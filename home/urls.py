from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_home, name='dashboard_home'),
    path('auth/', views.auth_view, name='auth_view'),
    path('auth/login/', views.login_action, name='login_view'),
    path('auth/register/', views.register_action, name='register_view'),
    path('auth/logout/', views.logout_action, name='logout'),
    path('device/<int:bin_id>/', views.device_detail, name='device_detail'),
    path('status/', views.system_status, name='system_status'),
    path('api/telemetry/', views.bin_telemetry_ingress, name='api_telemetry'),
    path('api/analytics/', views.analytics_api, name='analytics_api'),
    path('api/device/<int:bin_id>/analytics/', views.device_analytics_api, name='device_analytics_api'),
    path('reports/system.csv', views.system_report_csv, name='system_report_csv'),
    path('reports/system.pdf', views.system_report_pdf, name='system_report_pdf'),
    path('reports/device/<int:bin_id>.csv', views.device_report_csv, name='device_report_csv'),
    path('reports/device/<int:bin_id>.pdf', views.device_report_pdf, name='device_report_pdf'),
    path('dashboard/stats-live/', views.dashboard_stats_fragment, name='dashboard_stats_fragment'),
    path('dashboard/table-live/', views.dashboard_table_fragment, name='dashboard_table_fragment'),
    path('device/<int:bin_id>/live/', views.device_live_fragment, name='device_live_fragment'),
    path('device/<int:bin_id>/controls-live/', views.device_controls_fragment, name='device_controls_fragment'),
    path('device/<int:bin_id>/header-live/', views.device_header_fragment, name='device_header_fragment'),
    path('api/device/<int:bin_id>/<str:command>/', views.device_command, name='api_device_command'),
]
