from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_home, name='dashboard_home'),
    path('auth/', views.auth_view, name='auth_view'),
    path('auth/login/', views.login_action, name='login_view'),
    path('auth/register/', views.register_action, name='register_view'),
    path('auth/logout/', views.logout_action, name='logout'),
    path('device/<int:bin_id>/', views.device_detail, name='device_detail'),
    #path("devices/<int:id>/", views.device_detail, name="device_detail"),
    path('status/', views.system_status, name='system_status'),
    path('api/telemetry/', views.bin_telemetry_ingress, name='api_telemetry'),

    # HTMX live-polling fragments — same data as the pages above, re-rendered
    # every few seconds so the dashboard/device screens update without a reload.
    path('dashboard/stats-live/', views.dashboard_stats_fragment, name='dashboard_stats_fragment'),
    path('dashboard/table-live/', views.dashboard_table_fragment, name='dashboard_table_fragment'),
    path('device/<int:bin_id>/live/', views.device_live_fragment, name='device_live_fragment'),

    # Add this line to catch all device commands (lock, unlock, start-uv, etc.)
    path('api/device/<int:bin_id>/<str:command>/', views.device_command, name='api_device_command'),
]