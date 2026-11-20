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


    def test_open_existing_project_and_continue_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = create_window()
            root.withdraw()
            studio = Studio(root, Path(directory) / "projects")
            self.addCleanup(studio.close)
            root.update_idletasks()

            first_folder = studio.real_store.folder
            studio.real_store.append(Image.new("RGB", (80, 80)))
            studio.new_project()
            second_folder = studio.real_store.folder
            studio.real_store.append(Image.new("RGB", (80, 80), "blue"))

            studio.start_demo()
            start = studio.demo.started

            def choose(names, current):
                self.assertEqual(names, [second_folder.name, first_folder.name])
                self.assertEqual(current, second_folder.name)
                for elapsed in (0, 0.3, 0.6, 0.9):
                    studio._step(start + elapsed)
                self.assertEqual(studio.store.frames, [])
                return first_folder.name

            with patch.object(studio.ui, "choose_project", side_effect=choose):
                studio.ui.open_project_button.invoke()
            self.assertIs(studio.store, studio.real_store)
            self.assertEqual(studio.real_store.folder, first_folder)
            self.assertIsNone(studio.demo)
            self.assertFalse(studio.real_store.frames[-1].getbbox())
            self.assertIn("0001", studio.ui.project_label.cget("text"))

            # Feed a real controller its next hand cycle without using a physical camera.
            with patch("app.CameraFeed"):
                studio.start_camera(0)
                frame = np.zeros((80, 80, 3), dtype=np.uint8)
                frame[10:30, 20:40] = (40, 170, 240)
                studio._observe(frame, True, start + 2.0)
                for elapsed in (2.1, 2.3, 2.5, 2.8):
                    studio._observe(frame, False, start + elapsed)
                self.assertEqual(len(studio.store.frames), 2)

            output = Path(directory) / "reopened.gif"
            with patch("app.filedialog.asksaveasfilename", return_value=str(output)):
                studio.export_gif()
            with Image.open(output) as gif:
                self.assertEqual(gif.n_frames, 2)
            with patch.object(studio.ui, "choose_project", return_value=second_folder.name):
                studio.open_project_dialog()
            self.assertEqual(studio.real_store.folder, second_folder)
            self.assertEqual(studio.store.frames[0].getpixel((0, 0)), (0, 0, 255))
            self.assertEqual(len(studio.store.frames), 1)

    def test_demo_stops_after_eight_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = create_window()
            root.withdraw()
            studio = Studio(root, Path(directory) / "projects")
            self.addCleanup(studio.close)
            root.update_idletasks()
            studio.start_demo()
            start = studio.demo.started
            for step in range(250):
                studio._step(start + step * 0.1)
            self.assertIsNone(studio.demo)
            self.assertEqual(len(studio.store.frames), 8)
            self.assertEqual(studio.real_store.frames, [])
            self.assertIn("演示已拍好", studio.ui.status_label.cget("text"))


    def test_inspecting_saved_frames_pauses_capture_until_live_preview_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = create_window()
            root.withdraw()
            studio = Studio(root, Path(directory) / "projects")
            self.addCleanup(studio.close)
            root.update_idletasks()
            studio.start_demo()
            start = studio.demo.started
            for step in range(40):
                studio._step(start + step * 0.1)
            originals = [frame.tobytes() for frame in studio.store.frames]
            self.assertEqual(len(originals), 2)

            with patch.object(studio.ui, "show_frame", wraps=studio.ui.show_frame) as show_frame:
                studio.seek_frame(0)
                self.assertEqual(studio.inspection_index, 0)
                self.assertEqual(show_frame.call_args.args[0].tobytes(), originals[0])
                studio.ui.next_frame_button.invoke()
                self.assertEqual(studio.inspection_index, 1)
                self.assertEqual(show_frame.call_args.args[0].tobytes(), originals[1])
                studio.step_frame(1)
                self.assertEqual(studio.inspection_index, 1)
                studio.ui.previous_frame_button.invoke()
                studio.step_frame(-1)
                self.assertEqual(studio.inspection_index, 0)

                show_frame.reset_mock()
                for step in range(40, 100):
                    studio._step(start + step * 0.1)
                show_frame.assert_not_called()
                self.assertEqual([frame.tobytes() for frame in studio.store.frames], originals)

            studio.ui.resume_button.invoke()
            self.assertIsNone(studio.inspection_index)
            for step in range(100, 147):
                studio._step(start + step * 0.1)
            after_resume = [frame.tobytes() for frame in studio.store.frames]
            self.assertGreater(len(after_resume), len(originals))
            self.assertEqual(after_resume[:len(originals)], originals)

    def test_playback_starts_from_selected_frame_and_can_return_to_live(self):
        with tempfile.TemporaryDirectory() as directory:
            root = create_window()
            root.withdraw()
            studio = Studio(root, Path(directory) / "projects")
            self.addCleanup(studio.close)
            root.update_idletasks()
            studio.start_demo()
            start = studio.demo.started
            for step in range(63):
                studio._step(start + step * 0.1)
            frames = studio.store.frames
            self.assertEqual(len(frames), 3)
            studio.seek_frame(1)

            with patch.object(studio.ui, "show_frame", wraps=studio.ui.show_frame) as show_frame:
                studio.ui.play_button.invoke()
                studio._step(start + 6.5)
                self.assertTrue(studio.playing)
                self.assertEqual(show_frame.call_args.args[0].tobytes(), frames[1].tobytes())

            studio.ui.play_button.invoke()
            self.assertFalse(studio.playing)
            self.assertIsNone(studio.inspection_index)
            self.assertIsNotNone(studio.demo)
            self.assertEqual([frame.tobytes() for frame in studio.store.frames],
                             [frame.tobytes() for frame in frames])

            studio.seek_frame(1)
            studio.ui.play_button.invoke()
            studio.ui.next_frame_button.invoke()
            self.assertFalse(studio.playing)
            self.assertEqual(studio.inspection_index, 2)


    def test_mp4_export_uses_selected_path_and_frame_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = create_window()
            root.withdraw()
            studio = Studio(root, Path(directory) / "projects")
            self.addCleanup(studio.close)
            root.update_idletasks()
            studio.store.append(Image.new("RGB", (80, 80), "green"))
            studio._refresh()
            studio.set_fps(6)
            output = Path(directory) / "动画.mp4"

            with (patch("app.filedialog.asksaveasfilename", return_value=str(output)) as dialog,
                  patch.object(studio.store, "export_mp4") as export):
                studio.ui.export_mp4_button.invoke()
            self.assertEqual(dialog.call_args.kwargs["defaultextension"], ".mp4")
            export.assert_called_once_with(output, 6)


if __name__ == "__main__":
    unittest.main()
