"""6일차 Random Forest·Feature 목록·학습 정보와 YOLO Pose 가중치를 한 번만 로드한다."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import joblib
import torch
from ultralytics import YOLO

from src.sequence_utils import sequence_feature_names

BASE_DIR = Path(__file__).resolve().parents[1]

# 다른 모델로 바꿀 때는 MODEL_DIR만 바꾸면 된다 (파일명은 아래 3개 + project.json의 pose_model)
MODEL_DIR = Path(os.getenv('MODEL_DIR', BASE_DIR / 'models'))
CONFIG_PATH = Path(os.getenv('PROJECT_CONFIG', BASE_DIR / 'project.json'))

MODEL_FILE = 'rf_action_baseline.joblib'
FEATURE_FILE = 'rf_feature_columns.json'
INFO_FILE = 'rf_training_info.json'

FRAME_FEATURE_DIM = 38


@dataclass
class LoadedModels:
    classifier: object
    pose_model: YOLO
    feature_columns: list[str]
    training_info: dict
    config: dict
    device: object

    @property
    def classes(self) -> list[str]:
        return [str(c) for c in self.classifier.classes_]

    @property
    def sequence_steps(self) -> int:
        return int(self.training_info['sequence_steps'])

    @property
    def feature_count(self) -> int:
        return int(self.classifier.n_features_in_)

    @property
    def uncertain_threshold(self) -> float:
        """confidence가 이 값보다 낮으면 '판단 불확실'. 환경변수 UNCERTAIN_THRESHOLD가 project.json보다 우선."""
        return float(os.getenv('UNCERTAIN_THRESHOLD', self.config.get('uncertain_threshold', 0.4)))

    @property
    def model_version(self) -> str:
        return str(self.training_info.get('model_version', 'v1'))


def _read_json(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _resolve_device(requested: str):
    if requested != 'auto':
        return requested
    return 0 if torch.cuda.is_available() else 'cpu'


def load_models() -> LoadedModels:
    config = _read_json(CONFIG_PATH)

    # joblib.load는 우리가 직접 학습한 신뢰 가능한 파일에만 사용한다
    classifier = joblib.load(MODEL_DIR / MODEL_FILE)
    feature_columns = _read_json(MODEL_DIR / FEATURE_FILE)
    training_info = _read_json(MODEL_DIR / INFO_FILE)

    steps = int(training_info['sequence_steps'])
    expected = steps * FRAME_FEATURE_DIM

    # 학습 때와 입력 규격이 다르면 서버를 띄우지 않는다
    checks = {
        'feature_columns 개수': len(feature_columns),
        'training_info.feature_count': int(training_info['feature_count']),
        'model.n_features_in_': int(classifier.n_features_in_),
    }
    for name, value in checks.items():
        if value != expected:
            raise RuntimeError(f'{name}={value}, 기대값 {steps}x{FRAME_FEATURE_DIM}={expected}')

    # 학습 Feature 순서 = src/sequence_utils 가 만드는 순서(t00_nose_x, t00_nose_y, ...)인지 확인
    if list(feature_columns) != sequence_feature_names(steps):
        raise RuntimeError('rf_feature_columns.json 순서가 sequence_utils의 Feature 순서와 다릅니다.')

    model_classes = sorted(str(c) for c in classifier.classes_)
    info_classes = sorted(str(c) for c in training_info['classes'])
    if model_classes != info_classes:
        raise RuntimeError(f'Class 불일치: model={model_classes}, info={info_classes}')

    pose_model = YOLO(str(MODEL_DIR / config['pose_model']))

    return LoadedModels(
        classifier=classifier,
        pose_model=pose_model,
        feature_columns=feature_columns,
        training_info=training_info,
        config=config,
        device=_resolve_device(config.get('device', 'auto')),
    )
