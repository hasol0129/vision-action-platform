from pathlib import Path

from django.conf import settings
from rest_framework import serializers

from .models import AnalysisJob, PersonPrediction


class PersonPredictionSerializer(serializers.ModelSerializer):
    action_label_display = serializers.CharField(source='get_action_label_display', read_only=True)

    class Meta:
        model = PersonPrediction
        fields = ['track_id', 'action_label', 'action_label_display', 'confidence', 'is_uncertain',
                  'window_count', 'valid_frame_count', 'predicted_at']
        read_only_fields = fields


class AnalysisJobSerializer(serializers.ModelSerializer):
    """생성·조회용. 상태·AI 결과 필드는 모두 읽기 전용이다."""

    username = serializers.CharField(source='user.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    input_type_display = serializers.CharField(source='get_input_type_display', read_only=True)
    expected_action_display = serializers.CharField(source='get_expected_action_display', read_only=True)
    stage_display = serializers.CharField(source='get_stage_display', read_only=True)
    is_finished = serializers.BooleanField(read_only=True)
    predictions = PersonPredictionSerializer(many=True, read_only=True)

    class Meta:
        model = AnalysisJob
        fields = ['id', 'username', 'title', 'memo', 'input_type', 'input_type_display',
                  'video', 'camera_key', 'expected_action', 'expected_action_display',
                  'status', 'status_display', 'stage', 'stage_display', 'is_finished', 'celery_task_id',
                  'error_message', 'result_message', 'processing_time_sec', 'frame_count', 'keyframe',
                  'created_at', 'started_at', 'completed_at', 'predictions']
        read_only_fields = ['status', 'stage', 'celery_task_id', 'error_message', 'result_message',
                            'processing_time_sec', 'frame_count', 'keyframe',
                            'created_at', 'started_at', 'completed_at']

    def validate(self, attrs):
        input_type = attrs.get('input_type')
        video = attrs.get('video')
        camera_key = attrs.get('camera_key', '')

        if input_type == AnalysisJob.InputType.UPLOAD:
            if not video:
                raise serializers.ValidationError({'video': '분석할 영상 파일을 선택하세요.'})
            ext = Path(video.name).suffix.lower()
            if ext not in settings.ALLOWED_VIDEO_EXTENSIONS:
                raise serializers.ValidationError(
                    {'video': f'지원하지 않는 형식입니다({ext or "확장자 없음"}). '
                              f'{", ".join(settings.ALLOWED_VIDEO_EXTENSIONS)}만 가능합니다.'})
            if video.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
                raise serializers.ValidationError({'video': f'파일은 {settings.MAX_UPLOAD_MB}MB 이하만 가능합니다.'})
            attrs['camera_key'] = ''

        elif input_type == AnalysisJob.InputType.IP_WEBCAM:
            # 사용자는 허용 목록의 key만 고른다. 임의 URL은 받지 않는다
            if camera_key not in settings.ALLOWED_CAMERAS:
                raise serializers.ValidationError({'camera_key': '허용된 카메라를 선택하세요.'})
            if video:
                raise serializers.ValidationError({'video': 'IP Webcam 분석에는 파일을 첨부하지 않습니다.'})

        return attrs


class AnalysisJobUpdateSerializer(serializers.ModelSerializer):
    """PATCH: 제목·메모만 수정 가능."""

    class Meta:
        model = AnalysisJob
        fields = ['title', 'memo']


class AnalysisJobStatusSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    stage_display = serializers.CharField(source='get_stage_display', read_only=True)
    is_finished = serializers.BooleanField(read_only=True)
    prediction_count = serializers.IntegerField(source='predictions.count', read_only=True)

    class Meta:
        model = AnalysisJob
        fields = ['id', 'input_type', 'status', 'status_display', 'stage', 'stage_display', 'is_finished',
                  'celery_task_id',
                  'error_message', 'result_message', 'processing_time_sec', 'prediction_count',
                  'started_at', 'completed_at']
        read_only_fields = fields
