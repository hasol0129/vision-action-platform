"""FastAPI AI 추론 서버: 시작 시 모델을 한 번 로드하고 /health, /predict/video 제공.

실행: ai_service/ 폴더에서  uvicorn main:app --host 0.0.0.0 --port 8001
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from routers import predictions
from services.model_loader import MODEL_DIR, load_models

logger = logging.getLogger('uvicorn.error')


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.models = None
    app.state.model_error = None
    try:
        app.state.models = load_models()
        m = app.state.models
        logger.info('모델 로드 완료: classes=%s features=%d steps=%d device=%s',
                    m.classes, m.feature_count, m.sequence_steps, m.device)
    except Exception as exc:  # 모델이 없어도 /health로 원인을 확인할 수 있게 서버는 띄운다
        app.state.model_error = f'{type(exc).__name__}: {exc}'
        logger.exception('모델 로드 실패')
    yield


app = FastAPI(title='Vision Action AI Service', version='1.0.0', lifespan=lifespan)
app.include_router(predictions.router)


@app.get('/health')
def health(request: Request):
    m = request.app.state.models
    if m is None:
        return {'status': 'error', 'model_ready': False, 'error': request.app.state.model_error}
    return {
        'status': 'ok',
        'model_ready': True,
        'model_dir': str(MODEL_DIR),
        'classes': m.classes,
        'class_count': len(m.classes),
        'feature_count': m.feature_count,
        'sequence_steps': m.sequence_steps,
        'pose_model': m.config['pose_model'],
        'model_version': m.model_version,
        'uncertain_threshold': m.uncertain_threshold,
        'device': str(m.device),
    }
