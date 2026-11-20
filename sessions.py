"""Local PNG frame storage and GIF export for the stop-motion workbench."""

import os
import re
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
        for path in self.base_dir.iterdir():
            matched = SESSION_NAME.fullmatch(path.name)
            if matched and path.is_dir():
                sessions.append((int(matched[1]), path))
        return sorted(sessions)

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

    def _frame_entries(self):
        entries = []
        for path in self.folder.iterdir():
            matched = FRAME_NAME.fullmatch(path.name)
            if matched:
                entries.append((int(matched[1]), path))
        return sorted(entries)

    @property
    def frames(self) -> list[Image.Image]:
        images = []
        for _, path in self._frame_entries():
            if path not in self._cache:
                try:
                    with Image.open(path) as source:
                        self._cache[path] = source.convert("RGB")
                except OSError as error:
                    raise OSError(f"无法读取动画帧 {path.name}：{error}") from error
            images.append(self._cache[path])
        return images

    def append(self, image: Image.Image):
        entries = self._frame_entries()
        number = entries[-1][0] + 1 if entries else 1
        # A unique suffix prevents simultaneous captures overwriting each other.
        path = self.folder / f"frame-{number:06d}-{uuid4().hex}.png"
        frame = image.convert("RGB")
        with _atomic_output(path) as output:
            frame.save(output, format="PNG")
        self._cache[path] = frame

    def undo(self) -> bool:
        entries = self._frame_entries()
        if not entries:
            return False
        path = entries[-1][1]
        path.unlink()
        self._cache.pop(path, None)
        return True

    def export_gif(self, path: Path, fps: int):
        if type(fps) is not int or not 1 <= fps <= 100:
            raise ValueError("帧率必须是 1 至 100 之间的整数")
        frames = self.frames
        if not frames:
            raise ValueError("请先拍摄至少一帧")

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
