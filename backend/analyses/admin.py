from django.contrib import admin

from .models import AnalysisJob, PersonPrediction


class PersonPredictionInline(admin.TabularInline):
    model = PersonPrediction
    extra = 0
    can_delete = False
    readonly_fields = ['track_id', 'action_label', 'confidence', 'is_uncertain',
                       'window_count', 'valid_frame_count', 'predicted_at']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'input_type', 'status', 'expected_action', 'prediction_summary',
                    'processing_time_sec', 'created_at']
    list_filter = ['status', 'input_type', 'expected_action', 'created_at']
    search_fields = ['user__username', 'title', 'celery_task_id']
    readonly_fields = ['status', 'celery_task_id', 'error_message', 'result_message', 'processing_time_sec',
                       'frame_count', 'created_at', 'started_at', 'completed_at']
    inlines = [PersonPredictionInline]
    list_select_related = ['user']

    def get_queryset(self, request):
        # 목록의 '사람별 예측' 칸이 행마다 쿼리를 날리지 않게 한 번에 가져온다 (N+1 방지)
        return super().get_queryset(request).prefetch_related('predictions')

    @admin.display(description='사람별 예측')
    def prediction_summary(self, obj):
        items = obj.predictions.all()
        return ', '.join(f'#{p.track_id} {p.action_label}({p.confidence:.2f})' for p in items) or '-'


@admin.register(PersonPrediction)
class PersonPredictionAdmin(admin.ModelAdmin):
    list_display = ['id', 'job', 'track_id', 'action_label', 'confidence', 'is_uncertain', 'predicted_at']
    list_filter = ['action_label', 'is_uncertain', 'job__input_type']
    search_fields = ['job__user__username', 'job__id']
    list_select_related = ['job', 'job__user']
