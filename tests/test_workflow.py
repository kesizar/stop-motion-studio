"""Exercise the same controller and Tk widgets reached by the desktop launcher."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
