from django.urls import path

from . import api

urlpatterns = [
    # 认证
    path("auth/me/", api.auth_me, name="api_auth_me"),
    path("auth/login/", api.auth_login, name="api_auth_login"),
    path("auth/logout/", api.auth_logout, name="api_auth_logout"),
    path("auth/register/", api.auth_register, name="api_auth_register"),
    path("auth/profile/", api.auth_profile, name="api_auth_profile"),

    # 工作台
    path("dashboard/", api.dashboard, name="api_dashboard"),

    # 用户与权限
    path("users/", api.user_list, name="api_user_list"),
    path("users/<int:pk>/", api.user_detail, name="api_user_detail"),
    path("permissions/", api.permissions, name="api_permissions"),

    # 医师
    path("doctors/", api.doctor_list, name="api_doctor_list"),

    # 排班
    path("schedules/", api.schedule_list, name="api_schedule_list"),
    path("schedules/<int:pk>/", api.schedule_detail, name="api_schedule_detail"),

    # 预约
    path("appointments/", api.appointment_list, name="api_appointment_list"),
    path("appointments/options/", api.appointment_options, name="api_appointment_options"),
    path("appointments/<int:pk>/", api.appointment_detail, name="api_appointment_detail"),
    path("appointments/<int:pk>/cancel/", api.appointment_cancel, name="api_appointment_cancel"),

    # 就诊
    path("visits/", api.visit_list, name="api_visit_list"),
    path("visits/options/", api.visit_options, name="api_visit_options"),
    path("visits/<int:pk>/", api.visit_detail, name="api_visit_detail"),

    # 统计与日志
    path("statistics/", api.statistics, name="api_statistics"),
    path("statistics/export/", api.export_appointments, name="api_statistics_export"),
    path("logs/", api.operation_logs, name="api_operation_logs"),
]
