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
        self.wait_for_hand = False
        self.gate = ShutterGate()
        self.playing = False
        self.play_index = 0
        self.next_frame = 0.0
        self.fps = 8
        self.ui = StudioUI(root, self)
        self.ui.set_source("本地作品")
        self._refresh()
        self.ui.set_status("固定好镜头，摆好第一帧，然后开始拍摄。也可以先体验模拟演示。")
        self.tick_id = root.after(40, self._tick)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _refresh(self):
        frames = self.store.frames
        self.ui.set_timeline(frames)
        if frames:
            self.ui.show_frame(frames[-1])
        else:
            self.ui.show_frame(None)

    def _reset_gate(self):
        frames = self.store.frames
        ref = np.asarray(frames[-1])[:, :, ::-1] if frames else None
        self.gate.reset(ref)
        self.wait_for_hand = False
        self.last_observation = None

    def _stop_playback(self):
        self.playing = False
        self.ui.set_playing(False)

    def stop_source(self):
        if self.camera is not None:
            self.camera.close()
            self.retiring.append(self.camera)
            self.camera = None
        self.demo = None
        self._stop_playback()
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
        self.ui.set_source("模拟演示")
        self.ui.set_status("模拟纸船摆拍。手部信号来自脚本，可回放并导出。")

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
        self.ui.set_status("已撤回一帧。再次伸手摆放道具后继续拍摄。")

    def set_fps(self, fps):
        self.fps = min(16, max(2, int(fps)))

    def playback(self):
        if self.playing:
            self._stop_playback()
            self._reset_gate()
            self._refresh()
            self.ui.set_status("回放已结束。")
        elif self.store.frames:
            self.playing = True
            self.play_index = 0
            self.next_frame = 0.0
            self.ui.set_playing(True)
            self.ui.set_status("正在循环回放。结束回放后可以继续拍摄。")

    def export_gif(self):
        if not self.store.frames:
            return
        filename = filedialog.asksaveasfilename(parent=self.root, title="保存定格动画",
                    defaultextension=".gif", filetypes=[("GIF 动画", "*.gif")],
                    initialfile="我的定格动画.gif", initialdir=self.real_store.folder.parent)
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
            waiting = self.wait_for_hand
            self._reset_gate()
            self.wait_for_hand = waiting
        self.last_observation = now
        image = Image.fromarray(frame[:, :, ::-1].copy())
        self.ui.show_frame(image)
        if self.wait_for_hand and not hand_present:
            return
        self.wait_for_hand = False
        capture, status = self.gate.update(frame, hand_present, now)
        if capture:
            self.store.append(image)
            self.ui.set_timeline(self.store.frames)
            status = f"已收下第 {len(self.store.frames)} 帧。可以摆下一个动作。"
        self.ui.set_status(status)

    def _step(self, now):
        self.retiring = [worker for worker in self.retiring if worker.thread.is_alive()]
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
        self.root.destroy()


if __name__ == "__main__":
    root = create_window()
    studio = Studio(root, Path(__file__).resolve().parent / "作品")
    if '--demo' in sys.argv:
        studio.start_demo()
    root.mainloop()
