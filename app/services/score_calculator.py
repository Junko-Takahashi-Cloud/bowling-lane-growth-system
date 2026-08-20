from typing import List, Dict, Any, Tuple


def calculate_bowling_score(frames_input: List[Dict[str, Any]]) -> Tuple[int, List[int]]:
    """
    10フレームの投球データから、各フレームの累積スコアと最終合計スコアを計算する。
    frames_input: [{'frame_number': 1, 'shots': [10]}, ...] （shotsは各投のpins_knockedのリスト）
    """
    all_shots: List[int] = []
    frame_shot_map: Dict[int, List[int]] = {}

    sorted_frames = sorted(frames_input, key=lambda x: x["frame_number"])

    for f_idx, f in enumerate(sorted_frames):
        shots = f["shots"]
        frame_shot_map[f_idx] = []
        for s in shots:
            frame_shot_map[f_idx].append(len(all_shots))
            all_shots.append(s)

    frame_scores: List[int] = []
    running_total = 0

    for f_idx in range(len(sorted_frames)):
        shot_indices = frame_shot_map[f_idx]
        if not shot_indices:
            frame_scores.append(running_total)
            continue
        first_shot_idx = shot_indices[0]

        if f_idx < 9:
            first_pins = all_shots[first_shot_idx]
            if first_pins == 10:  # ストライク
                bonus1 = all_shots[first_shot_idx + 1] if first_shot_idx + 1 < len(all_shots) else 0
                bonus2 = all_shots[first_shot_idx + 2] if first_shot_idx + 2 < len(all_shots) else 0
                f_score = 10 + bonus1 + bonus2
            else:
                second_pins = all_shots[first_shot_idx + 1] if first_shot_idx + 1 < len(all_shots) else 0
                if first_pins + second_pins == 10:  # スペア
                    bonus = all_shots[first_shot_idx + 2] if first_shot_idx + 2 < len(all_shots) else 0
                    f_score = 10 + bonus
                else:  # オープンフレーム
                    f_score = first_pins + second_pins
        else:  # 10フレーム目
            f_score = sum(all_shots[first_shot_idx:])

        running_total += f_score
        frame_scores.append(running_total)

    return running_total, frame_scores
