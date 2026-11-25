# django와 celery 서비스가 같은 이미지를 사용한다 (compose.yaml의 command만 다름)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# OpenCV(카메라 수집)가 쓰는 시스템 라이브러리 + IP Webcam 스트림용 ffmpeg 백엔드
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
