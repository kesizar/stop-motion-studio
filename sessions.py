"""Local PNG frame storage and animation export for the stop-motion workbench."""

import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps


SESSION_NAME = re.compile(r"session-(\d+)")
FRAME_NAME = re.compile(r"frame-(\d+)-[0-9a-f]{32}\.png")


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
        frames = self._read_frames(folder, cache)
        self.folder = folder
        self._cache = cache
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

    def _frame_entries(self, folder):
        entries = []
        for path in folder.iterdir():
            matched = FRAME_NAME.fullmatch(path.name)
            if matched:
                entries.append((int(matched[1]), path))
        return sorted(entries)

    @property
    def frames(self) -> list[Image.Image]:
        return self._read_frames(self.folder, self._cache)

    def _read_frames(self, folder, cache):
        images = []
        for _, path in self._frame_entries(folder):
            if path not in cache:
                try:
                    with Image.open(path) as source:
                        cache[path] = source.convert("RGB")
                except OSError as error:
                    raise OSError(f"无法读取动画帧 {path.name}：{error}") from error
            images.append(cache[path])
        return images

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
        return True

    def _export_frames(self, fps: int) -> list[Image.Image]:
        if type(fps) is not int or not 1 <= fps <= 100:
            raise ValueError("帧率必须是 1 至 100 之间的整数")
        frames = self.frames
        if not frames:
            raise ValueError("请先拍摄至少一帧")
        return frames

    def export_gif(self, path: Path, fps: int):
        frames = self._export_frames(fps)

        # A camera change can produce frames with a different aspect ratio.
        size = frames[0].size
        frames = [
            frame if frame.size == size else ImageOps.pad(frame, size, color="black")
            for frame in frames
        ]
        # GIF delays have 10 ms resolution. Round cumulative times to avoid drift.
        delays = [
            10 * (round((index + 1) * 100 / fps) - round(index * 100 / fps))
            for index in range(len(frames))
        ]
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

        source_size = frames[0].size
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
                    for frame in frames:
                        if frame.size != source_size:
                            frame = ImageOps.pad(frame, source_size, color="black")
                        # Video encoders often truncate odd dimensions. Add an
                        # extra row or column while retaining every input pixel.
                        if source_size != video_size:
                            padded = Image.new("RGB", video_size)
                            padded.paste(frame, (0, 0))
                            frame = padded
                        writer.write(cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR))
                finally:
                    writer.release()

                if not staged.is_file() or not staged.stat().st_size:
                    raise OSError("MP4 编码器没有生成视频。")
                reader = cv2.VideoCapture(video_path)
                try:
                    ok, first = reader.read()
                    if (not ok or (first.shape[1], first.shape[0]) != video_size
                            or reader.get(cv2.CAP_PROP_FRAME_COUNT) != len(frames)):
                        raise OSError("生成的 MP4 无法读取或帧数不完整。")
                finally:
                    reader.release()
            except cv2.error as error:
                raise OSError(f"MP4 编码失败：{error}") from error

            with staged.open("rb") as video, _atomic_output(path) as output:
                shutil.copyfileobj(video, output)
