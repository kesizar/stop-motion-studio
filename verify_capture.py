"""Run a deterministic shutter comparison on scripted tabletop observations."""

from dataclasses import dataclass

import numpy as np

from shutter import ShutterGate


SAMPLES_PER_SECOND = 10
Observation = tuple[np.ndarray, bool]


@dataclass(frozen=True)
class Scenario:
    name: str
    observations: list[Observation]
    valid_window: tuple[int, int] | None  # Inclusive sample numbers, or no shot expected.


def sample(x=40, *, hand=False, detected=None, shift=0, brightness=0) -> Observation:
    """Render one BGR image and the hand result fed to the shutter."""
    frame = np.full((120, 160, 3), 80, dtype=np.uint8)
    # Fixed marks make a shifted camera view distinguishable from the settled view.
    frame[12:16, 8:152] = 130
    frame[103:107, 8:152] = 130
    frame[50:68, x:x + 20] = (30, 170, 220)
    if hand:
        frame[:62, x + 8:x + 34] = (110, 153, 207)
    if shift:
        frame = np.roll(frame, shift, axis=1)
        frame = np.roll(frame, shift, axis=0)
    frame += brightness
    return frame, hand if detected is None else detected


def scenarios() -> list[Scenario]:
    hand = [sample(hand=True)] * 3
    settling = [sample(x=58, shift=2 if index % 2 == 0 else -2) for index in range(12)]
    dropout = [sample(x=58, hand=True, detected=False)] * 3
    # The valid window begins when the hand is truly out and the final pose is still.
    return [
        Scenario("正常移动", hand + [sample(x=58)] * 14, (3, 16)),
        Scenario("原样摆回", hand + [sample()] * 14, None),
        Scenario("收手后桌面晃动", hand + settling + [sample(x=58)] * 14, (15, 28)),
        Scenario("检测短暂漏手", hand + dropout + hand + [sample(x=58)] * 14, (9, 22)),
        Scenario("道具移动 2 像素", hand + [sample(x=42)] * 14, (3, 16)),
        Scenario("仅全局亮度上升", hand + [sample(brightness=25)] * 14, None),
    ]


def run_scenario(scenario: Scenario) -> tuple[list[int], list[int]]:
    gate = ShutterGate()
    gate.reset(sample()[0])
    gate_shots = []
    baseline_shots = []
    previous_hand = False
    for index, (frame, hand_detected) in enumerate(scenario.observations):
        capture, _ = gate.update(frame, hand_detected, index / SAMPLES_PER_SECOND)
        if capture:
            gate_shots.append(index)
        if previous_hand and not hand_detected:
            baseline_shots.append(index)
        previous_hand = hand_detected
    return gate_shots, baseline_shots


def score(shots: list[int], window: tuple[int, int] | None) -> tuple[int, int, int]:
    expected = int(window is not None)
    matched = int(window is not None and any(window[0] <= shot <= window[1] for shot in shots))
    return matched, len(shots) - matched, expected - matched


def format_times(samples: list[int]) -> str:
    return "、".join(f"{index / SAMPLES_PER_SECOND:.2f}" for index in samples) or "无"


def main() -> int:
    print("合成桌面序列，10 Hz，每个场景都从一张已拍参考帧开始。")
    print("对照规则：检测到手消失就立即拍摄。两套逻辑使用相同的画面和手部信号。")
    print("有效时间窗由场景预先标注。窗外或多余收帧算误拍，窗口内没有收帧算漏拍。")
    print()
    all_gate_scores = []
    all_baseline_scores = []
    for scenario in scenarios():
        gate, baseline = run_scenario(scenario)
        window = scenario.valid_window
        expected = "不收帧" if window is None else f"{window[0] / SAMPLES_PER_SECOND:.2f}–{window[1] / SAMPLES_PER_SECOND:.2f}"
        print(f"{scenario.name} | 预期 {expected} | 工作台 {format_times(gate)} | 对照 {format_times(baseline)}")
        all_gate_scores.append(score(gate, window))
        all_baseline_scores.append(score(baseline, window))

    print()
    print("以上时刻单位为秒。")
    gate_hits, gate_false, gate_missed = map(sum, zip(*all_gate_scores))
    baseline_hits, baseline_false, baseline_missed = map(sum, zip(*all_baseline_scores))
    print(f"工作台：命中 {gate_hits}，误拍 {gate_false}，漏拍 {gate_missed}")
    print(f"对照：命中 {baseline_hits}，误拍 {baseline_false}，漏拍 {baseline_missed}")
    print("本评估使用合成画面与预设手部信号。实拍中的手部检测表现需另行测量。")
    return int(gate_false > 0 or gate_missed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
