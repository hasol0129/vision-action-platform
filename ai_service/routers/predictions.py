"""POST /predict/video — Celery Worker가 보낸 영상 1건을 받아 사람별 예측 JSON 반환."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from services.action_inference import predict_tracks
from services.overlay import render_keyframe
from services.pose_pipeline import VideoReadError, extract_tracks

router = APIRouter(tags=['predictions'])

ALLOWED_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '200'))

MSG_NO_PERSON = '영상에서 사람을 찾지 못했습니다'
MSG_TOO_SHORT = '사람은 검출됐지만 동작을 판단할 만큼 유효한 Frame이 부족합니다'


def _error(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={'error': code, 'message': message})


@router.post('/api/v1/predict/')
@router.post('/predict/video')
def predict_video(request: Request, file: UploadFile = File(...), include_keyframe: bool = True):
    models = getattr(request.app.state, 'models', None)
    if models is None:
        _error(503, 'model_not_ready', '추론 모델이 아직 준비되지 않았습니다.')

    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        _error(400, 'invalid_extension', f'지원하지 않는 확장자입니다: {suffix or "(없음)"}')

    started = time.perf_counter()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
        if size_mb == 0:
            _error(400, 'invalid_video', '빈 파일입니다.')
        if size_mb > MAX_UPLOAD_MB:
            _error(413, 'file_too_large', f'파일이 너무 큽니다 ({size_mb:.1f}MB > {MAX_UPLOAD_MB}MB).')

        try:
            video = extract_tracks(tmp_path, models)
        except VideoReadError as exc:
            _error(400, 'invalid_video', str(exc))

        predictions = predict_tracks(video.tracks, models)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    if predictions:
        message = f'{len(predictions)}명의 동작을 분석했습니다'
    elif video.tracks:
        message = MSG_TOO_SHORT
    else:
        message = MSG_NO_PERSON

    return {
        'status': 'ok',
        'message': message,
        'person_detected': bool(video.tracks),
        'predictions': predictions,
        'frame_count': video.frame_count,
        'fps': round(video.fps, 2),
        'duration_sec': round(video.duration_sec, 2),
        'processing_time_sec': round(time.perf_counter() - started, 3),
        # 추가 필드(기존 계약과 호환): 대표 Frame에 Skeleton을 그린 JPEG (base64). 사람이 없으면 null
        'keyframe_jpeg_base64': render_keyframe(video.keyframe, predictions) if include_keyframe else None,
    }
