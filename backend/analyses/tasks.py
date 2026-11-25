"""Celery 작업: 영상 확보 → FastAPI 추론 → Django ORM으로 결과·실패 저장."""
import base64
import binascii
import logging

from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .camera_capture import CameraError, capture_clip
from .models import AnalysisJob, PersonPrediction
from .services import AIServiceError, request_prediction

logger = logging.getLogger(__name__)


def _fail(job, message):
    # 작업이 그 사이 삭제됐으면 저장할 곳이 없으므로 조용히 끝낸다
    AnalysisJob.objects.filter(pk=job.pk).update(
        status=AnalysisJob.Status.FAILURE, error_message=message, completed_at=timezone.now())


@shared_task(bind=True)
def run_analysis(self, job_id):
    job = AnalysisJob.objects.filter(pk=job_id).first()
    if job is None:
        logger.warning('job %s가 없습니다(삭제됨).', job_id)
        return

    job.status = AnalysisJob.Status.STARTED
    job.stage = AnalysisJob.Stage.COLLECTING
    job.started_at = timezone.now()
    job.error_message = ''
    job.save(update_fields=['status', 'stage', 'started_at', 'error_message'])

    try:
        # 1) 분석할 영상 확보
        if job.input_type == AnalysisJob.InputType.IP_WEBCAM:
            job.video.name = capture_clip(job.camera_key, settings.CAMERA_CAPTURE_SECONDS, job.id)
            job.save(update_fields=['video'])
        if not job.video:
            raise AIServiceError('분석할 영상이 없습니다.')

        # 2) FastAPI 추론
        job.stage = AnalysisJob.Stage.INFERRING
        job.save(update_fields=['stage'])
        result = request_prediction(job.video.path)

        # 2-1) Skeleton Overlay 대표 Frame (FastAPI가 주면 media/keyframes/에 저장)
        keyframe_b64 = result.get('keyframe_jpeg_base64')
        if keyframe_b64:
            try:
                job.keyframe.save(f'job{job.id}.jpg', ContentFile(base64.b64decode(keyframe_b64)), save=False)
            except (ValueError, binascii.Error):
                logger.warning('job %s keyframe 디코딩 실패', job.id)

        # 3) 결과 저장 (작업 상태와 사람별 예측을 함께)
        with transaction.atomic():
            job.predictions.all().delete()
            PersonPrediction.objects.bulk_create([
                PersonPrediction(
                    job=job,
                    track_id=p['track_id'],
                    action_label=p['action_label'],
                    confidence=p['confidence'],
                    is_uncertain=p.get('is_uncertain', False),
                    window_count=p.get('window_count', 0),
                    valid_frame_count=p.get('valid_frame_count', 0),
                )
                for p in result.get('predictions', [])
            ])
            job.status = AnalysisJob.Status.SUCCESS
            job.stage = AnalysisJob.Stage.DONE
            job.result_message = (result.get('message') or '')[:255]
            job.processing_time_sec = result.get('processing_time_sec')
            job.frame_count = result.get('frame_count')
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'stage', 'keyframe', 'result_message', 'processing_time_sec',
                                    'frame_count', 'completed_at'])

    except (CameraError, AIServiceError) as exc:
        _fail(job, str(exc))
    except Exception as exc:  # 예상 못 한 오류도 상태는 반드시 남긴다
        logger.exception('job %s 분석 실패', job_id)
        _fail(job, f'처리 중 오류가 발생했습니다: {type(exc).__name__}: {exc}')
