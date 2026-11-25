# 코드 읽는 순서 (CODE_GUIDE)

처음 보는 사람이 **"AI 분석 시작" 버튼 한 번이 어떤 파일을 거쳐 가는지** 따라가며 읽을 수 있게 순서대로 정리했습니다.
각 파일은 "무엇을 하나 → 꼭 볼 부분" 순서로 적었습니다.

---

## 0. 전체 그림 먼저

| 서비스 | 폴더 | 한 줄 역할 |
|---|---|---|
| django | `backend/` | 회원·화면·API·DB 저장(ORM) |
| celery | `backend/` (같은 코드) | 오래 걸리는 분석을 뒤에서 처리하고 결과 저장 |
| redis | (이미지만 사용) | celery 작업 대기열 |
| postgres | (이미지만 사용) | 회원·분석 기록 영구 저장 |
| fastapi | `ai_service/` | 영상 → 자세 추출 → 동작 예측 JSON (DB 모름) |

그림: [docs/architecture.png](docs/architecture.png) · [docs/button_flow.png](docs/button_flow.png) · [docs/erd.png](docs/erd.png)

---

## 1. `compose.yaml` — 서비스 5개를 한 번에 띄우는 설정

- 5개 서비스(django · fastapi · celery · redis · postgres)가 어떻게 연결되는지 정의합니다.
- **꼭 볼 부분**
  - `django`와 `celery`가 같은 `./backend` 이미지를 쓰고, `media` 볼륨을 같이 씁니다 → 업로드한 영상을 celery가 읽을 수 있음
  - `celery`는 `fastapi`가 healthy(모델 로드 완료)가 된 뒤 시작
  - 서비스끼리는 `localhost`가 아니라 이름(`postgres`, `redis`, `fastapi`)으로 통신
  - `pgdata` 볼륨 → 컨테이너를 다시 띄워도 DB 유지

## 2. `backend/static/js/analyses.js` — 버튼을 누르면 시작되는 곳 (브라우저)

- 탭 전환(영상 업로드 / IP Webcam), 영상 미리보기, `AI 분석 시작` 버튼, 상태 표시, 결과 표를 담당합니다.
- **꼭 볼 부분**
  - `form.addEventListener('submit', ...)` → `POST /api/v1/analyses/` 로 영상(또는 카메라 이름)을 보냄
  - 응답으로 **작업 ID**를 바로 받고, `poll()`이 1.5초마다 `GET /api/v1/analyses/{id}/status/` 를 호출
  - `renderStepper()` → 대기 · 영상 수집 · AI 분석 · 완료 4단계 표시
  - 끝나면 `resultHtml()`로 사람별 결과 표, `showKeyframe()`으로 Skeleton Overlay 이미지 표시
  - IP Webcam 미리보기는 `startLive()`가 `/api/v1/cameras/{key}/snapshot/` 을 0.5초마다 다시 불러옴 (카메라 주소는 브라우저가 모름)

## 3. `backend/analyses/views.py` — 요청을 받아 작업을 등록 (Django · DRF)

- `AnalysisJobViewSet` 하나로 등록·목록·상세·메모 수정·삭제·상태 조회를 처리합니다.
- **꼭 볼 부분**
  - `get_queryset()` → 일반 회원은 **자기 작업만** 보임 (남의 것은 404)
  - `perform_create()` → DB에 `PENDING`으로 저장하고, `transaction.on_commit(...)`으로 **저장이 끝난 뒤에** celery 작업 등록
  - `enqueue_analysis()` → `run_analysis.delay(job_id)` 후 task ID 저장. Redis가 죽어 있으면 FAILURE로 기록
  - `partial_update` → 제목·메모만 수정 가능 (`AnalysisJobUpdateSerializer`)
  - `camera_snapshot()` → 허용 카메라의 현재 화면을 대신 가져다 줌
- 함께 보면 좋은 파일
  - `serializers.py` : 확장자·크기 검사, 카메라는 허용 목록의 이름만 받음, 상태·결과 필드는 읽기 전용
  - `models.py` : `AnalysisJob`(요청 1건) · `PersonPrediction`(사람별 예측) — ERD 그대로
  - `urls.py` : `/api/v1/analyses/` 라우터, `/dashboard/`, `/api/v1/cameras/{key}/snapshot/`

## 4. `backend/analyses/tasks.py` — 뒤에서 실제로 분석을 돌리는 작업 (Celery Worker)

