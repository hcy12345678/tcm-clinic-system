from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.ClinicLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register, name="register"),
    path("profile/", views.profile, name="profile"),
    path("users/", views.user_list, name="user_list"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("permissions/", views.permissions, name="permissions"),

    path("schedules/", views.schedule_list, name="schedule_list"),
    path("schedules/create/", views.schedule_create, name="schedule_create"),
    path("schedules/<int:pk>/", views.schedule_detail, name="schedule_detail"),
    path("schedules/<int:pk>/edit/", views.schedule_edit, name="schedule_edit"),
    path("schedules/<int:pk>/delete/", views.schedule_delete, name="schedule_delete"),

    path("appointments/", views.appointment_list, name="appointment_list"),
    path("appointments/create/", views.appointment_create, name="appointment_create"),
    path("appointments/<int:pk>/", views.appointment_detail, name="appointment_detail"),
    path("appointments/<int:pk>/edit/", views.appointment_edit, name="appointment_edit"),
    path("appointments/<int:pk>/cancel/", views.appointment_cancel, name="appointment_cancel"),

    path("visits/", views.visit_list, name="visit_list"),
    path("visits/create/", views.visit_create, name="visit_create"),
    path("visits/<int:pk>/", views.visit_detail, name="visit_detail"),
    path("visits/<int:pk>/edit/", views.visit_edit, name="visit_edit"),

    path("statistics/", views.statistics, name="statistics"),
    path("statistics/export/", views.export_appointments, name="export_appointments"),
    path("statistics/print/", views.print_report, name="print_report"),
    path("logs/", views.operation_logs, name="operation_logs"),
]
