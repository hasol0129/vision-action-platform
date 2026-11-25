"""Track ID별 Feature → 30-Step Sequence(1,140) → Random Forest 예측 정리.

- 기본(window_seconds=0): Track 전체를 30 Step으로 리샘플해 1번 예측 → 6일차 학습(Clip 전체 리샘플)과 같은 입력
- window_seconds>0 이고 Track이 더 길면: 그 길이의 Window를 window_stride_seconds 간격으로 밀며 예측하고 확률을 평균
"""
from __future__ import annotations

import numpy as np

from services.model_loader import LoadedModels
from services.pose_pipeline import TrackData
from src.sequence_utils import flatten_sequence, resample_sequence

UNCERTAIN_LABEL = '판단 불확실'


def _window_ranges(times: np.ndarray, window: float, stride: float) -> list[tuple[float, float]]:
    start, end = float(times[0]), float(times[-1])
    if window <= 0 or end - start <= window:
        return [(start, end)]
    ranges = []
    s = start
    while s + window <= end + 1e-6:
        ranges.append((s, s + window))
        s += stride
    if ranges[-1][1] < end - 1e-6:  # 마지막 구간이 남으면 끝에 맞춘 Window 추가
        ranges.append((end - window, end))
    return ranges


def predict_track(track_id: int, data: TrackData, models: LoadedModels) -> dict | None:
    cfg = models.config
    min_valid = int(cfg.get('min_valid_features', 10))
    if len(data.features) < min_valid:
        return None

    times = np.asarray(data.times, dtype=np.float32)
    matrix = np.stack(data.features).astype(np.float32)

    vectors = []
    for w_start, w_end in _window_ranges(
        times, float(cfg.get('window_seconds', 0)), float(cfg.get('window_stride_seconds', 1.0))
    ):
        mask = (times >= w_start - 1e-6) & (times <= w_end + 1e-6)
        if mask.sum() < min_valid:
            continue
        sequence = resample_sequence(matrix[mask], times[mask], target_steps=models.sequence_steps)
        vectors.append(flatten_sequence(sequence))

    if not vectors:
        return None

    X = np.stack(vectors)
    if X.shape[1] != models.feature_count:
        raise RuntimeError(f'입력 Feature 수 {X.shape[1]} != 모델 {models.feature_count}')

    probabilities = models.classifier.predict_proba(X).mean(axis=0)
    best = int(np.argmax(probabilities))
    label = models.classes[best]
    confidence = float(probabilities[best])
    uncertain = confidence < models.uncertain_threshold  # 모델 출력은 그대로, 표시만 바뀜

    return {
        'track_id': int(track_id),
        'action_label': label,
        'confidence': round(confidence, 4),
        'is_uncertain': uncertain,
        'display_label': UNCERTAIN_LABEL if uncertain else label,
        'window_count': len(vectors),
        'valid_frame_count': len(data.features),
        'seen_frame_count': data.seen_frames,
        'probabilities': {c: round(float(p), 4) for c, p in zip(models.classes, probabilities)},
    }


def predict_tracks(tracks: dict[int, TrackData], models: LoadedModels) -> list[dict]:
    results = []
    for track_id in sorted(tracks):
        item = predict_track(track_id, tracks[track_id], models)
        if item is not None:
            results.append(item)
    return results
