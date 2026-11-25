"""HTML 화면: 분석 화면, 작업 상세, 관리자 전용 대시보드(ORM 집계)."""
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, render

from .models import ACTION_LABELS, AnalysisJob, PersonPrediction


@login_required
def index(request):
    return render(request, 'analyses/index.html', {
        'cameras': list(settings.ALLOWED_CAMERAS.keys()),
        'actions': ACTION_LABELS,
        'capture_seconds': settings.CAMERA_CAPTURE_SECONDS,
        'max_upload_mb': settings.MAX_UPLOAD_MB,
    })


@login_required
def job_detail(request, pk):
    qs = AnalysisJob.objects.all() if request.user.is_staff else AnalysisJob.objects.filter(user=request.user)
    job = get_object_or_404(qs.select_related('user').prefetch_related('predictions'), pk=pk)
    return render(request, 'analyses/detail.html', {'job': job})


@staff_member_required
def dashboard(request):
    action_counts = dict(
        PersonPrediction.objects.values_list('action_label').annotate(n=Count('id')).values_list('action_label', 'n')
    )
    status_counts = dict(
        AnalysisJob.objects.values_list('status').annotate(n=Count('id')).values_list('status', 'n')
    )
    input_counts = dict(
        AnalysisJob.objects.values_list('input_type').annotate(n=Count('id')).values_list('input_type', 'n')
    )
    avg_times = dict(
        AnalysisJob.objects.filter(status=AnalysisJob.Status.SUCCESS, processing_time_sec__isnull=False)
        .values_list('input_type').annotate(avg=Avg('processing_time_sec')).values_list('input_type', 'avg')
    )

    S = AnalysisJob.Status
    status_order = [S.SUCCESS, S.FAILURE, S.STARTED, S.PENDING]  # 완료 · 실패 · 처리 중 · 대기

    chart_data = {
        # 필수 1: 6개 Action별 예측 건수 (0건도 표시)
        'actions': {
            'keys': [key for key, _ in ACTION_LABELS],
            'labels': [label for _, label in ACTION_LABELS],
            'values': [action_counts.get(key, 0) for key, _ in ACTION_LABELS],
        },
        # 필수 2: 작업 상태별 건수
        'statuses': {
            'keys': [s.value for s in status_order],
            'labels': [s.label for s in status_order],
            'values': [status_counts.get(s.value, 0) for s in status_order],
            'colors': ['#16a34a', '#e5484d', '#3b82f6', '#a3a8bd'],
        },
        # 선택: 입력 방식 비율, 평균 처리 시간
        'inputs': {
            'labels': [label for _, label in AnalysisJob.InputType.choices],
            'values': [input_counts.get(key, 0) for key, _ in AnalysisJob.InputType.choices],
        },
        'avg_time': {
            'labels': [label for _, label in AnalysisJob.InputType.choices],
            'values': [round(avg_times.get(key) or 0, 2) for key, _ in AnalysisJob.InputType.choices],
        },
    }
    total_jobs = AnalysisJob.objects.count()
    finished = status_counts.get(S.SUCCESS, 0) + status_counts.get(S.FAILURE, 0)
    total_predictions = PersonPrediction.objects.count()
    uncertain = PersonPrediction.objects.filter(is_uncertain=True).count()
    avg_all = AnalysisJob.objects.filter(status=S.SUCCESS, processing_time_sec__isnull=False) \
        .aggregate(v=Avg('processing_time_sec'))['v']

    kpis = {
        'total_jobs': total_jobs,
        'success_rate': round(status_counts.get(S.SUCCESS, 0) / finished * 100) if finished else None,
        'avg_time': round(avg_all, 2) if avg_all is not None else None,
        'total_predictions': total_predictions,
        'uncertain_rate': round(uncertain / total_predictions * 100) if total_predictions else None,
        'users': AnalysisJob.objects.values('user').distinct().count(),
    }
    return render(request, 'analyses/dashboard.html', {
        'chart_data': chart_data,
        'kpis': kpis,
        'recent_jobs': AnalysisJob.objects.select_related('user').prefetch_related('predictions')[:10],
    })
