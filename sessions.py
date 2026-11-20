"""Local PNG frame storage and animation export for the stop-motion workbench."""

import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps


SESSION_NAME = re.compile(r"session-(\d+)")
FRAME_NAME = re.compile(r"frame-(\d+)-[0-9a-f]{32}\.png")
BATCH_NAME = re.compile(r"batch-[0-9a-f]{32}")
NAME_NUMBERS = re.compile(r"([0-9]+)")
PHOTO_FORMATS = {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}
MAX_HOLD = 120
EDIT_FILE = "timeline.json"


@dataclass(frozen=True)
class TimelineFrame:
    image: Image.Image
    hold: int
    hidden: bool


@dataclass(frozen=True)
class FrameSettings:
    hold: int = 1
    hidden: bool = False


@dataclass(frozen=True)
class FrameEdit:
    name: str
    previous: FrameSettings
    updated: FrameSettings


DEFAULT_SETTINGS = FrameSettings()


def _natural_key(path: Path):
    parts = NAME_NUMBERS.split(path.name.casefold())
    tokens = tuple(int(part) if index % 2 else part for index, part in enumerate(parts))
    return tokens, path.name.casefold(), str(path)


def _visible_entries(items):
    return ((index, item) for index, item in enumerate(items) if not item.hidden)


def playback_order(items) -> tuple[int, ...]:
    """Map each slot in the final animation to its original frame index."""
    return tuple(index for index, item in _visible_entries(items) for _ in range(item.hold))


@contextmanager
def _atomic_output(destination):
    """Publish a completed file in one rename, including on Windows."""
    destination = Path(destination)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=".writing-", suffix=".tmp", delete=False
    ) as output:
        temporary = Path(output.name)
        try:
            yield output
            output.flush()
            os.fsync(output.fileno())
            output.close()
            os.replace(temporary, destination)
        finally:
            output.close()
            temporary.unlink(missing_ok=True)


