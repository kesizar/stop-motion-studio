"""Automatic shutter for a fixed tabletop camera. Times are monotonic seconds."""

from typing import Optional

import numpy as np


def _sample(frame: np.ndarray) -> np.ndarray:
    """Produce an independent, denoised BGR sample with bounded dimensions."""
    if frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) == 0:
        raise ValueError("快门需要非空的 BGR 彩色画面")
    stride = max(1, (max(frame.shape[:2]) + 639) // 640)
    sample = frame[::stride, ::stride].astype(np.int16)
    # A 3x3 box mean suppresses sensor noise while retaining small prop edges.
    horizontal = np.pad(sample, ((0, 0), (1, 1), (0, 0)), mode="edge")
    rows = horizontal[:, :-2] + horizontal[:, 1:-1] + horizontal[:, 2:]
    vertical = np.pad(rows, ((1, 1), (0, 0), (0, 0)), mode="edge")
    return (vertical[:-2] + vertical[1:-1] + vertical[2:]) // 9


def _change(before: np.ndarray, after: np.ndarray) -> str:
    """Distinguish a localized cluster from noise or a changed composition."""
    if before.shape != after.shape:
        return "widespread"
    delta = after - before
    offset = np.median(delta[::8, ::8], axis=(0, 1)).astype(np.int16)
    mask = np.max(np.abs(delta - offset), axis=2) >= 18
    count = np.count_nonzero(mask)
    if count > mask.size * 0.35:
        return "widespread"

    # A tiny prop can change a few adjacent pixels in an otherwise empty frame.
    required = max(8, min(20, mask.size // 14000))
    if count < required:
        return "none"
    block = 12
    rows = np.add.reduceat(mask, np.arange(0, mask.shape[0], block), axis=0)
    tiles = np.add.reduceat(rows, np.arange(0, mask.shape[1], block), axis=1)
    padded = np.pad(tiles, ((0, 1), (0, 1)))
    groups = tiles + padded[1:, :-1] + padded[:-1, 1:] + padded[1:, 1:]
    return "localized" if groups.max() >= required else "none"


class ShutterGate:
    """Commit one clean, settled picture per hand-entry/exit cycle."""

    settle_seconds = 0.65
    max_gap_seconds = 0.75
    min_stable_samples = 3

    def __init__(self) -> None:
        self.reset()

    def reset(self, reference: Optional[np.ndarray] = None) -> None:
        self._reference = None if reference is None else _sample(reference)
        self._armed = reference is None
        self._anchor = None
        self._stable_since = 0.0
        self._stable_samples = 0
        self._last_time = None

    def update(self, frame: np.ndarray, hand_present: bool, now: float) -> tuple[bool, str]:
        """Return the capture decision and a user-facing Chinese status."""
        previous_time = self._last_time
        self._last_time = now
        if hand_present:
            self._armed = True
            self._anchor = None
            return False, "检测到手，请摆好道具后移开手"
        if not self._armed:
            return False, "等待下一次摆动道具"

        sample = _sample(frame)
        interrupted = previous_time is None or not 0 < now - previous_time <= self.max_gap_seconds
        if self._anchor is None or interrupted or _change(self._anchor, sample) != "none":
            self._anchor = sample
            self._stable_since = now
            self._stable_samples = 1
            return False, "等待画面稳定"
        self._stable_samples += 1
        if now - self._stable_since < self.settle_seconds or self._stable_samples < self.min_stable_samples:
            return False, "等待画面稳定"

        change = "localized" if self._reference is None else _change(self._reference, sample)
        if change == "widespread":
            return False, "取景变化较大，请恢复机位或重新开始拍摄"
        self._armed = False
        self._anchor = None
        if change == "none":
            return False, "道具位置未变化，已跳过"
        self._reference = sample
        return True, "已自动拍下一帧"

