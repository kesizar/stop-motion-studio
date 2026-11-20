import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from sessions import SessionStore


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = SessionStore(self.root / "sessions")

    def test_capture_order_rgb_restart_and_undo(self):
        self.store.append(Image.new("L", (4, 4), 25))
        self.store.append(Image.new("RGB", (4, 4), "red"))
        resumed = SessionStore(self.store.base_dir)
        self.assertEqual(resumed.folder, self.store.folder)
        self.assertEqual([frame.mode for frame in resumed.frames], ["RGB", "RGB"])
        self.assertEqual([frame.getpixel((0, 0)) for frame in resumed.frames],
                         [(25, 25, 25), (255, 0, 0)])
        self.assertTrue(resumed.undo())
        self.assertEqual(len(SessionStore(self.store.base_dir).frames), 1)
        self.assertTrue(resumed.undo())
        self.assertFalse(resumed.undo())

    def test_new_session_preserves_previous_frames_and_reopens_empty(self):
        self.store.append(Image.new("RGB", (4, 4), "red"))
        old_folder = self.store.folder
        self.store.new_session()
        self.assertEqual(len(list(old_folder.glob("*.png"))), 1)
        self.assertNotEqual(old_folder, self.store.folder)
        resumed = SessionStore(self.store.base_dir)
        self.assertEqual(resumed.folder, self.store.folder)
        self.assertEqual(resumed.frames, [])

    def test_list_open_and_continue_an_older_project(self):
        self.store.append(Image.new("RGB", (4, 4), "red"))
        old_folder = self.store.folder
        self.store.new_session()
        self.store.append(Image.new("RGB", (4, 4), "blue"))
        new_folder = self.store.folder
        (self.store.base_dir / "notes").mkdir()
        (self.store.base_dir / "session-0003").touch()

        self.assertEqual(self.store.list_sessions(), [new_folder, old_folder])
        reopened = self.store.open_session(old_folder.name)
        self.assertEqual([frame.getpixel((0, 0)) for frame in reopened], [(255, 0, 0)])
        self.store.append(Image.new("RGB", (4, 4), "green"))
        self.assertEqual(
            [frame.getpixel((0, 0)) for frame in self.store.frames],
            [(255, 0, 0), (0, 128, 0)],
        )
        self.assertEqual(len(list(new_folder.glob("*.png"))), 1)
        self.assertEqual(SessionStore(self.store.base_dir).folder, new_folder)

    def test_failed_open_keeps_current_project(self):
        old_folder = self.store.folder
        corrupt = old_folder / f"frame-000001-{'0' * 32}.png"
        corrupt.write_bytes(b"not a PNG")
        self.store.new_session()
        self.store.append(Image.new("RGB", (4, 4), "blue"))
        current_folder = self.store.folder

        for name in ("../" + old_folder.name, old_folder.as_posix(), "session-9999", old_folder.name.upper()):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.open_session(name)
        with self.assertRaises(OSError):
            self.store.open_session(old_folder.name)
        self.assertEqual(self.store.folder, current_folder)
        self.assertEqual([frame.getpixel((0, 0)) for frame in self.store.frames], [(0, 0, 255)])

    def test_gif_order_loop_timing_and_mixed_sizes(self):
        for size, color in [((8, 8), "red"), ((8, 4), "green"), ((8, 8), "blue")]:
            self.store.append(Image.new("RGB", size, color))
        path = self.root / "film.gif"
        self.store.export_gif(path, 12)
        with Image.open(path) as film:
            self.assertEqual(film.n_frames, 3)
            self.assertEqual(film.info["loop"], 0)
            total_ms = 0
            for index, expected in enumerate([(255, 0, 0), (0, 128, 0), (0, 0, 255)]):
                film.seek(index)
                self.assertEqual(film.size, (8, 8))
                self.assertEqual(film.convert("RGB").getpixel((4, 4)), expected)
                total_ms += film.info["duration"]
            self.assertEqual(total_ms, 250)

    def test_single_frame_and_repeated_identical_frames(self):
        frame = Image.new("RGB", (4, 4), "red")
        self.store.append(frame)
        path = self.root / "still.gif"
        self.store.export_gif(path, 10)
        with Image.open(path) as result:
            self.assertEqual(result.info["duration"], 100)
        self.store.append(frame)
        self.store.export_gif(path, 10)
        with Image.open(path) as result:
            elapsed = 0
            for index in range(result.n_frames):
                result.seek(index)
                elapsed += result.info["duration"]
            self.assertEqual(elapsed, 200)

    def test_failed_write_preserves_existing_gif_and_published_frames(self):
        frame = Image.new("RGB", (4, 4), "red")
        self.store.append(frame)
        path = self.root / "film.gif"
        self.store.export_gif(path, 10)
        original = path.read_bytes()
        with patch.object(Image.Image, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.export_gif(path, 10)
            with self.assertRaises(OSError):
                self.store.append(frame)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(SessionStore(self.store.base_dir).frames), 1)
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_empty_and_invalid_exports(self):
        path = self.root / "film.gif"
        with self.assertRaises(ValueError):
            self.store.export_gif(path, 12)
        self.store.append(Image.new("RGB", (4, 4)))
        for fps in (0, 101, True, 1.5):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                self.store.export_gif(path, fps)
        self.assertFalse(path.exists())
