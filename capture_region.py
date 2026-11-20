"""Normalized regions and conservative frame-to-frame alignment measurement."""

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CaptureRegion:
    """A rectangle expressed as fractions of the full camera image."""

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self):
        if not (
            0 <= self.left < self.right <= 1
            and 0 <= self.top < self.bottom <= 1
            and self.right - self.left >= 0.05 - 1e-9
            and self.bottom - self.top >= 0.05 - 1e-9
        ):
            raise ValueError("拍摄区域至少占画面宽、高的 5%，并且必须在画面内。")

    def crop(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        left, right = math.floor(self.left * width), math.ceil(self.right * width)
        top, bottom = math.floor(self.top * height), math.ceil(self.bottom * height)
        return frame[top:bottom, left:right]

    def intersects(self, bounds: tuple[float, float, float, float]) -> bool:
        left, top, right, bottom = bounds
        return left <= self.right and right >= self.left and top <= self.bottom and bottom >= self.top


@dataclass(frozen=True)
class AlignmentMeasurement:
    """Estimated translation in full-resolution pixels, with supporting tile count."""

    dx: float
    dy: float
    support: int

    @property
    def distance(self) -> float:
        return math.hypot(self.dx, self.dy)


def measure_alignment(reference_bgr: np.ndarray, current_bgr: np.ndarray) -> AlignmentMeasurement | None:
    """Compare edge tiles. Return None when the background gives no consensus."""
    if (
        reference_bgr.shape != current_bgr.shape
        or reference_bgr.ndim != 3
        or reference_bgr.shape[2] != 3
    ):
        return None
    height, width = reference_bgr.shape[:2]
    if min(height, width) < 72:
        return None
    try:
        import cv2
    except ImportError:
        return None

    # Limit CPU cost while retaining enough texture to estimate subpixel motion.
    factor = min(1.0, 384 / max(height, width))
    size = round(width * factor), round(height * factor)
    tile_width, tile_height = size[0] // 3, size[1] // 3
    if min(tile_width, tile_height) < 24:
        return None

    def grayscale(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, size, interpolation=cv2.INTER_AREA) if factor < 1 else gray

    reference = grayscale(reference_bgr)
    current = grayscale(current_bgr)
    window = cv2.createHanningWindow((tile_width, tile_height), cv2.CV_32F)
    candidates = []
    locations = []
    for row in range(3):
        for col in range(3):
            # The center usually contains the moving subject.
            if row == col == 1:
                continue
            x, y = col * tile_width, row * tile_height
            a = reference[y:y + tile_height, x:x + tile_width].astype(np.float32)
            b = current[y:y + tile_height, x:x + tile_width].astype(np.float32)
            if min(a.std(), b.std()) < 3:
                continue
            a -= a.mean()
            b -= b.mean()
            (dx, dy), response = cv2.phaseCorrelate(a, b, window)
            if response >= 0.45 and abs(dx) < tile_width / 4 and abs(dy) < tile_height / 4:
                candidates.append((dx, dy))
                locations.append((row, col))

    if len(candidates) < 4:
        return None
    shifts = np.asarray(candidates)
    agreement = np.linalg.norm(shifts[:, None] - shifts[None, :], axis=2) <= 1.5
    counts = agreement.sum(axis=1)
    selected = agreement[counts.argmax()]
    support = int(selected.sum())
    if support < max(4, math.ceil(len(candidates) * 0.6)):
        return None
    support_locations = [locations[index] for index in np.flatnonzero(selected)]
    rows, cols = zip(*support_locations)
    if max(rows) - min(rows) < 2 or max(cols) - min(cols) < 2:
        # Motion isolated to one patch of the image is insufficient evidence.
        return None
    dx, dy = np.median(shifts[selected], axis=0)
    return AlignmentMeasurement(float(dx * width / size[0]), float(dy * height / size[1]), support)
