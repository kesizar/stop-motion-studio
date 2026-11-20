import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from sessions import SessionStore, playback_order


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


    def test_mp4_decodes_with_odd_and_mixed_dimensions(self):
        import cv2

        red = Image.new("RGB", (65, 49), (255, 0, 0))
        green = Image.new("RGB", (65, 21), (0, 255, 0))
        blue = Image.new("RGB", (65, 49), (0, 0, 255))
        for frame in (red, green, green, blue):
            self.store.append(frame)

        folder = self.root / "导出作品"
        folder.mkdir()
        path = folder / "动画.mp4"
        with patch("tempfile.tempdir", str(folder)):
            self.store.export_mp4(path, 12)
        # Stage the decode under a simple filename so the test checks the
        # application's Unicode output path independently of OpenCV's decoder.
        copy = self.root / "decode.mp4"
        copy.write_bytes(path.read_bytes())
        video = cv2.VideoCapture(str(copy))
        decoded = []
        try:
            self.assertAlmostEqual(video.get(cv2.CAP_PROP_FPS), 12)
            while True:
                ok, frame = video.read()
                if not ok:
                    break
                decoded.append(frame)
        finally:
            video.release()
        self.assertEqual(len(decoded), 4)
        for frame, color_channel in zip(decoded, (2, 1, 1, 0)):
            self.assertEqual(frame.shape, (50, 66, 3))
            center = frame[24, 32]
            self.assertGreater(center[color_channel], 220)
            self.assertLess(sum(center) - center[color_channel], 25)
        # The short frame has black letterbox bars, not a stretched image.
        self.assertLess(int(decoded[1][2, 32].max()), 15)
        self.assertLess(int(decoded[1][46, 32].max()), 15)
        # The odd input's final row and column survive within the padded size.
        self.assertGreater(decoded[0][24, 64, 2], 100)
        self.assertGreater(decoded[0][48, 32, 2], 100)

    def test_mp4_failures_leave_the_previous_file_intact(self):
        path = self.root / "existing.mp4"
        path.write_bytes(b"previous video")
        with self.assertRaises(ValueError):
            self.store.export_mp4(path, 12)
        self.store.append(Image.new("RGB", (32, 32), "red"))
        with self.assertRaises(ValueError):
            self.store.export_mp4(path, 0)
        with patch("cv2.VideoWriter") as factory:
            writer = factory.return_value
            writer.isOpened.return_value = False
            with self.assertRaisesRegex(OSError, "编码器"):
                self.store.export_mp4(path, 12)
            writer.release.assert_called_once()
            writer.reset_mock()
            writer.isOpened.return_value = True
            with self.assertRaisesRegex(OSError, "没有生成"):
                self.store.export_mp4(path, 12)
            writer.release.assert_called_once()
        self.assertEqual(path.read_bytes(), b"previous video")
        self.assertEqual(len(self.store.frames), 1)

    def test_timeline_preserves_originals_and_reopens_edits(self):
        for color in ("red", "green", "blue"):
            self.store.append(Image.new("RGB", (24, 24), color))
        originals = {path: path.read_bytes() for path in self.store.folder.glob("*.png")}
        self.assertEqual(playback_order(self.store.timeline), (0, 1, 2))
        self.assertFalse(self.store.edit_frame(0, hold=1, hidden=False))
        self.assertFalse((self.store.folder / "timeline.json").exists())

        self.assertTrue(self.store.edit_frame(1, hidden=True))
        self.assertTrue(self.store.edit_frame(2, hold=3))
        self.assertEqual(playback_order(self.store.timeline), (0, 2, 2, 2))
        self.assertTrue(self.store.can_undo_edit)
        self.assertFalse(self.store.can_redo_edit)
        self.assertTrue(self.store.undo_edit())
        self.assertEqual(playback_order(self.store.timeline), (0, 2))
        self.assertTrue(self.store.redo_edit())
        self.assertEqual(playback_order(self.store.timeline), (0, 2, 2, 2))
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)

        reopened = SessionStore(self.store.base_dir)
        self.assertEqual(playback_order(reopened.timeline), (0, 2, 2, 2))
        self.assertEqual([(item.hold, item.hidden) for item in reopened.timeline],
                         [(1, False), (1, True), (3, False)])
        self.assertEqual(len(reopened.frames), 3)
        self.assertFalse(reopened.can_undo_edit)

    def test_failed_edit_and_undo_leave_previous_manifest_and_history_intact(self):
        self.store.append(Image.new("RGB", (24, 24)))
        self.store.edit_frame(0, hold=2)
        timeline = self.store.folder / "timeline.json"
        saved = timeline.read_bytes()
        with patch("sessions.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.edit_frame(0, hidden=True)
            with self.assertRaises(OSError):
                self.store.undo_edit()

        self.assertEqual(timeline.read_bytes(), saved)
        self.assertEqual(playback_order(self.store.timeline), (0, 0))
        self.assertTrue(self.store.can_undo_edit)
        self.assertFalse(self.store.can_redo_edit)
        self.assertTrue(self.store.undo_edit())
        self.assertTrue(self.store.can_redo_edit)
        self.assertTrue(self.store.edit_frame(0, hold=5))
        self.assertFalse(self.store.can_redo_edit)
        self.assertFalse(self.store.edit_frame(1, hold=2))
        for hold in (False, 0, 121, 1.2):
            with self.subTest(hold=hold), self.assertRaises(ValueError):
                self.store.edit_frame(0, hold=hold)

    def test_import_natural_order_and_exif_transpose(self):
        self.store.append(Image.new("RGB", (4, 4), "white"))
        two = self.root / "照片2.jpg"
        ten = self.root / "照片10.png"
        orientation = Image.Exif()
        orientation[274] = 6
        Image.new("RGB", (18, 8), (255, 0, 0)).save(two, exif=orientation)
        Image.new("RGBA", (8, 18), (0, 0, 255, 255)).save(ten)
        original_bytes = [path.read_bytes() for path in (two, ten)]
        self.assertEqual(self.store.import_images([]), 0)
        self.assertEqual(self.store.import_images([ten, two]), 2)
        self.store.append(Image.new("RGB", (4, 4), "green"))
        self.store.edit_frame(2, hidden=True, hold=4)

        reopened = SessionStore(self.store.base_dir)
        self.assertEqual([frame.size for frame in reopened.frames], [(4, 4), (8, 18), (8, 18), (4, 4)])
        self.assertEqual([frame.mode for frame in reopened.frames], ["RGB"] * 4)
        self.assertGreater(reopened.frames[1].getpixel((0, 0))[0], 250)
        self.assertEqual(reopened.frames[2].getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(playback_order(reopened.timeline), (0, 1, 3))
        self.assertEqual([path.read_bytes() for path in (two, ten)], original_bytes)
        self.assertEqual(len(list(reopened.folder.glob("batch-*"))), 1)
        self.assertEqual(list(reopened.folder.glob(".importing-*")), [])

    def test_invalid_import_does_not_publish_partial_batch(self):
        self.store.append(Image.new("RGB", (4, 4), "green"))
        good = self.root / "01.png"
        bad = self.root / "02.png"
        Image.new("RGB", (4, 4), "red").save(good)
        bad.write_bytes(b"not a photo")
        files = set(self.store.folder.iterdir())
        with self.assertRaisesRegex(ValueError, "02.png"):
            self.store.import_images([bad, good])
        self.assertEqual(set(self.store.folder.iterdir()), files)
        reopened = SessionStore(self.store.base_dir)
        self.assertEqual(len(reopened.frames), 1)
        self.assertEqual(reopened.frames[0].getpixel((0, 0)), (0, 128, 0))

    def test_exports_share_edited_frame_sequence_and_duration(self):
        import cv2

        for color in ("red", "lime", "blue"):
            self.store.append(Image.new("RGB", (24, 24), color))
        self.store.edit_frame(1, hidden=True)
        self.store.edit_frame(2, hold=3)
        gif = self.root / "edited.gif"
        mp4 = self.root / "edited.mp4"
        self.store.export_gif(gif, 10)
        self.store.export_mp4(mp4, 10)
        with Image.open(gif) as film:
            self.assertEqual(film.n_frames, 2)
            for index, expected in enumerate([((255, 0, 0), 100), ((0, 0, 255), 300)]):
                film.seek(index)
                self.assertEqual((film.convert("RGB").getpixel((8, 8)), film.info["duration"]), expected)
        reader = cv2.VideoCapture(str(mp4))
        try:
            self.assertAlmostEqual(reader.get(cv2.CAP_PROP_FPS), 10)
            channels = []
            while True:
                ok, pixels = reader.read()
                if not ok:
                    break
                channels.append(int(pixels[8, 8].argmax()))
            self.assertEqual(channels, [2, 0, 0, 0])
        finally:
            reader.release()

        for index in range(3):
            self.store.edit_frame(index, hidden=True)
        for export, path in [(self.store.export_gif, gif), (self.store.export_mp4, mp4)]:
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "可见帧"):
                export(path, 10)
            self.assertEqual(path.read_bytes(), before)
