import unittest

import numpy as np

from shutter import ShutterGate


def scene(x=40):
    frame = np.full((120, 160, 3), 80, dtype=np.uint8)
    frame[50:68, x:x + 20] = (30, 170, 230)
    return frame


class ShutterTests(unittest.TestCase):
    def setUp(self):
        self.gate = ShutterGate()
        self.now = 0.0

    def observe(self, frame, hand=False, ticks=1):
        shots = 0
        for _ in range(ticks):
            self.now += 0.10
            captured, _ = self.gate.update(frame, hand, self.now)
            shots += int(captured)
        return shots

    def test_first_frame_once_then_only_move_after_hand(self):
        self.assertEqual(self.observe(scene(), ticks=20), 1)
        self.assertEqual(self.observe(scene(42), ticks=15), 0)
        self.assertEqual(self.observe(scene(42), hand=True, ticks=15), 0)
        self.assertEqual(self.observe(scene(42), ticks=20), 1)

    def test_stable_unchanged_scene_consumes_intervention(self):
        self.gate.reset(scene())
        self.observe(scene(), hand=True)
        self.assertEqual(self.observe(scene(), ticks=12), 0)
        self.assertEqual(self.observe(scene(50), ticks=12), 0)

    def test_slow_motion_and_brief_hand_tracking_dropout(self):
        self.gate.reset(scene())
        self.observe(scene(), hand=True)
        self.assertEqual(self.observe(scene(42), ticks=4), 0)
        self.observe(scene(44), hand=True)
        for x in range(45, 68):
            self.assertEqual(self.observe(scene(x)), 0)
        self.assertEqual(self.observe(scene(68), ticks=12), 1)

    def test_exposure_and_sensor_noise_allow_first_shot_but_no_duplicates(self):
        frame = scene()
        rng = np.random.default_rng(11)

        def noisy(offset):
            noise = rng.normal(0, 5, size=frame.shape)
            return np.clip(frame.astype(float) + offset + noise, 0, 255).astype(np.uint8)

        self.assertEqual(sum(self.observe(noisy(0)) for _ in range(18)), 1)
        self.observe(frame, hand=True)
        self.assertEqual(sum(self.observe(noisy(9)) for _ in range(18)), 0)

    def test_large_scene_change_is_suppressed_and_recoverable(self):
        frame = scene()
        self.gate.reset(frame)
        self.observe(frame, hand=True)
        changed = frame.copy()
        changed[:, :80] = (220, 10, 180)
        self.assertEqual(self.observe(changed, ticks=20), 0)
        self.assertEqual(self.observe(scene(42), ticks=12), 1)

    def test_disconnect_is_not_observed_stability(self):
        self.assertEqual(self.observe(scene(), ticks=2), 0)
        self.now += 3
        self.assertEqual(self.observe(scene(), ticks=2), 0)
        self.assertEqual(self.observe(scene(), ticks=9), 1)

    def test_undo_reference_is_copied_and_can_be_used_again(self):
        previous = scene(40)
        self.gate.reset(previous)
        previous[:] = 0
        self.assertEqual(self.observe(scene(44), ticks=12), 0)
        self.observe(scene(44), hand=True)
        self.assertEqual(self.observe(scene(44), ticks=12), 1)
        self.gate.reset(scene(40))
        self.observe(scene(44), hand=True)
        self.assertEqual(self.observe(scene(44), ticks=12), 1)


if __name__ == "__main__":
    unittest.main()

