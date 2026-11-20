"""定格动画工作台的本机入口。"""
import os
import queue
import shutil
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import numpy as np
from PIL import Image

from sessions import SessionStore
from shutter import ShutterGate
from sources import CameraFeed, DemoFeed
from studio_ui import StudioUI


DEMO_FRAME_LIMIT = 8


def create_window():
    """Make Tcl/Tk scripts accessible when a WindowsApps Python backs the venv."""
    base = Path(sys.base_prefix)
    prefix = Path(sys.prefix)
    if os.name == "nt" and prefix != base and "windowsapps" in (part.lower() for part in base.parts):
        # Python can read the packaged files, but native Tcl may not see them
        # when started from Explorer. Use scripts from this exact interpreter.
        cache = prefix / f"tk-runtime-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        tcl_dir = f"tcl{tk.TclVersion}"
        tk_dir = f"tk{tk.TkVersion}"
        if not cache.is_dir():
            with tempfile.TemporaryDirectory(dir=prefix) as temporary:
                staging = Path(temporary) / "libraries"
                for name in (tcl_dir, tk_dir):
                    shutil.copytree(base / "tcl" / name, staging / name)
                try:
                    staging.rename(cache)
                except FileExistsError:
                    # A second launch finished copying the same libraries first.
                    pass
        os.environ["TCL_LIBRARY"] = (cache / tcl_dir).as_posix()
        os.environ["TK_LIBRARY"] = (cache / tk_dir).as_posix()
    return tk.Tk()


