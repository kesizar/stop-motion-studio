"""Check that the shipped hand model loads from the project's Unicode path."""
import unittest

import numpy as np

from sources import HandDetector


class DetectorTest(unittest.TestCase):
    def test_load_model_bytes_and_process_two_frames(self):
        empty = np.zeros((240, 320, 3), np.uint8)
        with HandDetector() as detector:
            self.assertFalse(detector.sees_hand(empty, 0.5))
            self.assertFalse(detector.sees_hand(empty, 0.5))
            self.assertGreater(detector.last_ms, 500)
