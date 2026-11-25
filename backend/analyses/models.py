from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver

# 6일차 Random Forest가 학습한 6개 Action
ACTION_LABELS = [
    ('bend_return', 'A001 허리 굽혔다 펴기'),
    ('leg_raise_lower', 'A002 한쪽 다리 들었다 내리기'),
    ('walk_turn_walk', 'A003 걷다가 방향 바꾸기'),
    ('drink_return', 'A004 음료 마시기'),
    ('sit_stand', 'A005 앉았다 일어나기'),
    ('wave', 'A006 손 흔들기'),
]


class AnalysisJob(models.Model):
    """분석 요청 1건. 영상 파일 자체는 MEDIA에 두고 DB에는 경로만 저장한다."""

    class InputType(models.TextChoices):
        UPLOAD = 'upload', '영상 업로드'
        IP_WEBCAM = 'ip_webcam', 'IP Webcam'

    class Status(models.TextChoices):
        PENDING = 'PENDING', '대기'
        STARTED = 'STARTED', '처리 중'
        SUCCESS = 'SUCCESS', '완료'
        FAILURE = 'FAILURE', '실패'

    class Stage(models.TextChoices):
        """화면 스텝퍼용 세부 단계. 실패하면 실패한 단계에 머문다."""
        QUEUED = 'QUEUED', '대기'
        COLLECTING = 'COLLECTING', '영상 수집'
        INFERRING = 'INFERRING', 'AI 분석'
        DONE = 'DONE', '완료'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='analysis_jobs')
    title = models.CharField('제목', max_length=100, blank=True)
    memo = models.TextField('메모', blank=True)

    input_type = models.CharField('입력 방식', max_length=20, choices=InputType.choices)
    video = models.FileField('영상', upload_to='uploads/%Y/%m/%d/', blank=True)
    camera_key = models.CharField('카메라', max_length=50, blank=True)
    # 사용자가 "하려고 한 동작"일 뿐, 검증된 정답 Label이 아니다
    expected_action = models.CharField('수행하려는 동작', max_length=30, choices=ACTION_LABELS, blank=True)

    status = models.CharField('상태', max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    stage = models.CharField('진행 단계', max_length=12, choices=Stage.choices, default=Stage.QUEUED)
    keyframe = models.FileField('Skeleton Overlay', upload_to='keyframes/%Y/%m/%d/', blank=True)
    celery_task_id = models.CharField('Celery task ID', max_length=255, blank=True)
    error_message = models.TextField('에러 메시지', blank=True)
    result_message = models.CharField('결과 메시지', max_length=255, blank=True)
    processing_time_sec = models.FloatField('AI 처리 시간(초)', null=True, blank=True)
    frame_count = models.PositiveIntegerField('Frame 수', null=True, blank=True)

    created_at = models.DateTimeField('요청 시간', auto_now_add=True)
    started_at = models.DateTimeField('시작 시간', null=True, blank=True)
    completed_at = models.DateTimeField('완료 시간', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', '-created_at'], name='job_user_recent_idx')]
        verbose_name = '분석 작업'
        verbose_name_plural = '분석 작업'

    def __str__(self):
        return f'#{self.pk} {self.user} {self.get_input_type_display()} {self.status}'

    @property
    def is_finished(self):
        return self.status in (self.Status.SUCCESS, self.Status.FAILURE)


class PersonPrediction(models.Model):
    """한 작업 안의 사람(Track ID)별 예측. track_id는 작업 안에서만 의미 있는 번호다."""

    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name='predictions')
    track_id = models.PositiveIntegerField('Track ID')
    action_label = models.CharField('예측 Action', max_length=30, choices=ACTION_LABELS)
    confidence = models.FloatField('Confidence')
    is_uncertain = models.BooleanField('판단 불확실', default=False)
    window_count = models.PositiveIntegerField('Window 수', default=0)
    valid_frame_count = models.PositiveIntegerField('유효 Frame 수', default=0)
    predicted_at = models.DateTimeField('예측 시간', auto_now_add=True)

    class Meta:
        ordering = ['job', 'track_id']
        indexes = [models.Index(fields=['action_label'], name='pred_action_idx')]
        constraints = [models.UniqueConstraint(fields=['job', 'track_id'], name='unique_track_per_job')]
        verbose_name = '사람별 예측'
        verbose_name_plural = '사람별 예측'

    def __str__(self):
        return f'job#{self.job_id} track{self.track_id} {self.action_label} {self.confidence:.2f}'


@receiver(post_delete, sender=AnalysisJob)
def delete_video_file(sender, instance, **kwargs):
    """작업을 지우면 예측(CASCADE)과 함께 MEDIA의 영상·Overlay 파일도 지운다."""
    for f in (instance.video, instance.keyframe):
        if f:
            f.delete(save=False)
