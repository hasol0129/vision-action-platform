import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .camera_capture import CameraError, fetch_snapshot
from .models import AnalysisJob
from .serializers import AnalysisJobSerializer, AnalysisJobStatusSerializer, AnalysisJobUpdateSerializer
from .tasks import run_analysis

logger = logging.getLogger(__name__)


class CameraSnapshotThrottle(UserRateThrottle):
    """미리보기는 0.5초마다 호출되므로 사용자당 분당 240회까지만 허용 (카메라 보호)"""
    rate = '240/min'


def enqueue_analysis(job_id):
    """DB 커밋 후 Redis에 작업을 등록하고 task ID를 저장한다. 큐 연결 실패도 DB에 남긴다."""
    try:
        result = run_analysis.delay(job_id)
    except Exception as exc:
        logger.exception('Celery 작업 등록 실패 job=%s', job_id)
        AnalysisJob.objects.filter(pk=job_id).update(
            status=AnalysisJob.Status.FAILURE,
            error_message=f'작업 대기열(Redis)에 등록하지 못했습니다: {exc}',
            completed_at=timezone.now(),
        )
        return
    AnalysisJob.objects.filter(pk=job_id).update(celery_task_id=result.id)


class AnalysisJobViewSet(viewsets.ModelViewSet):
    """
    POST   /api/analyses/              분석 등록 → 작업 ID 즉시 반환
    GET    /api/analyses/              내 분석 목록 (관리자는 전체)
    GET    /api/analyses/{id}/         상세 + 사람별 결과
    PATCH  /api/analyses/{id}/         제목·메모만 수정
    DELETE /api/analyses/{id}/         삭제 (사람별 예측·영상 파일 함께 삭제)
    GET    /api/analyses/{id}/status/  상태 조회
    """

    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = AnalysisJob.objects.select_related('user').prefetch_related('predictions')
        if self.request.user.is_staff:
            return qs
        return qs.filter(user=self.request.user)  # 다른 회원 기록은 404

    def get_serializer_class(self):
        if self.action == 'partial_update':
            return AnalysisJobUpdateSerializer
        if self.action == 'status':
            return AnalysisJobStatusSerializer
        return AnalysisJobSerializer

    def perform_create(self, serializer):
        job = serializer.save(user=self.request.user, status=AnalysisJob.Status.PENDING)
        # 트랜잭션이 커밋된 뒤에 등록해야 Worker가 아직 없는 Job을 조회하지 않는다
        transaction.on_commit(lambda: enqueue_analysis(job.id))

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        job = self.get_queryset().get(pk=response.data['id'])
        response.data = AnalysisJobSerializer(job, context=self.get_serializer_context()).data
        return response

    def partial_update(self, request, *args, **kwargs):
        super().partial_update(request, *args, **kwargs)
        job = self.get_object()
        return Response(AnalysisJobSerializer(job, context=self.get_serializer_context()).data)

    def destroy(self, request, *args, **kwargs):
        """분석이 끝나기 전에는 삭제를 막는다 (Worker가 지워진 작업에 결과를 쓰지 않도록)."""
        job = self.get_object()
        if not job.is_finished:
            return Response({'detail': '분석이 끝난 뒤에 삭제할 수 있습니다.'}, status=409)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'])
    def status(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@throttle_classes([CameraSnapshotThrottle])
def camera_snapshot(request, key):
    """GET /api/cameras/{key}/snapshot/ — 로그인 사용자에게 허용 카메라의 현재 화면(JPEG)을 대신 전달."""
    if key not in settings.ALLOWED_CAMERAS:
        return Response({'detail': '허용되지 않은 카메라입니다.'}, status=404)
    try:
        jpeg = fetch_snapshot(key)
    except CameraError as exc:
        # busy: DroidCam처럼 한 번에 1개 연결만 받는 카메라를 다른 곳(수집 중인 Worker 등)이 쓰는 중
        return Response({'detail': str(exc), 'busy': exc.busy}, status=409 if exc.busy else 502)
    response = HttpResponse(jpeg, content_type='image/jpeg')
    response['Cache-Control'] = 'no-store'
    return response
