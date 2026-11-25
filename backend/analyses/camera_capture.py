"""허용된 휴대폰 카메라에서 정해진 시간만 Frame을 읽어 MP4로 저장하고 종료한다.

지원하는 주소 예 (.env의 ALLOWED_CAMERA_URLS에만 적는다)
- IP Webcam 앱 : http://<휴대폰 IP>:8080/video   (/shot.jpg 정지 이미지도 제공)
- DroidCam 앱  : http://<휴대폰 IP>:4747/video   (MJPEG만 제공, 한 번에 1개 연결만 허용)
"""
import time
from pathlib import Path

import cv2
import requests
from django.conf import settings
from django.utils import timezone

MIN_FRAMES = 10          # 이보다 적게 받으면 분석 불가로 처리
READ_FAIL_LIMIT_SEC = 3  # 연속으로 이 시간 동안 Frame이 안 오면 연결 끊김으로 판단
MAX_SNAPSHOT_BYTES = 3 * 1024 * 1024

_ROTATIONS = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def _rotate(frame):
    """휴대폰을 옆으로 세워 찍으면 사람이 누운 영상이 된다 → .env CAMERA_ROTATE(0/90/180/270)만큼 돌린다."""
    code = _ROTATIONS.get(int(getattr(settings, "CAMERA_ROTATE", 0)) % 360)
    return cv2.rotate(frame, code) if code is not None else frame


BUSY_MESSAGE = '카메라가 다른 연결에서 사용 중입니다. 다른 화면의 미리보기나 진행 중인 분석이 끝난 뒤 다시 시도하세요.'


class CameraError(Exception):
    def __init__(self, message, busy=False):
        super().__init__(message)
        self.busy = busy


def _snapshot_url(url: str) -> str | None:
    """IP Webcam 앱은 /video 옆에 /shot.jpg(정지 이미지)를 제공한다."""
    return url[: -len('/video')] + '/shot.jpg' if url.endswith('/video') else None


def _is_busy_page(res: requests.Response) -> bool:
    """DroidCam은 이미 다른 연결이 있으면 200 + 'DroidCam is Busy' HTML을 돌려준다."""
    return res.headers.get('Content-Type', '').startswith('text/html')


def _grab_jpeg_from_stream(url: str, timeout: float) -> bytes:
    """MJPEG 스트림에 잠깐 연결해 첫 JPEG 한 장만 꺼내고 바로 연결을 닫는다."""
    try:
        res = requests.get(url, stream=True, timeout=timeout)
    except requests.RequestException:
        raise CameraError('카메라에 연결할 수 없습니다.')
    try:
        if _is_busy_page(res):
            raise CameraError(BUSY_MESSAGE, busy=True)
        if res.status_code != 200:
            raise CameraError(f'카메라 응답 오류 (HTTP {res.status_code}).')
        buf = b''
        deadline = time.monotonic() + timeout
        for chunk in res.iter_content(chunk_size=16384):
            buf += chunk
            start = buf.find(b'\xff\xd8')
            end = buf.find(b'\xff\xd9', start + 2) if start >= 0 else -1
            if start >= 0 and end > start:
                return _rotate_jpeg(buf[start:end + 2])
            if len(buf) > MAX_SNAPSHOT_BYTES or time.monotonic() > deadline:
                break
    except requests.RequestException:
        raise CameraError('카메라 스트림이 끊겼습니다.')
    finally:
        res.close()
    raise CameraError('카메라에서 화면을 받지 못했습니다.')


