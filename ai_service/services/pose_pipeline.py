"""영상 → YOLO Pose Tracking → Track ID별 (시간, 38-D Feature) 목록.

8일차 49_ip_webcam_multi_person_action.py 의 model.track(persist=True) 흐름을
저장 영상 한 건 단위로 옮겼다. Feature 계산은 src/multi_person_utils.feature_from_keypoints 재사용.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import cv2
import numpy as np

from services.model_loader import LoadedModels
from src.multi_person_utils import feature_from_keypoints


class VideoReadError(Exception):
    """영상 파일을 열 수 없거나 Frame이 하나도 읽히지 않을 때."""


@dataclass
class TrackData:
    times: list[float] = field(default_factory=list)
    features: list[np.ndarray] = field(default_factory=list)
    seen_frames: int = 0  # 이 Track이 화면에 잡힌 Frame 수(Feature 계산 실패 포함)


@dataclass
class KeyFrame:
    """Skeleton Overlay용 대표 Frame: 사람이 가장 많이 잡힌 Frame 중 영상 가운데에 가장 가까운 것."""
    frame: np.ndarray
    people: list[tuple[int, np.ndarray, np.ndarray, np.ndarray]]  # (track_id, xy(17,2), conf(17,), box xyxy)


@dataclass
class VideoTracks:
    frame_count: int
    fps: float
    tracks: dict[int, TrackData]
    keyframe: KeyFrame | None = None

    @property
    def duration_sec(self) -> float:
        return self.frame_count / self.fps if self.fps > 0 else 0.0


# YOLO 모델과 Tracker 상태는 요청 간에 공유되므로 한 번에 영상 하나만 처리한다
_track_lock = threading.Lock()


def _reset_tracker(models: LoadedModels) -> None:
    """이전 영상의 Track ID가 이어지지 않도록 Tracker를 초기화한다."""
    predictor = getattr(models.pose_model, 'predictor', None)
    for tracker in getattr(predictor, 'trackers', None) or []:
        tracker.reset()


def extract_tracks(video_path: str, models: LoadedModels) -> VideoTracks:
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        raise VideoReadError('영상 파일을 열 수 없습니다.')

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0 or fps > 240:
        fps = 30.0  # FPS 정보가 없는 파일은 30fps로 가정

    cfg = models.config
    tracks: dict[int, TrackData] = {}
    frame_index = 0
    middle = (capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / 2
    best_score, keyframe = None, None

    with _track_lock:
        _reset_tracker(models)
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                timestamp = frame_index / fps
                frame_index += 1

                result = models.pose_model.track(
                    source=frame,
                    persist=True,
                    tracker=cfg.get('tracker', 'bytetrack.yaml'),
                    imgsz=int(cfg['image_size']),
                    conf=float(cfg['person_confidence']),
                    device=models.device,
                    verbose=False,
                )[0]

                boxes, keypoints = result.boxes, result.keypoints
                if boxes is None or boxes.id is None or keypoints is None or keypoints.xy is None:
                    continue

                track_ids = boxes.id.detach().cpu().numpy().astype(int)
                kp_xy = keypoints.xy.detach().cpu().numpy()
                kp_conf = (keypoints.conf.detach().cpu().numpy() if keypoints.conf is not None
                           else np.ones(kp_xy.shape[:2], dtype=np.float32))
                xyxy = boxes.xyxy.detach().cpu().numpy()

                for track_id, xy in zip(track_ids, kp_xy):
                    data = tracks.setdefault(int(track_id), TrackData())
                    data.seen_frames += 1
                    feature = feature_from_keypoints(xy)
                    if feature is not None:
                        data.times.append(timestamp)
                        data.features.append(feature)

                score = (len(track_ids), -abs((frame_index - 1) - middle))
                if best_score is None or score > best_score:
                    best_score = score
                    keyframe = KeyFrame(frame=frame.copy(), people=[
                        (int(t), xy, c, b) for t, xy, c, b in zip(track_ids, kp_xy, kp_conf, xyxy)
                    ])
        finally:
            capture.release()

    if frame_index == 0:
        raise VideoReadError('영상에서 Frame을 읽지 못했습니다. 손상되었거나 지원하지 않는 형식입니다.')

    return VideoTracks(frame_count=frame_index, fps=fps, tracks=tracks, keyframe=keyframe)