class SessionStore:
    """Persist every capture immediately and reopen the most recent session."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._cache = {}
        self._undo_edits: list[FrameEdit] = []
        self._redo_edits: list[FrameEdit] = []
        sessions = self._sessions()
        if sessions:
            self.folder = sessions[-1][1]
        else:
            self.new_session()

    def _sessions(self):
        sessions = []
        base = self.base_dir.resolve()
        for path in self.base_dir.iterdir():
            matched = SESSION_NAME.fullmatch(path.name)
            if matched and path.is_dir() and path.resolve() == base / path.name:
                sessions.append((int(matched[1]), path))
        return sorted(sessions)

    def list_sessions(self) -> list[Path]:
        """Return local project folders in descending session number."""
        return [path for _, path in reversed(self._sessions())]

    def open_session(self, name: str) -> list[Image.Image]:
        """Switch projects only after successfully reading the selected frames."""
        folder = next((path for path in self.list_sessions() if path.name == name), None)
        if folder is None:
            raise ValueError("找不到所选作品。")

        cache = {}
        entries = self._frame_entries(folder)
        self._read_settings(folder, entries)
        frames = self._read_frames(entries, cache)
        self.folder = folder
        self._cache = cache
        self._clear_edit_history()
        return frames

    def new_session(self):
        sessions = self._sessions()
        number = sessions[-1][0] + 1 if sessions else 1
        while True:
            folder = self.base_dir / f"session-{number:04d}"
            try:
                folder.mkdir()
                break
            except FileExistsError:
                number += 1
        self.folder = folder
        self._cache.clear()
        self._clear_edit_history()

    def _clear_edit_history(self):
        self._undo_edits.clear()
        self._redo_edits.clear()

    def _frame_entries(self, folder):
        paths = list(folder.iterdir())
        base = folder.resolve()
        for path in tuple(paths):
            if BATCH_NAME.fullmatch(path.name) and path.is_dir() and path.resolve() == base / path.name:
                paths.extend(path.iterdir())
        entries = []
        for path in paths:
            matched = FRAME_NAME.fullmatch(path.name)
            if matched:
                entries.append((int(matched[1]), path))
        return sorted(entries)

    @property
    def frames(self) -> list[Image.Image]:
        return self._read_frames(self._frame_entries(self.folder), self._cache)

    def _read_frames(self, entries, cache):
        images = []
        for _, path in entries:
            if path not in cache:
                try:
                    with Image.open(path) as source:
                        cache[path] = source.convert("RGB")
                except OSError as error:
                    raise OSError(f"无法读取动画帧 {path.name}：{error}") from error
            images.append(cache[path])
        return images

    @property
    def timeline(self) -> list[TimelineFrame]:
        entries = self._frame_entries(self.folder)
        settings = self._read_settings(self.folder, entries)
        frames = self._read_frames(entries, self._cache)
        items = []
        for (_, path), frame in zip(entries, frames):
            edit = settings.get(path.name, DEFAULT_SETTINGS)
            items.append(TimelineFrame(frame, edit.hold, edit.hidden))
        return items

    @staticmethod
    def _read_settings(folder: Path, entries) -> dict[str, FrameSettings]:
        try:
            data = (folder / EDIT_FILE).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except UnicodeError as error:
            raise OSError(f"无法读取剪辑记录：{error}") from error

        try:
            document = json.loads(data)
            if not isinstance(document, dict) or type(document.get("version")) is not int or document["version"] != 1:
                raise ValueError("剪辑记录版本无效")
            frames = document.get("frames")
            if not isinstance(frames, dict):
                raise ValueError("剪辑记录缺少帧列表")

            names = {path.name for _, path in entries}
            settings = {}
            for name, value in frames.items():
                if name not in names:
                    continue
                if not isinstance(value, dict):
                    raise ValueError("帧设置无效")
                hold, hidden = value.get("hold"), value.get("hidden")
                if type(hold) is not int or not 1 <= hold <= MAX_HOLD or type(hidden) is not bool:
                    raise ValueError("帧停留或隐藏设置无效")
                settings[name] = FrameSettings(hold, hidden)
            return settings
        except ValueError as error:
            raise OSError(f"无法读取剪辑记录：{error}") from error

    def _write_setting(self, settings, name, value):
        if value == DEFAULT_SETTINGS:
            settings.pop(name, None)
        else:
            settings[name] = value
        frames = {key: {"hold": item.hold, "hidden": item.hidden} for key, item in settings.items()}
        document = json.dumps({"version": 1, "frames": frames}, indent=2, sort_keys=True)
        with _atomic_output(self.folder / EDIT_FILE) as output:
            output.write((document + "\n").encode("utf-8"))

    def edit_frame(self, index: int, *, hold: int | None = None, hidden: bool | None = None) -> bool:
        entries = self._frame_entries(self.folder)
        if type(index) is not int or not 0 <= index < len(entries):
            return False
        if hold is not None and (type(hold) is not int or not 1 <= hold <= MAX_HOLD):
            raise ValueError(f"帧停留须为 1–{MAX_HOLD} 格")
        if hidden is not None and type(hidden) is not bool:
            raise ValueError("隐藏状态必须为布尔值")
        settings = self._read_settings(self.folder, entries)
        name = entries[index][1].name
        previous = settings.get(name, DEFAULT_SETTINGS)
        updated = FrameSettings(
            previous.hold if hold is None else hold,
            previous.hidden if hidden is None else hidden,
        )
        if previous == updated:
            return False
        self._write_setting(settings, name, updated)
        self._undo_edits.append(FrameEdit(name, previous, updated))
        self._redo_edits.clear()
        return True

    @property
    def can_undo_edit(self) -> bool:
        return bool(self._undo_edits)

    @property
    def can_redo_edit(self) -> bool:
        return bool(self._redo_edits)

    def _move_edit(self, history, other, *, undo):
        if not history:
            return False
        change = history[-1]
        entries = self._frame_entries(self.folder)
        if not any(path.name == change.name for _, path in entries):
            self._clear_edit_history()
            return False
        settings = self._read_settings(self.folder, entries)
        expected = change.updated if undo else change.previous
        replacement = change.previous if undo else change.updated
        if settings.get(change.name, DEFAULT_SETTINGS) != expected:
            # A second window has changed this frame since the edit was recorded.
            self._clear_edit_history()
            return False
        self._write_setting(settings, change.name, replacement)
        other.append(history.pop())
        return True

    def undo_edit(self) -> bool:
        return self._move_edit(self._undo_edits, self._redo_edits, undo=True)

    def redo_edit(self) -> bool:
        return self._move_edit(self._redo_edits, self._undo_edits, undo=False)

    def import_images(self, paths: list[Path]) -> int:
        sources = sorted(map(Path, paths), key=_natural_key)
        if not sources:
            return 0
        entries = self._frame_entries(self.folder)
        first_number = entries[-1][0] + 1 if entries else 1
        destination = self.folder / f"batch-{uuid4().hex}"
        # An unfinished batch is never considered a frame source. Rename the
        # complete folder once so every imported frame becomes visible together.
        with tempfile.TemporaryDirectory(prefix=".importing-", dir=self.folder) as temporary:
            stage = Path(temporary)
            for index, source in enumerate(sources, first_number):
                try:
                    with Image.open(source, formats=sorted(PHOTO_FORMATS)) as image:
                        if getattr(image, "n_frames", 1) != 1:
                            raise ValueError("仅支持静态照片")
                        photo = ImageOps.exif_transpose(image).convert("RGB")
                except (OSError, ValueError, Image.DecompressionBombError) as error:
                    raise ValueError(f"无法导入 {source.name}：{error}") from error
                path = stage / f"frame-{index:06d}-{uuid4().hex}.png"
                with _atomic_output(path) as output:
                    photo.save(output, format="PNG")
            stage.rename(destination)
        return len(sources)

    def append(self, image: Image.Image):
        entries = self._frame_entries(self.folder)
        number = entries[-1][0] + 1 if entries else 1
        # A unique suffix prevents simultaneous captures overwriting each other.
        path = self.folder / f"frame-{number:06d}-{uuid4().hex}.png"
        frame = image.convert("RGB")
        with _atomic_output(path) as output:
            frame.save(output, format="PNG")
        self._cache[path] = frame

    def undo(self) -> bool:
        entries = self._frame_entries(self.folder)
        if not entries:
            return False
        path = entries[-1][1]
        path.unlink()
        self._cache.pop(path, None)
        self._undo_edits = [edit for edit in self._undo_edits if edit.name != path.name]
        self._redo_edits = [edit for edit in self._redo_edits if edit.name != path.name]
        return True

    def _export_frames(self, fps: int) -> list[TimelineFrame]:
        if type(fps) is not int or not 1 <= fps <= 100:
            raise ValueError("帧率必须是 1 至 100 之间的整数")
        frames = [frame for _, frame in _visible_entries(self.timeline)]
        if not frames:
            raise ValueError("请保留至少一张可见帧再导出")
        return frames

    def export_gif(self, path: Path, fps: int):
        timeline = self._export_frames(fps)

        # A camera change can produce frames with a different aspect ratio.
        size = timeline[0].image.size
        frames = [
            item.image if item.image.size == size else ImageOps.pad(item.image, size, color="black")
            for item in timeline
        ]
        # GIF delays have 10 ms resolution. Round cumulative times to avoid drift.
        delays = []
        elapsed = 0
        for item in timeline:
            end = elapsed + item.hold
            delays.append(10 * (round(end * 100 / fps) - round(elapsed * 100 / fps)))
            elapsed = end
        with _atomic_output(path) as output:
            frames[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=delays,
                loop=0,
                disposal=2,
            )


    def export_mp4(self, path: Path, fps: int) -> None:
        """Encode a silent, constant-frame-rate video, then publish it atomically."""
        frames = self._export_frames(fps)
        try:
            import cv2
        except ImportError as error:
            raise OSError("导出 MP4 需要 OpenCV。请运行启动脚本安装依赖。") from error
        import numpy as np

        source_size = frames[0].image.size
        expected_count = sum(frame.hold for frame in frames)
        video_size = tuple(side + side % 2 for side in source_size)
        # Keep the user-selected destination out of the native encoder. Python
        # handles its path and can replace the old export only after validation.
        with tempfile.TemporaryDirectory(prefix="stopmotion-mp4-") as temporary:
            staged = Path(temporary) / "video.mp4"
            video_path = str(staged)
            try:
                writer = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, video_size)
                try:
                    if not writer.isOpened():
                        raise OSError("无法启动 MP4 编码器。请确认 OpenCV 支持 mp4v。")
                    for item in frames:
                        frame = item.image
                        if frame.size != source_size:
                            frame = ImageOps.pad(frame, source_size, color="black")
                        # Video encoders often truncate odd dimensions. Add an
                        # extra row or column while retaining every input pixel.
                        if source_size != video_size:
                            padded = Image.new("RGB", video_size)
                            padded.paste(frame, (0, 0))
                            frame = padded
                        bgr = cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR)
                        for _ in range(item.hold):
                            writer.write(bgr)
                finally:
                    writer.release()

                if not staged.is_file() or not staged.stat().st_size:
                    raise OSError("MP4 编码器没有生成视频。")
                reader = cv2.VideoCapture(video_path)
                try:
                    ok, first = reader.read()
                    if (not ok or (first.shape[1], first.shape[0]) != video_size
                            or reader.get(cv2.CAP_PROP_FRAME_COUNT) != expected_count):
                        raise OSError("生成的 MP4 无法读取或帧数不完整。")
                finally:
                    reader.release()
            except cv2.error as error:
                raise OSError(f"MP4 编码失败：{error}") from error

            with staged.open("rb") as video, _atomic_output(path) as output:
                shutil.copyfileobj(video, output)
