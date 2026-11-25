# Django가 시작될 때 Celery 앱도 함께 로드해서 @shared_task가 이 앱을 사용하게 한다
from .celery import app as celery_app

__all__ = ('celery_app',)
