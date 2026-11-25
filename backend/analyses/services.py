"""FastAPI 추론 서버 호출. 응답·타임아웃·오류를 사람이 읽을 수 있는 메시지로 바꾼다."""
from pathlib import Path

import requests
from django.conf import settings


class AIServiceError(Exception):
    pass


def request_prediction(video_path: str) -> dict:
    url = f'{settings.FASTAPI_URL}/api/v1/predict/'
    path = Path(video_path)
    if not path.exists():
        raise AIServiceError('분석할 영상 파일을 찾을 수 없습니다.')

    try:
        with path.open('rb') as f:
            response = requests.post(
                url,
                files={'file': (path.name, f, 'video/mp4')},
                timeout=(5, settings.FASTAPI_TIMEOUT),  # (연결, 응답) 초
            )
    except requests.Timeout:
        raise AIServiceError(f'AI 서버 응답 시간이 초과되었습니다({settings.FASTAPI_TIMEOUT}초).')
    except requests.ConnectionError:
        raise AIServiceError('AI 서버에 연결할 수 없습니다. fastapi 서비스가 실행 중인지 확인하세요.')

    if response.status_code != 200:
        try:
            detail = response.json().get('detail', {})
            message = detail.get('message') if isinstance(detail, dict) else str(detail)
        except ValueError:
            message = None
        raise AIServiceError(message or f'AI 서버 오류 (HTTP {response.status_code})')

    try:
        return response.json()
    except ValueError:
        raise AIServiceError('AI 서버 응답을 해석할 수 없습니다.')
