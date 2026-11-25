from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework.routers import DefaultRouter

from . import page_views, views
from .views import AnalysisJobViewSet

app_name = 'analyses'

router = DefaultRouter()
router.register('analyses', AnalysisJobViewSet, basename='analysis')

urlpatterns = [
    # 화면 (단계별 개발가이드 권장 주소: /analyses/, /dashboard/)
    path('', RedirectView.as_view(pattern_name='analyses:index', permanent=False)),
    path('analyses/', page_views.index, name='index'),
    path('analyses/<int:pk>/', page_views.job_detail, name='detail'),
    path('dashboard/', page_views.dashboard, name='dashboard'),

    # API: 권장 주소 /api/v1/... (기존 /api/... 도 같은 View로 계속 동작)
    path('api/v1/cameras/<str:key>/snapshot/', views.camera_snapshot, name='camera-snapshot'),
    path('api/cameras/<str:key>/snapshot/', views.camera_snapshot),
    path('api/v1/', include(router.urls)),
    path('api/', include((router.urls, 'legacy'), namespace='legacy')),
]