def _rotate_jpeg(jpeg: bytes) -> bytes:
    if int(getattr(settings, "CAMERA_ROTATE", 0)) % 360 == 0:
        return jpeg
    import numpy as np
    frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return jpeg
    ok, buf = cv2.imencode(".jpg", _rotate(frame), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else jpeg


def fetch_snapshot(camera_key: str) -> bytes:
    """미리보기용 JPEG 1장. 브라우저에는 카메라 주소를 노출하지 않고 Django가 대신 받아 전달한다."""
    url = settings.ALLOWED_CAMERAS.get(camera_key)
    if not url:
        raise CameraError('허용되지 않은 카메라입니다.')
    timeout = settings.CAMERA_SNAPSHOT_TIMEOUT_SEC

    if url.startswith(('http://', 'https://')):
        shot = _snapshot_url(url)
        if shot:  # IP Webcam: 정지 이미지 주소가 있으면 그것을 쓴다
            try:
                res = requests.get(shot, timeout=timeout)
                if res.status_code == 200 and res.headers.get('Content-Type', '').startswith('image/'):
                    return _rotate_jpeg(res.content)
            except requests.RequestException:
                pass
        return _grab_jpeg_from_stream(url, timeout)  # DroidCam 등: 스트림에서 한 장만

    # rtsp 또는 테스트용 로컬 영상: OpenCV로 한 Frame을 읽는다 (로컬 영상은 시간에 맞춰 반복 재생)
    capture = cv2.VideoCapture(url)
    try:
        if not capture.isOpened():
            raise CameraError('카메라에 연결할 수 없습니다.')
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total > 0 and not url.startswith('rtsp'):
            fps = capture.get(cv2.CAP_PROP_FPS) or 25
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(time.time() * fps) % total)
        ok, frame = capture.read()
    finally:
        capture.release()
    if not ok or frame is None:
        raise CameraError('카메라에서 화면을 받지 못했습니다.')
    ok, buf = cv2.imencode('.jpg', _rotate(frame), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes()


def _check_busy(url: str) -> None:
    """수집 실패 원인이 '다른 연결이 카메라를 쓰는 중'인지 확인해 더 정확한 메시지를 준다."""
    if not url.startswith(('http://', 'https://')):
        return
    try:
        res = requests.get(url, stream=True, timeout=3)
        busy = _is_busy_page(res)
        res.close()
    except requests.RequestException:
        return
    if busy:
        raise CameraError(BUSY_MESSAGE, busy=True)


def capture_clip(camera_key: str, seconds: float, job_id: int) -> str:
    """수집한 영상을 MEDIA_ROOT/captures/에 저장하고 MEDIA 기준 상대 경로를 반환한다."""
    url = settings.ALLOWED_CAMERAS.get(camera_key)
    if not url:
        raise CameraError(f'허용되지 않은 카메라입니다: {camera_key}')

    capture = cv2.VideoCapture(
        url, cv2.CAP_FFMPEG,
        [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(settings.CAMERA_OPEN_TIMEOUT_SEC * 1000),
         cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_FAIL_LIMIT_SEC * 1000],
    )
    if not capture.isOpened():
        capture.release()
        _check_busy(url)
        raise CameraError('카메라에 연결할 수 없습니다. 휴대폰 카메라 앱이 켜져 있고 같은 네트워크인지 확인하세요.')

    rel_dir = Path('captures') / timezone.localtime().strftime('%Y/%m/%d')
    out_dir = Path(settings.MEDIA_ROOT) / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'job{job_id}_{int(time.time())}.mp4'
    tmp_path = out_dir / f'.{filename}.part.mp4'

    frames = []
    started = time.monotonic()
    last_ok = started
    try:
        # seconds 동안 들어오는 Frame을 모은다 (연결 시간은 포함하지 않음)
        while time.monotonic() - started < seconds:
            ok, frame = capture.read()
            now = time.monotonic()
            if ok and frame is not None:
                frames.append(_rotate(frame))
                last_ok = now
            elif now - last_ok > READ_FAIL_LIMIT_SEC:
                break
            elif not ok and not url.startswith(('http', 'rtsp')):
                break  # 테스트용 로컬 파일: 끝까지 읽음
    finally:
        capture.release()

    elapsed = max(time.monotonic() - started, 1e-3)
    if len(frames) < MIN_FRAMES:
        if not frames:
            _check_busy(url)
        raise CameraError(f'카메라에서 영상을 충분히 받지 못했습니다({len(frames)} Frame). 연결이 끊겼을 수 있습니다.')

    fps = len(frames) / elapsed if url.startswith(('http', 'rtsp')) else 25.0
    fps = min(max(fps, 1.0), 60.0)
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(tmp_path), cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))
    for frame in frames:
        if frame.shape[:2] != (height, width):
            frame = cv2.resize(frame, (width, height))
        writer.write(frame)
    writer.release()

    final_path = out_dir / filename
    tmp_path.rename(final_path)
    return str(rel_dir / filename)
