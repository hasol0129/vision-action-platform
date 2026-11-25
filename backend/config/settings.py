"""Django 설정. 값은 환경변수(.env → compose env_file)로 받고, 없으면 로컬 개발용 기본값을 쓴다."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.getenv(name, str(int(default))).strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(name, default=''):
    return [v.strip() for v in os.getenv(name, default).split(',') if v.strip()]


SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-only-insecure-key-change-me')
DEBUG = env_bool('DJANGO_DEBUG', True)
if not DEBUG and SECRET_KEY.startswith('dev-only'):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured('DJANGO_DEBUG=0 이면 .env에 DJANGO_SECRET_KEY를 꼭 설정해야 합니다.')
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'accounts',
    'analyses',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# DB: compose에서는 PostgreSQL, 로컬 테스트는 USE_SQLITE=1
if env_bool('USE_SQLITE'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB', 'vision_action'),
            'USER': os.getenv('POSTGRES_USER', 'vision'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''),
            'HOST': os.getenv('POSTGRES_HOST', 'postgres'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# 업로드 영상·카메라 수집 영상. compose에서 django·celery가 같은 볼륨을 공유한다
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', BASE_DIR / 'media'))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'analyses:index'
LOGOUT_REDIRECT_URL = 'login'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
}

# Celery: Redis는 큐·상태만, 결과는 PostgreSQL(ORM)에 저장
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env_bool('CELERY_TASK_ALWAYS_EAGER')
CELERY_TASK_TRACK_STARTED = True
CELERY_TIMEZONE = TIME_ZONE

# FastAPI AI 추론 서버 (컨테이너끼리는 서비스 이름으로 통신)
FASTAPI_URL = os.getenv('FASTAPI_URL', 'http://fastapi:8001').rstrip('/')
FASTAPI_TIMEOUT = int(os.getenv('FASTAPI_TIMEOUT', '300'))

# 업로드 제한
MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '100'))
ALLOWED_VIDEO_EXTENSIONS = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024


def parse_cameras(raw):
    """'phone1=http://192.168.0.10:8080/video,phone2=...' → {'phone1': 'http://...'}"""
    cameras = {}
    for item in raw.split(','):
        if '=' in item:
            key, url = item.split('=', 1)
            if key.strip() and url.strip():
                cameras[key.strip()] = url.strip()
    return cameras


# 수업에서 허용한 카메라만 사용. 사용자는 key만 고르고 URL은 서버 설정에만 있다
ALLOWED_CAMERAS = parse_cameras(os.getenv('ALLOWED_CAMERA_URLS', ''))
CAMERA_CAPTURE_SECONDS = float(os.getenv('CAMERA_CAPTURE_SECONDS', '8'))
CAMERA_OPEN_TIMEOUT_SEC = float(os.getenv('CAMERA_OPEN_TIMEOUT_SEC', '10'))
CAMERA_ROTATE = int(os.getenv('CAMERA_ROTATE', '0'))  # 휴대폰을 옆으로 세웠을 때 90/180/270
CAMERA_SNAPSHOT_TIMEOUT_SEC = float(os.getenv('CAMERA_SNAPSHOT_TIMEOUT_SEC', '3'))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {'analyses': {'handlers': ['console'], 'level': 'INFO'}},
}
