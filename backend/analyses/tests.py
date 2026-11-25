import shutil
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from config.celery import app as celery_app

from .camera_capture import CameraError
from .models import AnalysisJob, PersonPrediction
from .services import AIServiceError
from .tasks import run_analysis

TEMP_MEDIA = tempfile.mkdtemp()

FAKE_RESULT = {
    'status': 'ok',
    'message': '2명의 동작을 분석했습니다',
    'predictions': [
        {'track_id': 1, 'action_label': 'wave', 'confidence': 0.82, 'is_uncertain': False,
         'window_count': 1, 'valid_frame_count': 120},
        {'track_id': 2, 'action_label': 'sit_stand', 'confidence': 0.31, 'is_uncertain': True,
         'window_count': 1, 'valid_frame_count': 90},
    ],
    'frame_count': 126,
    'processing_time_sec': 1.23,
}


def video_file(name='clip.mp4'):
    return SimpleUploadedFile(name, b'\x00\x00\x00\x18ftypmp42', content_type='video/mp4')


@override_settings(
    MEDIA_ROOT=TEMP_MEDIA,
    ALLOWED_CAMERAS={'phone1': 'http://192.168.0.10:8080/video'},
)
class AnalysisApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Celery 앱은 시작 시 설정을 읽으므로 override_settings 대신 앱 설정을 직접 바꾼다 (Redis 없이 즉시 실행)
        cls._eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True

    @classmethod
    def tearDownClass(cls):
        celery_app.conf.task_always_eager = cls._eager
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice = User.objects.create_user('alice', password='pw-alice-2026')
        self.bob = User.objects.create_user('bob', password='pw-bob-2026')
        self.admin = User.objects.create_user('admin', password='pw-admin-2026', is_staff=True)

    def make_job(self, user, **kwargs):
        defaults = {'input_type': AnalysisJob.InputType.UPLOAD, 'video': video_file(), 'title': f'{user} job'}
        defaults.update(kwargs)
        return AnalysisJob.objects.create(user=user, **defaults)

    # --- T02 / T05: 등록 즉시 작업 ID 반환, 커밋 후 Celery 작업 실행 ---
    @mock.patch('analyses.tasks.request_prediction', return_value=FAKE_RESULT)
    def test_create_upload_job_returns_id_and_saves_predictions(self, mocked):
        self.client.force_login(self.alice)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            res = self.client.post('/api/analyses/', {
                'input_type': 'upload', 'video': video_file(), 'title': '손 흔들기', 'expected_action': 'wave',
            })
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIn('id', res.data)
        self.assertEqual(res.data['status'], 'PENDING')  # 응답 시점에는 아직 분석 전
        self.assertEqual(len(callbacks), 1)

        job = AnalysisJob.objects.get(pk=res.data['id'])
        self.assertEqual(job.status, 'SUCCESS')
        self.assertTrue(job.celery_task_id)
        self.assertEqual(job.predictions.count(), 2)  # T04: 작업 1건에 사람 2명
        self.assertEqual(job.processing_time_sec, 1.23)
        mocked.assert_called_once_with(job.video.path)

        # T06: 다시 조회해도 DB에 남아 있음
        detail = self.client.get(f'/api/analyses/{job.id}/')
        self.assertEqual([p['track_id'] for p in detail.data['predictions']], [1, 2])
        self.assertTrue(detail.data['predictions'][1]['is_uncertain'])

    @mock.patch('analyses.tasks.request_prediction', return_value=FAKE_RESULT)
    def test_v1_api_urls_work(self, mocked):
        """단계별 개발가이드 권장 주소 /api/v1/analyses/ 와 기존 /api/analyses/ 가 같은 데이터를 준다."""
        self.client.force_login(self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post('/api/v1/analyses/', {'input_type': 'upload', 'video': video_file()})
        self.assertEqual(res.status_code, 201, res.content)
        jid = res.data['id']
        self.assertEqual(self.client.get(f'/api/v1/analyses/{jid}/').data['status'], 'SUCCESS')
        self.assertEqual(self.client.get(f'/api/v1/analyses/{jid}/status/').data['status'], 'SUCCESS')
        self.assertEqual(len(self.client.get('/api/v1/analyses/').data), len(self.client.get('/api/analyses/').data))

    def test_upload_rejects_wrong_extension(self):
        self.client.force_login(self.alice)
        res = self.client.post('/api/analyses/', {
            'input_type': 'upload', 'video': SimpleUploadedFile('note.txt', b'hello'),
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('video', res.data)
        self.assertFalse(AnalysisJob.objects.exists())

    def test_upload_requires_file(self):
        self.client.force_login(self.alice)
        res = self.client.post('/api/analyses/', {'input_type': 'upload'})
        self.assertEqual(res.status_code, 400)

    def test_webcam_requires_allowed_camera_key(self):
        self.client.force_login(self.alice)
        res = self.client.post('/api/analyses/', {'input_type': 'ip_webcam', 'camera_key': 'http://evil.example/'})
        self.assertEqual(res.status_code, 400)
        self.assertIn('camera_key', res.data)

    @mock.patch('analyses.tasks.request_prediction', return_value=FAKE_RESULT)
    @mock.patch('analyses.tasks.capture_clip', return_value='captures/test/job.mp4')
    def test_webcam_job_captures_then_predicts(self, capture, predict):
        self.client.force_login(self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post('/api/analyses/', {'input_type': 'ip_webcam', 'camera_key': 'phone1'})
        self.assertEqual(res.status_code, 201, res.content)
        job = AnalysisJob.objects.get(pk=res.data['id'])
        capture.assert_called_once()
        self.assertEqual(capture.call_args.args[0], 'phone1')
        self.assertEqual(job.video.name, 'captures/test/job.mp4')
        self.assertEqual(job.status, 'SUCCESS')

    # --- T07: 다른 회원 기록 조회·수정·삭제 불가 ---
    def test_user_cannot_access_other_users_job(self):
        bob_job = self.make_job(self.bob)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(f'/api/analyses/{bob_job.id}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/analyses/{bob_job.id}/status/').status_code, 404)
        self.assertEqual(self.client.patch(f'/api/analyses/{bob_job.id}/', {'title': 'hacked'},
                                           content_type='application/json').status_code, 404)
        self.assertEqual(self.client.delete(f'/api/analyses/{bob_job.id}/').status_code, 404)
        self.assertEqual(self.client.get(reverse('analyses:detail', args=[bob_job.id])).status_code, 404)
        bob_job.refresh_from_db()
        self.assertEqual(bob_job.title, 'bob job')

    def test_list_shows_only_own_jobs_but_staff_sees_all(self):
        self.make_job(self.alice)
        self.make_job(self.bob)
        self.client.force_login(self.alice)
        self.assertEqual([j['username'] for j in self.client.get('/api/analyses/').data], ['alice'])
        self.client.force_login(self.admin)
        self.assertEqual(len(self.client.get('/api/analyses/').data), 2)

    def test_patch_changes_only_title_and_memo(self):
        job = self.make_job(self.alice)
        self.client.force_login(self.alice)
        res = self.client.patch(f'/api/analyses/{job.id}/', {
            'title': '새 제목', 'memo': '메모', 'status': 'SUCCESS', 'error_message': 'x',
        }, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        job.refresh_from_db()
        self.assertEqual((job.title, job.memo, job.status, job.error_message), ('새 제목', '메모', 'PENDING', ''))

    def test_put_is_not_allowed(self):
        job = self.make_job(self.alice)
        self.client.force_login(self.alice)
        res = self.client.put(f'/api/analyses/{job.id}/', {'title': 'x'}, content_type='application/json')
        self.assertEqual(res.status_code, 405)

    def test_delete_removes_predictions(self):
        job = self.make_job(self.alice, status='SUCCESS')
        PersonPrediction.objects.create(job=job, track_id=1, action_label='wave', confidence=0.9)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.delete(f'/api/analyses/{job.id}/').status_code, 204)
        self.assertFalse(PersonPrediction.objects.exists())

    def test_cannot_delete_running_job(self):
        """분석 중(PENDING/STARTED)에는 삭제를 막는다 — Worker가 지워진 작업에 쓰지 않도록."""
        job = self.make_job(self.alice, status='STARTED')
        self.client.force_login(self.alice)
        res = self.client.delete(f'/api/v1/analyses/{job.id}/')
        self.assertEqual(res.status_code, 409)
        self.assertTrue(AnalysisJob.objects.filter(pk=job.id).exists())

    def test_status_endpoint(self):
        job = self.make_job(self.alice)
        self.client.force_login(self.alice)
        res = self.client.get(f'/api/analyses/{job.id}/status/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], 'PENDING')
        self.assertEqual(res.data['status_display'], '대기')
        self.assertFalse(res.data['is_finished'])

    # --- T09: 실패도 DB에 남는다 ---
    @mock.patch('analyses.tasks.request_prediction', side_effect=AIServiceError('영상 파일을 열 수 없습니다.'))
    def test_task_failure_is_saved(self, mocked):
        job = self.make_job(self.alice)
        run_analysis(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILURE')
        self.assertEqual(job.error_message, '영상 파일을 열 수 없습니다.')
        self.assertIsNotNone(job.completed_at)

    @mock.patch('analyses.tasks.capture_clip', side_effect=CameraError('카메라에 연결할 수 없습니다.'))
    def test_camera_failure_is_saved(self, mocked):
        job = AnalysisJob.objects.create(user=self.alice, input_type='ip_webcam', camera_key='phone1')
        run_analysis(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILURE')
        self.assertIn('카메라', job.error_message)

    @mock.patch('analyses.tasks.request_prediction', side_effect=RuntimeError('boom'))
    def test_unexpected_error_is_saved(self, mocked):
        job = self.make_job(self.alice)
        run_analysis(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILURE')
        self.assertIn('RuntimeError', job.error_message)

    @mock.patch('analyses.tasks.request_prediction',
                return_value={'status': 'ok', 'message': '영상에서 사람을 찾지 못했습니다', 'predictions': [],
                              'frame_count': 75, 'processing_time_sec': 0.5})
    def test_no_person_is_success_with_message(self, mocked):
        job = self.make_job(self.alice)
        run_analysis(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, 'SUCCESS')
        self.assertEqual(job.predictions.count(), 0)
        self.assertEqual(job.result_message, '영상에서 사람을 찾지 못했습니다')

    # --- T08: 관리자 대시보드 ---
    def test_dashboard_staff_only(self):
        job = self.make_job(self.alice, status='SUCCESS', processing_time_sec=1.0)
        PersonPrediction.objects.create(job=job, track_id=1, action_label='wave', confidence=0.9)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse('analyses:dashboard')).status_code, 302)
        self.client.force_login(self.admin)
        res = self.client.get(reverse('analyses:dashboard'))
        self.assertEqual(res.status_code, 200)
        data = res.context['chart_data']
        self.assertEqual(len(data['actions']['labels']), 6)
        self.assertEqual(data['actions']['labels'][5], 'A006 손 흔들기')
        self.assertEqual(data['actions']['values'][data['actions']['keys'].index('wave')], 1)
        self.assertEqual(data['statuses']['values'][data['statuses']['keys'].index('SUCCESS')], 1)
        self.assertEqual(res.context['kpis']['total_jobs'], 1)

    # --- Skeleton Overlay · 진행 단계 ---
    def test_keyframe_and_stage_saved(self):
        import base64
        jpeg = b'\xff\xd8\xff\xe0fake-jpeg\xff\xd9'
        result = dict(FAKE_RESULT, keyframe_jpeg_base64=base64.b64encode(jpeg).decode())
        job = self.make_job(self.alice)
        with mock.patch('analyses.tasks.request_prediction', return_value=result):
            run_analysis(job.id)
        job.refresh_from_db()
        self.assertEqual((job.status, job.stage), ('SUCCESS', 'DONE'))
        self.assertTrue(job.keyframe.name.startswith('keyframes/'))
        with job.keyframe.open('rb') as f:
            self.assertEqual(f.read(), jpeg)
        self.client.force_login(self.alice)
        self.assertTrue(self.client.get(f'/api/analyses/{job.id}/').data['keyframe'])

    @mock.patch('analyses.tasks.request_prediction', side_effect=AIServiceError('AI 서버 응답 시간이 초과되었습니다'))
    def test_failure_keeps_failed_stage(self, mocked):
        job = self.make_job(self.alice)
        run_analysis(job.id)
        job.refresh_from_db()
        self.assertEqual((job.status, job.stage), ('FAILURE', 'INFERRING'))

    # --- IP Webcam 미리보기 프록시 ---
    @mock.patch('analyses.views.fetch_snapshot', return_value=b'\xff\xd8jpeg')
    def test_camera_snapshot_proxy(self, mocked):
        self.assertIn(self.client.get('/api/cameras/phone1/snapshot/').status_code, (401, 403))
        self.client.force_login(self.alice)
        res = self.client.get('/api/cameras/phone1/snapshot/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'image/jpeg')
        self.assertEqual(res.content, b'\xff\xd8jpeg')
        self.assertEqual(self.client.get('/api/cameras/unknown/snapshot/').status_code, 404)
        mocked.assert_called_once_with('phone1')

    def test_index_page_renders(self):
        self.client.force_login(self.alice)
        res = self.client.get(reverse('analyses:index'))
        self.assertContains(res, 'AI 분석 시작')
        self.assertContains(res, 'IP Webcam')
