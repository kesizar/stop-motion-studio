"""Live camera observations and a repeatable simulated tabletop scene."""
from pathlib import Path
import queue
import threading
import time

import numpy as np
from PIL import Image, ImageDraw

from capture_region import CaptureRegion


class HandDetector:
    """Use model bytes so native Windows code never has to resolve the Unicode project path."""
    def __init__(self):
        import mediapipe as mp
        self.mp = mp
        model = Path(__file__).with_name("hand_landmarker.task").read_bytes()
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=model),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=2,
        )
        self.detector = mp.tasks.vision.HandLandmarker.create_from_options(options)
        self.last_ms = -1

    def sees_hand(self, rgb, now, region: CaptureRegion | None = None) -> bool:
        stamp = max(self.last_ms + 1, int(now * 1000))
        self.last_ms = stamp
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self.detector.detect_for_video(image, stamp)
        if region is None:
            return bool(result.hand_landmarks)
        for hand in result.hand_landmarks:
            if not hand:
                continue
            xs = [landmark.x for landmark in hand]
            ys = [landmark.y for landmark in hand]
            if region.intersects((min(xs), min(ys), max(xs), max(ys))):
                return True
        return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.detector.close()


class CameraFeed:
    def __init__(self, index):
        self.index = index
        self.latest = queue.Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.hand_sequence = 0
        self._region = None
        self._region_revision = 0
        self._region_lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def set_region(self, region: CaptureRegion | None) -> tuple[int, int]:
        """Return the new region revision and its starting hand sequence."""
        with self._region_lock:
            self._region = region
            self._region_revision += 1
            return self._region_revision, self.hand_sequence

    def _publish(self, item):
        try:
            self.latest.put_nowait(item)
        except queue.Full:
            try:
                self.latest.get_nowait()
            except queue.Empty:
                pass
            self.latest.put_nowait(item)

    def _run(self):
        capture = None
        try:
            try:
                import cv2
            except ImportError as exc:
                raise RuntimeError('实拍需要 OpenCV 和 MediaPipe。请用「启动工作台.cmd」安装拍摄依赖，或先试用演示。') from exc
            capture = cv2.VideoCapture(self.index)
            if not capture.isOpened():
                raise RuntimeError("摄像头无法打开。请检查设备编号、相机权限，并关闭占用摄像头的软件。")
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            with HandDetector() as hands:
                while not self.stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok:
                        raise RuntimeError("摄像头画面中断。重新连接设备后再开始拍摄。")
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    now = time.monotonic()
                    with self._region_lock:
                        region, revision = self._region, self._region_revision
                    hand_present = hands.sees_hand(rgb, now, region)
                    with self._region_lock:
                        if revision != self._region_revision:
                            continue
                        # Carry sightings across dropped preview frames in this region.
                        if hand_present:
                            self.hand_sequence += 1
                        self._publish((frame, hand_present, now, self.hand_sequence, revision))
        except Exception as exc:
            self._publish(str(exc))
        finally:
            if capture is not None:
                capture.release()

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()


class DemoFeed:
    """Generated tabletop and scripted hand signal, with no camera or model inference."""
    def __init__(self):
        self.started = time.monotonic()

    def read(self, now, region: CaptureRegion | None = None):
        elapsed = max(0.0, now - self.started)
        cycle, phase = divmod(max(0.0, elapsed - 1.6), 2.5)
        cycle = int(cycle)
        hand = elapsed >= 1.6 and phase < 0.8
        step = cycle + (elapsed >= 1.6 and phase >= 0.42)
        # A paper boat moves back and forth across a blue tabletop.
        x = 90 + 37 * (8 - abs(step % 16 - 8))
        scene = Image.new("RGB", (640, 360), (127, 177, 201))
        draw = ImageDraw.Draw(scene)
        for row in (200, 232, 270):
            for col in range(15, 640, 62):
                draw.arc((col-17, row-4, col+17, row+4), 0, 180, fill=(98, 153, 173))
        draw.polygon([(x-42, 167), (x+46, 167), (x+25, 188), (x-20, 188)], fill=(183, 84, 58))
        draw.polygon([(x-4, 112), (x-4, 164), (x-37, 164)], fill=(248, 241, 232))
        draw.line([(x, 113), (x, 167)], fill=(79, 78, 63), width=3)
        if hand:
            draw.line([(x+53, 0), (x+10, 144)], fill=(218, 184, 137), width=24)
            if region is not None:
                hand = region.intersects(((x - 2) / 640, 0, (x + 65) / 640, 156 / 360))
        return np.asarray(scene)[:, :, ::-1], hand
