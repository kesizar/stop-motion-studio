"""定格动画工作台的本机入口。"""
from bisect import bisect_left
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

from capture_region import CaptureRegion, measure_alignment
from sessions import SessionStore, playback_order
from shutter import ShutterGate
from sources import CameraFeed, DemoFeed
from studio_ui import StudioUI


DEMO_FRAME_LIMIT = 8
ALIGNMENT_INTERVAL = 0.4
ALIGNMENT_THRESHOLD = 4


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
        self.capture_region = None
        self.region_revision = 0
        self._region_selecting = False
        self._next_alignment = 0.0
        self._camera_moved = False
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
        self.inspection_index = None
        self.project_frames = []
        self.timeline = []
        self.play_order = ()
        self.play_index = 0
        self.play_position = 0
        self.next_frame = 0.0
        self.fps = 8
        self.ui = StudioUI(root, self)
        self.ui.set_source("本地作品")
        self._refresh()
        self._sync_capture_controls(time.monotonic())
        self.ui.set_status("固定好镜头，摆好第一帧，然后开始拍摄。也可以先体验模拟演示。")
        self.tick_id = root.after(40, self._tick)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _refresh(self):
        self.timeline = self.store.timeline
        self.play_order = playback_order(self.timeline)
        frames = [item.image for item in self.timeline]
        self.ui.set_project("" if self.demo_dir is not None else self.store.folder.name)
        self.project_frames = frames
        self.reference_frame = frames[-1] if frames else None
        self.ui.set_timeline(frames)
        self.ui.set_timeline_edits([(item.hold, item.hidden) for item in self.timeline])
        if self.inspection_index is not None and frames:
            self.inspection_index = min(self.inspection_index, len(frames) - 1)
            self._show_frame_index(self.inspection_index)
        else:
            self.inspection_index = None
            self.ui.set_reviewing(False)
            self.ui.set_frame_position(None)
            self._show_preview()
        self._sync_edit_controls()
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
        frame = np.asarray(ref)[:, :, ::-1] if ref is not None else None
        self.gate.reset(self._capture_area(frame) if frame is not None else None)

    def _capture_area(self, frame):
        return self.capture_region.crop(frame) if self.capture_region else frame

    def set_region_selecting(self, active):
        self._region_selecting = bool(active) and self._has_live_preview()
        self._reset_gate()
        self.ui.set_capture_progress(None)
        self._sync_capture_controls(time.monotonic())

    def set_capture_region(self, rectangle):
        if not self._has_live_preview():
            return
        try:
            region = CaptureRegion(*rectangle) if rectangle is not None else None
        except ValueError:
            self.ui.set_status("拍摄区域太小。请在画面里拖出更大的矩形。")
            return
        if region == self.capture_region:
            return
        self.capture_region = region
        self._reset_live_observation()
        if self.camera is not None:
            self.region_revision, self.seen_hand = self.camera.set_region(region)
        self._sync_capture_controls(time.monotonic())
        text = "拍摄区域已更新。摆放道具时请把手伸进框内。" if region else "已恢复全画面检测。"
        self.ui.set_status(text)

    def _update_alignment(self, frame, hand_present, now):
        if self.camera is None or self.reference_frame is None:
            return
        if hand_present:
            self._next_alignment = 0.0
            return
        if now < self._next_alignment:
            return
        self._next_alignment = now + ALIGNMENT_INTERVAL
        reference = np.asarray(self.reference_frame)[:, :, ::-1]
        measurement = measure_alignment(reference, frame)
        self._camera_moved = measurement is not None and measurement.distance >= ALIGNMENT_THRESHOLD
        if measurement is None:
            text = "机位参考不足"
        elif self._camera_moved:
            text = f"机位偏移约 {measurement.distance:.0f} 像素"
        else:
            text = "机位与上帧对齐"
        self.ui.set_alignment_status(text)

    def _has_live_preview(self):
        return (
            not self.playing
            and self.inspection_index is None
            and (self.camera is not None or self.demo is not None)
        )

    def _can_capture(self, now):
        return (
            self._has_live_preview()
            and self.auto_paused
            and not self._region_selecting
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
        region = self.capture_region if self._has_live_preview() else None
        bounds = (region.left, region.top, region.right, region.bottom) if region is not None else None
        self.ui.set_region_controls(
            available=self._has_live_preview() and self.latest_frame is not None,
            region=bounds,
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
        self._reset_alignment()
        if self.camera is not None:
            self.ui.set_alignment_status("已更新机位参考")
        self.wait_for_hand = False
        self.capture_notice = (now + 0.8, f"已{mode}拍下第 {count} 帧。")
        if self.demo is not None and count >= DEMO_FRAME_LIMIT:
            self.stop_source()
            self.ui.set_capture_progress(1, captured=True)
            self.ui.set_status(f"演示已拍好 {count} 帧。点「回放」看纸船移动，或导出 GIF / MP4。")
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
        self.capture_region = None
        self.region_revision = 0
        self._region_selecting = False
        self._reset_alignment()
        self.latest_frame = None
        self.last_observation = None
        self.capture_notice = None
        self.auto_paused = False
        self.wait_for_hand = False
        self._stop_playback()
        self.inspection_index = None
        self.ui.set_reviewing(False)
        self.ui.set_frame_position(None)
        self._show_preview()
        self.ui.set_capture_progress(None)
        self._sync_capture_controls(time.monotonic())
        self._sync_edit_controls()
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
            if self.playing:
                self.next_frame = 0.0
            elif self._has_live_preview():
                self._reset_live_observation()
                self._sync_capture_controls(time.monotonic())

    def _reset_alignment(self):
        self._next_alignment = 0.0
        self._camera_moved = False
        self.ui.set_alignment_status("")

    def _reset_live_observation(self):
        self._reset_alignment()
        self.latest_frame = None
        self.last_observation = None
        self.capture_notice = None
        if self.camera is not None:
            self.seen_hand = self.camera.hand_sequence
        self._reset_gate()
        self.ui.set_capture_progress(None)

    def open_project_dialog(self):
        current = self.real_store.folder.name
        try:
            names = [folder.name for folder in self.real_store.list_sessions()]
            selected = self._run_dialog(self.ui.choose_project, names, current)
            if selected is None or (selected == current and self.demo_dir is None):
                return
            self.real_store.open_session(selected)
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法打开作品", str(exc), parent=self.root)
            return

        self.stop_source()
        self._use_real_store()
        count = self._refresh()
        self._reset_gate()
        self.ui.set_source("本地作品")
        self.ui.set_status(f"已打开作品，共 {count} 张原图。打开摄像头继续拍摄。")

    def new_project(self):
        self.stop_source()
        self._use_real_store()
        self.store.new_session()
        self._refresh()
        self._reset_gate()
        self.ui.set_source("本地作品")
        self.ui.set_status("新作品已就绪。上一部作品的原图保存在「作品」目录。")

    def import_images(self):
        filenames = self._run_dialog(
            filedialog.askopenfilenames, parent=self.root, title="导入照片序列到本地作品",
            filetypes=[("照片", ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp", "*.tif", "*.tiff"))],
        )
        if not filenames:
            return
        self.ui.set_status("正在读取并导入照片……")
        self.root.update_idletasks()
        try:
            count = self.real_store.import_images([Path(name) for name in filenames])
        except (OSError, ValueError) as exc:
            self.ui.set_status("导入失败。")
            messagebox.showerror("无法导入照片", str(exc), parent=self.root)
            return
        self.stop_source()
        self._use_real_store()
        self._refresh()
        self._reset_gate()
        self.ui.set_source("本地作品")
        self.ui.set_status(f"已按文件名顺序导入 {count} 张照片。可检查、编辑或继续拍摄。")

    def undo(self):
        if not self.project_frames:
            return
        self._stop_playback()
        self.store.undo()
        self._refresh()
        self._reset_gate()
        self._reset_alignment()
        self.wait_for_hand = True
        self.capture_notice = None
        self.ui.set_capture_progress(None)
        self._sync_capture_controls(time.monotonic())
        self.ui.set_status("已撤回一帧。再次伸手摆放道具后继续拍摄。")

    def _sync_edit_controls(self):
        item = self.timeline[self.inspection_index] if self.inspection_index is not None else None
        self.ui.set_edit_controls(
            available=item is not None,
            hold=item.hold if item else 1,
            hidden=item.hidden if item else False,
            can_undo=self.store.can_undo_edit,
            can_redo=self.store.can_redo_edit,
        )

    def _apply_edit(self, action, status, *args, **kwargs):
        try:
            if not action(*args, **kwargs):
                return
        except (OSError, ValueError) as exc:
            self._sync_edit_controls()
            messagebox.showerror("无法保存剪辑", str(exc), parent=self.root)
            return
        if self.playing:
            self._stop_playback()
            self.inspection_index = self.play_position
            self.ui.set_reviewing(True)
        self._refresh()
        self.ui.set_status(status)

    def set_selected_hold(self, value):
        if self.inspection_index is not None:
            self._apply_edit(
                self.store.edit_frame, f"已将这张照片设为停留 {value} 格。",
                self.inspection_index, hold=value,
            )

    def toggle_selected_hidden(self):
        if self.inspection_index is not None:
            index = self.inspection_index
            hidden = not self.timeline[index].hidden
            status = "已从成片隐藏，原图仍在时间轴。" if hidden else "已恢复显示这张照片。"
            self._apply_edit(self.store.edit_frame, status, index, hidden=hidden)

    def undo_edit(self):
        self._apply_edit(self.store.undo_edit, "已撤销上一步剪辑。")

    def redo_edit(self):
        self._apply_edit(self.store.redo_edit, "已重做上一步剪辑。")

    def set_fps(self, fps):
        self.fps = min(16, max(2, int(fps)))
        self.next_frame = 0.0

    def _show_frame_index(self, index):
        self.ui.show_frame(self.project_frames[index])
        self.ui.set_frame_position(index)

    def seek_frame(self, index):
        if not 0 <= index < len(self.project_frames):
            return
        self._stop_playback()
        self.inspection_index = index
        self.ui.set_reviewing(True)
        self.ui.set_capture_progress(None)
        self._sync_capture_controls(time.monotonic())
        self._show_frame_index(index)
        self._sync_edit_controls()
        self.ui.set_status(f"正在检查第 {index + 1} 帧。可以设置停留时长或从成片隐藏。")

    def step_frame(self, delta):
        if not self.project_frames:
            return
        last = len(self.project_frames) - 1
        if self.playing:
            index = self.play_position + delta
        elif self.inspection_index is None:
            index = last
        else:
            index = self.inspection_index + delta
        self.seek_frame(max(0, min(last, index)))

    def resume_preview(self):
        self._stop_playback()
        self.inspection_index = None
        self.ui.set_reviewing(False)
        self.ui.set_frame_position(None)
        self._reset_live_observation()
        self._sync_capture_controls(time.monotonic())
        self._sync_edit_controls()
        self._show_preview()
        if self._has_live_preview():
            self.ui.set_status("已返回取景。")
        else:
            self.ui.set_status("已退出查看。可以打开摄像头或继续回放。")

    def playback(self):
        if self.playing:
            self.resume_preview()
        elif self.play_order:
            start = bisect_left(self.play_order, self.inspection_index or 0) % len(self.play_order)
            self.play_index = start
            self.play_position = self.play_order[start]
            self.next_frame = 0.0
            self.inspection_index = None
            self.playing = True
            self.ui.set_reviewing(False)
            self.ui.set_playing(True)
            self.ui.set_capture_progress(None)
            self._sync_capture_controls(time.monotonic())
            self._show_frame_index(self.play_position)
            self._sync_edit_controls()
            self.ui.set_status(f"正在回放成片，共 {len(self.play_order)} 格。点击时间轴可以停在指定帧。")

    def export_gif(self):
        self._export_animation("gif", "GIF 动画", self.store.export_gif)

    def export_mp4(self):
        self._export_animation("mp4", "MP4 视频", self.store.export_mp4)

    def _export_animation(self, extension, label, exporter):
        if not self.play_order:
            return
        filename = self._run_dialog(
            filedialog.asksaveasfilename, parent=self.root, title=f"导出{label}",
            defaultextension=f".{extension}", filetypes=[(label, f"*.{extension}")],
            initialfile=f"我的定格动画.{extension}", initialdir=self.real_store.folder.parent,
        )
        if not filename:
            return
        self.ui.set_status(f"正在导出{label}……")
        self.root.update_idletasks()
        try:
            exporter(Path(filename), self.fps)
        except (OSError, ValueError) as exc:
            self.ui.set_status(f"{label}导出失败。")
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return
        self.ui.set_status(f"{label}已导出到 {filename}")

    def _observe(self, frame, hand_present, now):
        # A stalled source provides no evidence of stability over the missing interval.
        if self.last_observation is not None and now - self.last_observation > 1.2:
            self._reset_gate()
        self.last_observation = now
        image = Image.fromarray(frame[:, :, ::-1].copy())
        self.latest_frame = (image, hand_present)
        self._show_preview()
        self._sync_capture_controls(now)
        if self._region_selecting:
            self.ui.set_status("拖动鼠标画出检测区，松开确认，Esc 取消。")
            return
        self._update_alignment(frame, hand_present, now)
        if self.auto_paused:
            status = "自动快门已暂停。"
            if hand_present:
                status += "移开手后可以手动拍一帧。"
            self._show_capture_status(now, None, status)
            return
        if self.wait_for_hand and not hand_present:
            return
        if self._camera_moved and not hand_present:
            self._reset_gate()
            self._show_capture_status(now, None, "检测到机位偏移，请放回原位后重新摆放道具。")
            return
        self.wait_for_hand = False
        capture, status = self.gate.update(self._capture_area(frame), hand_present, now)
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
                if not self.next_frame:
                    self.next_frame = now
                skipped = int((now - self.next_frame) * self.fps)
                self.play_index += skipped
                self.play_position = self.play_order[self.play_index % len(self.play_order)]
                self._show_frame_index(self.play_position)
                self.play_index += 1
                self.next_frame += (skipped + 1) / self.fps
            return
        if self.inspection_index is not None:
            return
        if self.demo:
            frame, hand = self.demo.read(now, self.capture_region)
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
            frame, hand, stamp, sequence, revision = item
            if revision != self.region_revision:
                return
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