class Studio:
    def __init__(self, root, base_dir):
        self.root = root
        self.real_store = SessionStore(base_dir)
        self.store = self.real_store
        self.demo_dir = None
        self.camera = None
        self.retiring = []
        self.demo = None
        self.seen_hand = 0
        self.last_observation = None
        self.latest_frame = None
        self.reference_frame = None
        self.capture_notice = None
        self._dialog_open = False
        self.onion_skin = False
        self.auto_paused = False
        self.wait_for_hand = False
        self.gate = ShutterGate()
        self.playing = False
        self.play_index = 0
        self.next_frame = 0.0
        self.fps = 8
        self.ui = StudioUI(root, self)
        self.ui.set_source("本地作品")
        self._refresh()
        self._sync_capture_controls(time.monotonic())
        self.ui.set_status("固定好镜头，摆好第一帧，然后开始拍摄。也可以先体验模拟演示。")
        self.tick_id = root.after(40, self._tick)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _refresh(self, frames=None):
        if frames is None:
            frames = self.store.frames
        self.ui.set_project("" if self.demo_dir is not None else self.store.folder.name)
        self.reference_frame = frames[-1] if frames else None
        self.ui.set_timeline(frames)
        self._show_preview()
        return len(frames)

    def _show_preview(self):
        if self.latest_frame is None:
            self.ui.show_frame(self.reference_frame)
            return
        image, _ = self.latest_frame
        reference = self.reference_frame
        if self.onion_skin and reference is not None and reference.size == image.size:
            image = Image.blend(image, reference, 0.30)
        self.ui.show_frame(image)

    def _reset_gate(self):
        ref = self.reference_frame
        self.gate.reset(np.asarray(ref)[:, :, ::-1] if ref is not None else None)

    def _has_live_preview(self):
        return not self.playing and (self.camera is not None or self.demo is not None)

    def _can_capture(self, now):
        return (
            self._has_live_preview()
            and self.auto_paused
            and self.latest_frame is not None
            and not self.latest_frame[1]
            and 0 <= now - self.last_observation <= self.gate.max_gap_seconds
        )

    def _sync_capture_controls(self, now):
        self.ui.set_capture_controls(
            available=self._has_live_preview(),
            paused=self.auto_paused,
            can_capture=self._can_capture(now),
        )

    def set_onion_skin(self, enabled):
        self.onion_skin = enabled
        if self._has_live_preview():
            self._show_preview()

    def toggle_auto_pause(self):
        if not self._has_live_preview():
            return
        self.auto_paused = not self.auto_paused
        self.capture_notice = None
        self._reset_gate()
        self.ui.set_capture_progress(None)
        self._sync_capture_controls(time.monotonic())
        if self.auto_paused:
            self.ui.set_status("自动快门已暂停。移开手后可以手动拍一帧。")
        else:
            self.ui.set_status("自动快门已恢复。")

    def manual_capture(self):
        now = time.monotonic()
        if not self._can_capture(now):
            return
        image, _ = self.latest_frame
        try:
            self._save_frame(image, now, "手动")
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)

    def _save_frame(self, image, now, mode):
        self.store.append(image)
        count = self._refresh()
        self.wait_for_hand = False
        self.capture_notice = (now + 0.8, f"已{mode}拍下第 {count} 帧。")
        if self.demo is not None and count >= DEMO_FRAME_LIMIT:
            self.stop_source()
            self.ui.set_capture_progress(1, captured=True)
            self.ui.set_status(f"演示已拍好 {count} 帧。点「回放」看纸船移动，或导出 GIF。")
            return
        self._show_capture_status(now, None, "")

    def _show_capture_status(self, now, progress, status):
        if self.capture_notice is not None:
            expires, message = self.capture_notice
            if now < expires:
                self.ui.set_capture_progress(1, captured=True)
                self.ui.set_status(message)
                return
            self.capture_notice = None
        self.ui.set_capture_progress(progress)
        self.ui.set_status(status)

    def _stop_playback(self):
        self.playing = False
        self.ui.set_playing(False)

    def stop_source(self):
        if self.camera is not None:
            self.camera.close()
            self.retiring.append(self.camera)
            self.camera = None
        self.demo = None
        self.latest_frame = None
        self.last_observation = None
        self.capture_notice = None
        self.auto_paused = False
        self.wait_for_hand = False
        self._stop_playback()
        self._show_preview()
        self.ui.set_capture_progress(None)
        self._sync_capture_controls(time.monotonic())
        self.ui.set_source("模拟作品" if self.demo_dir else "本地作品")
        self.ui.set_status("已停止拍摄。可以回放、撤回或导出当前作品。")

    def _use_real_store(self):
        self.store = self.real_store
        if self.demo_dir is not None:
            self.demo_dir.cleanup()
            self.demo_dir = None

    def start_camera(self, index):
        self.stop_source()
        self._use_real_store()
        self._refresh()
        self._reset_gate()
        self.seen_hand = 0
        self.camera = CameraFeed(index)
        self._sync_capture_controls(time.monotonic())
        self.ui.set_source(f"摄像头 {index}")
        self.ui.set_status("正在连接摄像头并加载 MediaPipe 手部模型……")
        # Start after any previous worker has released the physical camera.

    def start_demo(self):
        self.stop_source()
        self._use_real_store()
        self.demo_dir = tempfile.TemporaryDirectory(prefix="stopmotion-demo-")
        self.store = SessionStore(Path(self.demo_dir.name))
        self._refresh()
        self._reset_gate()
        self.demo = DemoFeed()
        self._sync_capture_controls(time.monotonic())
        self.ui.set_source("模拟演示")
        self.ui.set_status(f"模拟纸船摆拍。拍满 {DEMO_FRAME_LIMIT} 帧后可以直接回放。")

    def _run_dialog(self, callback, *args, **kwargs):
        # Tk keeps processing scheduled events while a modal dialog is open.
        self._dialog_open = True
        try:
            return callback(*args, **kwargs)
        finally:
            self._dialog_open = False
            if self._has_live_preview():
                self.latest_frame = None
                self.last_observation = None
                self.capture_notice = None
                if self.camera is not None:
                    self.seen_hand = self.camera.hand_sequence
                self._reset_gate()
                self.ui.set_capture_progress(None)
                self._sync_capture_controls(time.monotonic())

    def open_project_dialog(self):
        current = self.real_store.folder.name
        try:
            names = [folder.name for folder in self.real_store.list_sessions()]
            selected = self._run_dialog(self.ui.choose_project, names, current)
            if selected is None or (selected == current and self.demo_dir is None):
                return
            frames = self.real_store.open_session(selected)
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法打开作品", str(exc), parent=self.root)
            return

        self.stop_source()
        self._use_real_store()
        self._refresh(frames)
        self._reset_gate()
        self.ui.set_source("本地作品")
        self.ui.set_status(f"已打开作品，共 {len(frames)} 帧。打开摄像头继续拍摄。")

    def new_project(self):
        self.stop_source()
        self._use_real_store()
        self.store.new_session()
        self._refresh()
        self._reset_gate()
        self.ui.set_source("本地作品")
        self.ui.set_status("新作品已就绪。上一部作品的原图保存在「作品」目录。")

    def undo(self):
        if not self.store.frames:
            return
        self._stop_playback()
        self.store.undo()
        self._refresh()
        self._reset_gate()
        self.wait_for_hand = True
        self.capture_notice = None
        self.ui.set_capture_progress(None)
        self._sync_capture_controls(time.monotonic())
        self.ui.set_status("已撤回一帧。再次伸手摆放道具后继续拍摄。")

    def set_fps(self, fps):
        self.fps = min(16, max(2, int(fps)))

    def playback(self):
        if self.playing:
            self._stop_playback()
            self._reset_gate()
            self._refresh()
            self._sync_capture_controls(time.monotonic())
            self.ui.set_status("回放已结束。")
        elif self.store.frames:
            self.playing = True
            self.latest_frame = None
            self.last_observation = None
            self.capture_notice = None
            self.ui.set_capture_progress(None)
            self._sync_capture_controls(time.monotonic())
            self.play_index = 0
            self.next_frame = 0.0
            self.ui.set_playing(True)
            self.ui.set_status("正在循环回放。结束回放后可以继续拍摄。")

    def export_gif(self):
        if not self.store.frames:
            return
        filename = self._run_dialog(
            filedialog.asksaveasfilename, parent=self.root, title="保存定格动画",
            defaultextension=".gif", filetypes=[("GIF 动画", "*.gif")],
            initialfile="我的定格动画.gif", initialdir=self.real_store.folder.parent,
        )
        if filename:
            try:
                self.store.export_gif(Path(filename), self.fps)
            except (OSError, ValueError) as exc:
                messagebox.showerror("导出失败", str(exc), parent=self.root)
                return
            self.ui.set_status(f"动画已导出到 {filename}")

    def _observe(self, frame, hand_present, now):
        # A stalled source provides no evidence of stability over the missing interval.
        if self.last_observation is not None and now - self.last_observation > 1.2:
            self._reset_gate()
        self.last_observation = now
        image = Image.fromarray(frame[:, :, ::-1].copy())
        self.latest_frame = (image, hand_present)
        self._show_preview()
        self._sync_capture_controls(now)
        if self.auto_paused:
            status = "自动快门已暂停。"
            if hand_present:
                status += "移开手后可以手动拍一帧。"
            self._show_capture_status(now, None, status)
            return
        if self.wait_for_hand and not hand_present:
            return
        self.wait_for_hand = False
        capture, status = self.gate.update(frame, hand_present, now)
        if capture:
            self._save_frame(image, now, "自动")
        else:
            self._show_capture_status(now, self.gate.settle_progress, status)

    def _step(self, now):
        self.retiring = [worker for worker in self.retiring if worker.thread.is_alive()]
        if self._dialog_open:
            return
        if self.playing:
            if now >= self.next_frame:
                frames = self.store.frames
                self.ui.show_frame(frames[self.play_index % len(frames)])
                self.play_index += 1
                self.next_frame = now + 1.0 / self.fps
            return
        if self.demo:
            frame, hand = self.demo.read(now)
            self._observe(frame, hand, now)
        elif self.camera:
            if self.camera.thread.ident is None and not self.retiring:
                self.camera.start()
            try:
                item = self.camera.latest.get_nowait()
            except queue.Empty:
                if (self.latest_frame is not None
                        and now - self.last_observation > self.gate.max_gap_seconds):
                    self.latest_frame = None
                    self.capture_notice = None
                    self.ui.set_capture_progress(None)
                    self._sync_capture_controls(now)
                    self.ui.set_status("等待摄像头画面……")
                return
            if isinstance(item, str):
                self.stop_source()
                self.ui.set_status(item)
                messagebox.showerror("摄像头未就绪", item, parent=self.root)
                return
            frame, hand, stamp, sequence = item
            observed_hand = hand or sequence != self.seen_hand
            self.seen_hand = sequence
            self._observe(frame, observed_hand, stamp)

    def _tick(self):
        try:
            self._step(time.monotonic())
        except Exception as exc:
            self.stop_source()
            self.ui.set_status(f"拍摄已暂停：{exc}")
            messagebox.showerror("拍摄已暂停", str(exc), parent=self.root)
        self.tick_id = self.root.after(40, self._tick)

    def close(self):
        self.root.after_cancel(self.tick_id)
        self.stop_source()
        self._use_real_store()
        self.ui.cancel_pending_draws()
        self.root.destroy()


if __name__ == "__main__":
    root = create_window()
    studio = Studio(root, Path(__file__).resolve().parent / "作品")
    if '--demo' in sys.argv:
        studio.start_demo()
    root.mainloop()
