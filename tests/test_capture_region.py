"""Exercise zone filtering and camera alignment without a physical camera."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from capture_region import CaptureRegion, measure_alignment
from sources import CameraFeed, DemoFeed, HandDetector


class CaptureRegionTest(unittest.TestCase):
    def test_crop_uses_normalized_image_bounds(self):
        frame = np.arange(10 * 20 * 3).reshape(10, 20, 3)
        region = CaptureRegion(0.2, 0.2, 0.7, 0.7)
        np.testing.assert_array_equal(region.crop(frame), frame[2:7, 4:14])
        self.assertTrue(region.intersects((0.6, 0.5, 0.8, 0.9)))
        self.assertFalse(region.intersects((0.75, 0.2, 0.9, 0.6)))
        for bounds in ((0.3, 0.3, 0.31, 0.5), (-0.1, 0.5, 0.9, 1), (0, 0.8, 1, 0.2)):
            with self.assertRaises(ValueError):
                CaptureRegion(*bounds)

    def test_detector_checks_multiple_hands_against_region(self):
        detector = HandDetector.__new__(HandDetector)
        detector.last_ms = -1
        detector.mp = MagicMock()
        detector.detector = MagicMock()
        detector.detector.detect_for_video.return_value.hand_landmarks = [
            [SimpleNamespace(x=0.05, y=0.4), SimpleNamespace(x=0.15, y=0.6)],
            [SimpleNamespace(x=0.55, y=0.55), SimpleNamespace(x=0.6, y=0.6)],
        ]
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        self.assertTrue(detector.sees_hand(frame, 0))
        self.assertFalse(detector.sees_hand(frame, 0.1, CaptureRegion(0.2, 0.2, 0.4, 0.8)))
        self.assertTrue(detector.sees_hand(frame, 0.2, CaptureRegion(0.5, 0.5, 0.8, 0.8)))

    def test_simulated_hand_outside_region_keeps_real_image(self):
        feed = DemoFeed()
        now = feed.started + 1.8
        frame, hand = feed.read(now)
        filtered, outside = feed.read(now, CaptureRegion(0.6, 0.2, 1.0, 0.6))
        _, inside = feed.read(now, CaptureRegion(0.1, 0.1, 0.3, 0.4))
        self.assertTrue(hand)
        self.assertTrue(inside)
        self.assertFalse(outside)
        np.testing.assert_array_equal(frame, filtered)

    def test_changing_region_discards_detection_in_flight(self):
        entered = threading.Event()
        release = threading.Event()
        hand_detector = MagicMock()
        hand_detector.__enter__.return_value = hand_detector

        def detect(_rgb, _now, region):
            if region is None:
                entered.set()
                if not release.wait(timeout=3):
                    raise TimeoutError("test did not change the region")
                return True
            return False

        source = MagicMock()
        source.isOpened.return_value = True
        source.read.return_value = (True, np.zeros((80, 80, 3), dtype=np.uint8))
        hand_detector.sees_hand.side_effect = detect
        feed = CameraFeed(0)
        with patch("sources.HandDetector", return_value=hand_detector), patch("cv2.VideoCapture", return_value=source):
            feed.start()
            try:
                self.assertTrue(entered.wait(timeout=3))
                revision, sequence = feed.set_region(CaptureRegion(0.3, 0.3, 0.8, 0.8))
                release.set()
                result = feed.latest.get(timeout=3)
                _, in_region, _, sampled_sequence, sampled_revision = result
                self.assertFalse(in_region)
                self.assertEqual(sampled_sequence, sequence)
                self.assertEqual(sampled_revision, revision)
            finally:
                release.set()
                feed.close()
                feed.thread.join(timeout=3)
            self.assertFalse(feed.thread.is_alive())


class CameraAlignmentTest(unittest.TestCase):
    def setUp(self):
        random = np.random.default_rng(6183)
        gray = random.integers(0, 256, (360, 480), dtype=np.uint8)
        self.reference = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def test_global_shift_agrees_across_distributed_tiles(self):
        translated = cv2.warpAffine(
            self.reference, np.float32([[1, 0, 7], [0, 1, -5]]), (480, 360),
            borderMode=cv2.BORDER_REFLECT,
        )
        alignment = measure_alignment(self.reference, translated)
        self.assertIsNotNone(alignment)
        self.assertAlmostEqual(alignment.dx, 7, delta=1.2)
        self.assertAlmostEqual(alignment.dy, -5, delta=1.2)
        self.assertGreaterEqual(alignment.support, 4)

    def test_moving_prop_does_not_count_as_camera_shift(self):
        reference = self.reference.copy()
        reference[135:185, 170:235] = (30, 40, 240)
        current = self.reference.copy()
        current[150:200, 210:275] = (30, 40, 240)
        alignment = measure_alignment(reference, current)
        self.assertIsNotNone(alignment)
        self.assertLess(alignment.distance, 1)

    def test_untextured_or_changed_resolution_is_indeterminate(self):
        flat = np.full_like(self.reference, 70)
        self.assertIsNone(measure_alignment(flat, np.full_like(flat, 120)))
        self.assertIsNone(measure_alignment(self.reference, self.reference[10:]))