- `run_analysis(job_id)` 하나가 전부입니다.
- **꼭 볼 부분 (위에서 아래로 순서대로 실행)**
  1. 상태를 `STARTED`, 단계를 `COLLECTING`(영상 수집)으로 저장
  2. IP Webcam이면 `camera_capture.capture_clip()`으로 8초 녹화 → `media/captures/…mp4`
  3. 단계를 `INFERRING`(AI 분석)으로 바꾸고 `services.request_prediction()` 호출
  4. 받은 Overlay 이미지를 `media/keyframes/`에 저장
  5. `transaction.atomic()` 안에서 `PersonPrediction` 여러 줄 저장 + `SUCCESS`
  6. 어디서든 오류가 나면 `_fail()` → `FAILURE` + `error_message` (화면에 그대로 보임)
- 함께 보면 좋은 파일: `camera_capture.py` (허용된 카메라만 열고, 정해진 시간만 읽고, 끊기면 실패 처리)

## 5. `backend/analyses/services.py` — FastAPI 호출 담당

- 영상 파일을 `POST {FASTAPI_URL}/api/v1/predict/` 로 보냅니다 (multipart).
- **꼭 볼 부분**: 연결 5초 · 응답 300초 timeout, 연결 실패·시간 초과·400 오류를 사람이 읽을 수 있는 한국어 메시지로 바꿔 `AIServiceError`로 올림

## 6. `ai_service/routers/predictions.py` — AI 서버 입구 (FastAPI)

- `POST /api/v1/predict/` 함수 하나.
- **꼭 볼 부분**
  - 확장자 검사 → 임시 파일 저장 → `extract_tracks()` → `predict_tracks()` → `render_keyframe()` 순서
  - 영상을 못 읽으면 **400 + 사유**, 사람이 없으면 **200 + 빈 목록 + "영상에서 사람을 찾지 못했습니다"** (두 경우를 Worker가 구분 가능)
- 시작점 `ai_service/main.py`: 서버가 켜질 때 `load_models()`로 모델을 **한 번만** 올리고, `GET /health`로 준비 여부를 알려 줌

## 7. `ai_service/services/pose_pipeline.py` — 영상 → 사람별 관절 데이터

- YOLO Pose `model.track(persist=True)`로 Frame마다 사람을 찾고 **Track ID**를 붙입니다 (8일차 다중 인물 코드와 같은 방식).
- **꼭 볼 부분**
  - Track ID마다 `feature_from_keypoints()`(기존 `src/multi_person_utils.py`)로 38개 숫자(정규화 좌표 34 + 관절 각도 4)를 모음
  - `_reset_tracker()` → 이전 영상의 Track 번호가 이어지지 않게 초기화
  - 사람이 가장 많이 잡힌 Frame 하나를 `KeyFrame`으로 기억 → Overlay 그림에 사용

## 8. `ai_service/services/action_inference.py` — 사람별 동작 예측

- **꼭 볼 부분**
  - Track 전체를 `resample_sequence()`로 **30 Step**에 맞춤 → `flatten_sequence()`로 30 × 38 = **1,140개** 숫자
  - 6일차 학습 때도 Clip 전체를 30 Step으로 줄였기 때문에 같은 방식 (5초 Window로 자르면 긴 영상이 틀렸던 문제를 이렇게 고침)
  - `predict_proba()`에서 가장 큰 값 = 예측 동작, 그 확률 = confidence
  - confidence가 `UNCERTAIN_THRESHOLD`(기본 0.4)보다 낮으면 `판단 불확실` (값 자체는 바꾸지 않음)

## 9. `ai_service/services/model_loader.py` — 모델 파일 불러오기와 규격 검사

- `models/`의 `rf_action_baseline.joblib` · `rf_feature_columns.json` · `rf_training_info.json` · `yolo11n-pose.pt`를 읽습니다.
- **꼭 볼 부분**: Feature 수(1,140)와 **순서**, 6개 Class가 학습 때와 다르면 서버가 `model_ready=false`로 뜨고 이유를 알려 줌

---

## 그 밖의 파일

| 파일 | 하는 일 |
|---|---|
| `ai_service/services/overlay.py` | 대표 Frame에 관절(민트색)·Track ID·예측을 그려 JPEG(base64)로 반환 |
| `ai_service/src/*.py` | 1~8일차 실습 코드 복사본 (정규화·각도·리샘플·다중 인물) |
| `backend/analyses/page_views.py` | 분석 화면, 상세 화면, 관리자 `/dashboard/` (ORM으로 차트 숫자 집계) |
| `backend/analyses/admin.py` | Django Admin 목록·검색·필터, 사람별 예측을 작업 안에 같이 표시 |
| `backend/static/js/dashboard.js` | Chart.js로 동작별(가로 막대) · 상태별(도넛) · 입력 방식 · 평균 처리 시간 차트 |
| `backend/templates/` | 화면 HTML (base · 로그인 · 회원가입 · 분석 · 상세 · 대시보드) |
| `backend/*/tests.py` | 29개 테스트: 회원, 권한(T07), 비동기 등록, 실패 저장, Overlay, 카메라 프록시, 대시보드 |
