"""Exercise the same controller and Tk widgets reached by the desktop launcher."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from app import Studio, create_window


class StudioWorkflowTest(unittest.TestCase):
    def test_demo_capture_undo_playback_export_and_return_to_real_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = create_window()
            root.withdraw()
            studio = Studio(root, Path(directory) / "projects")
            self.addCleanup(studio.close)
            saved_folder = studio.real_store.folder
            studio.start_demo()
            start = studio.demo.started
            for step in range(115):
                studio._step(start + step * 0.1)
            captured = len(studio.store.frames)
            self.assertGreaterEqual(captured, 4)
            self.assertEqual(studio.real_store.frames, [])
            studio.stop_source()
            studio.undo()
            self.assertEqual(len(studio.store.frames), captured - 1)
            studio.set_fps(6)
            studio.playback()
            studio._step(start + 15)
            self.assertTrue(studio.playing)
            self.assertEqual(studio.play_index, 1)
            studio.playback()
            self.assertFalse(studio.playing)
            output = Path(directory) / "boat.gif"
            with patch("app.filedialog.asksaveasfilename", return_value=str(output)):
                studio.export_gif()
            with Image.open(output) as gif:
                self.assertEqual(gif.n_frames, captured - 1)
                self.assertEqual(gif.info["loop"], 0)
            studio.new_project()
            self.assertEqual(studio.store.frames, [])
            self.assertNotEqual(studio.store.folder, saved_folder)
            self.assertTrue(saved_folder.is_dir())
            root.update_idletasks()


    def test_onion_preview_and_manual_capture_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = create_window()
            root.withdraw()
            studio = Studio(root, Path(directory) / "projects")
            self.addCleanup(studio.close)
            studio.start_demo()
            start = studio.demo.started
            first = np.zeros((80, 80, 3), dtype=np.uint8)
            second = first.copy()
            second[20:40, 20:40] = (30, 60, 210)
            third = first.copy()
            third[20:40, 24:44] = (30, 60, 210)

            for elapsed in (0.0, 0.2, 0.4, 0.7):
                studio._observe(first, False, start + elapsed)
            self.assertEqual(len(studio.store.frames), 1)
            self.assertIn("已自动拍下", studio.ui.status_label.cget("text"))

            with patch("app.time.monotonic", return_value=start + 0.8):
                studio.ui.pause_button.invoke()
            studio.set_onion_skin(True)
            studio._observe(second, True, start + 1.0)
            self.assertEqual(str(studio.ui.capture_button.cget("state")), "disabled")
            self.assertEqual(len(studio.store.frames), 1)
            with patch.object(studio.store, "_frame_entries", side_effect=AssertionError("preview rescanned files")):
                studio._observe(second, False, start + 1.1)
                self.assertEqual(studio.ui._image.getpixel((25, 25)), (147, 42, 21))
            self.assertEqual(str(studio.ui.capture_button.cget("state")), "normal")
            with patch("app.time.monotonic", return_value=start + 2.0):
                studio.ui.capture_button.invoke()
            self.assertEqual(len(studio.store.frames), 1)
            studio._observe(second, False, start + 2.1)
            with patch("app.time.monotonic", return_value=start + 2.1):
                studio.ui.capture_button.invoke()
            self.assertEqual(len(studio.store.frames), 2)
            self.assertEqual(studio.store.frames[-1].getpixel((25, 25)), (210, 60, 30))
            self.assertIn("已手动拍下", studio.ui.status_label.cget("text"))

            with patch("app.time.monotonic", return_value=start + 2.2):
                studio.ui.pause_button.invoke()
            self.assertEqual(str(studio.ui.capture_button.cget("state")), "disabled")
            for elapsed in (2.5, 2.7, 2.9, 3.2):
                studio._observe(second, False, start + elapsed)
            self.assertEqual(len(studio.store.frames), 2)

            studio._observe(third, True, start + 3.3)
            for elapsed in (3.4, 3.6, 3.8, 4.1):
                studio._observe(third, False, start + elapsed)
            self.assertEqual(len(studio.store.frames), 3)
            studio.stop_source()
            self.assertEqual(str(studio.ui.pause_button.cget("state")), "disabled")
            self.assertEqual(str(studio.ui.capture_button.cget("state")), "disabled")
            root.update_idletasks()


if __name__ == "__main__":
    unittest.main()
