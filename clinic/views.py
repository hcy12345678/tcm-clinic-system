from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .audit import log_action
from .decorators import menu_required, staff_required
from .forms import (
    AdminUserForm,
    AppointmentForm,
    LoginForm,
    ProfileForm,
    RegisterForm,
    ScheduleForm,
    VisitForm,
)
from .models import (
    Appointment,
    Doctor,
    OperationLog,
    RolePermission,
    Schedule,
    User,
    Visit,
    VisitHistory,
)
from .statistics import appointment_dataframe, filter_appointments, summarize_appointments


def paginate(request, queryset, per_page=10):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def appointment_scope(user):
    queryset = Appointment.objects.select_related(
        "patient", "schedule__doctor__user"
    )
    if user.role == User.Role.PATIENT:
        return queryset.filter(patient=user)
    if user.role == User.Role.DOCTOR:
        if hasattr(user, "doctor_profile"):
            return queryset.filter(schedule__doctor=user.doctor_profile)
        return queryset.none()
    return queryset


def visit_scope(user):
    queryset = Visit.objects.select_related(
        "appointment__patient", "appointment__schedule__doctor__user", "operator"
    )
    if user.role == User.Role.PATIENT:
        return queryset.filter(appointment__patient=user)
    if user.role == User.Role.DOCTOR:
        if hasattr(user, "doctor_profile"):
            return queryset.filter(appointment__schedule__doctor=user.doctor_profile)
        return queryset.none()
    return queryset


def can_manage_schedule(user, schedule=None):
    if user.role == User.Role.ADMIN:
        return True
    if user.role != User.Role.DOCTOR or not hasattr(user, "doctor_profile"):
        return False
    return schedule is None or schedule.doctor_id == user.doctor_profile.id


class ClinicLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, "用户与权限", "登录", self.request.user.username, "登录成功")
        return response


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        log_action(request, "用户与权限", "退出", request.user.username)
    auth_logout(request)
    return redirect("login")


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        auth_login(request, user)
        log_action(request, "用户与权限", "用户注册", user.username, "患者自助注册")
        messages.success(request, "注册成功，已为您登录。")
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    appointments = appointment_scope(request.user)
    today = timezone.localdate()
    context = {
        "doctor_count": Doctor.objects.filter(is_active=True).count(),
        "patient_count": User.objects.filter(role=User.Role.PATIENT, is_active=True).count(),
        "today_appointment_count": appointments.filter(schedule__date=today).count(),
        "today_schedule_count": Schedule.objects.filter(date=today, status=Schedule.Status.OPEN).count(),
        "recent_appointments": appointments[:6],
    }
    return render(request, "dashboard.html", context)


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request, "用户与权限", "资料维护", request.user.username)
        messages.success(request, "个人资料已保存。")
        return redirect("profile")
    return render(request, "form.html", {"title": "个人资料维护", "form": form, "submit_label": "保存资料"})


@menu_required("can_user")
def user_list(request):
    users = User.objects.all().order_by("id")
    keyword = request.GET.get("keyword", "").strip()
    role = request.GET.get("role", "")
    if keyword:
        users = users.filter(Q(username__icontains=keyword) | Q(first_name__icontains=keyword) | Q(phone__icontains=keyword))
    if role in User.Role.values:
        users = users.filter(role=role)
    return render(request, "users/list.html", {
        "users": paginate(request, users),
        "roles": User.Role.choices,
        "keyword": keyword,
        "selected_role": role,
    })


@menu_required("can_user")
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = AdminUserForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request, "用户与权限", "编辑用户", user.username, f"角色：{user.get_role_display()}")
        messages.success(request, "用户资料已更新。")
        return redirect("user_list")
    return render(request, "form.html", {"title": f"编辑用户：{user.display_name}", "form": form, "submit_label": "保存修改"})


@menu_required("can_user")
def permissions(request):
    permission_objects = []
    for role, _ in User.Role.choices:
        item, _ = RolePermission.objects.get_or_create(role=role, defaults=RolePermission.defaults_for(role))
        permission_objects.append(item)
    fields = ("can_user", "can_schedule", "can_appointment", "can_visit", "can_statistics")
    if request.method == "POST":
        for item in permission_objects:
            for field in fields:
                setattr(item, field, request.POST.get(f"{item.role}_{field}") in ("on", "1"))
            item.save()
        log_action(request, "用户与权限", "权限配置", "角色权限", "更新角色菜单权限")
        messages.success(request, "角色菜单与访问权限已保存。")
        return redirect("permissions")
    return render(request, "users/permissions.html", {"permissions": permission_objects})


@menu_required("can_schedule")
def schedule_list(request):
    schedules = Schedule.objects.select_related("doctor__user")
    if request.user.role == User.Role.DOCTOR and hasattr(request.user, "doctor_profile"):
        schedules = schedules.filter(doctor=request.user.doctor_profile)
    keyword = request.GET.get("keyword", "").strip()
    doctor_id = request.GET.get("doctor", "")
    status = request.GET.get("status", "")
    start_date = parse_date(request.GET.get("start_date", ""))
    end_date = parse_date(request.GET.get("end_date", ""))
    if keyword:
        schedules = schedules.filter(Q(doctor__user__first_name__icontains=keyword) | Q(doctor__department__icontains=keyword) | Q(room__icontains=keyword))
    if doctor_id.isdigit():
        schedules = schedules.filter(doctor_id=doctor_id)
    if status in Schedule.Status.values:
        schedules = schedules.filter(status=status)
    if start_date:
        schedules = schedules.filter(date__gte=start_date)
    if end_date:
        schedules = schedules.filter(date__lte=end_date)
    return render(request, "schedules/list.html", {
        "schedules": paginate(request, schedules),
        "doctors": Doctor.objects.select_related("user"),
        "keyword": keyword,
        "selected_doctor": doctor_id,
        "selected_status": status,
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
        "can_manage": request.user.role in (User.Role.ADMIN, User.Role.DOCTOR),
    })


@menu_required("can_schedule")
def schedule_detail(request, pk):
    schedule = get_object_or_404(Schedule.objects.select_related("doctor__user"), pk=pk)
    if not can_manage_schedule(request.user, schedule) and request.user.role == User.Role.DOCTOR:
        raise PermissionDenied("不能查看其他医师的排班详情。")
    return render(request, "schedules/detail.html", {
        "schedule": schedule,
        "can_manage": can_manage_schedule(request.user, schedule),
    })


@staff_required
@menu_required("can_schedule")
def schedule_create(request):
    if not can_manage_schedule(request.user):
        raise PermissionDenied("当前医师账号没有医师档案。")
    form = ScheduleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        schedule = form.save(commit=False)
        if request.user.role == User.Role.DOCTOR:
            schedule.doctor = request.user.doctor_profile
        schedule.save()
        log_action(request, "医师排班", "新增排班", schedule.pk, str(schedule))
        messages.success(request, "排班新增成功。")
        return redirect("schedule_list")
    return render(request, "form.html", {"title": "新增医师排班", "form": form, "submit_label": "保存排班"})


@staff_required
@menu_required("can_schedule")
def schedule_edit(request, pk):
    schedule = get_object_or_404(Schedule, pk=pk)
    if not can_manage_schedule(request.user, schedule):
        raise PermissionDenied("不能编辑其他医师的排班。")
    form = ScheduleForm(request.POST or None, instance=schedule)
    if request.method == "POST" and form.is_valid():
        schedule = form.save(commit=False)
        if request.user.role == User.Role.DOCTOR:
            schedule.doctor = request.user.doctor_profile
        schedule.save()
        log_action(request, "医师排班", "编辑排班", schedule.pk, str(schedule))
        messages.success(request, "排班修改成功。")
        return redirect("schedule_detail", pk=schedule.pk)
    return render(request, "form.html", {"title": "编辑医师排班", "form": form, "submit_label": "保存修改"})


@staff_required
@menu_required("can_schedule")
def schedule_delete(request, pk):
    schedule = get_object_or_404(Schedule, pk=pk)
    if not can_manage_schedule(request.user, schedule):
        raise PermissionDenied("不能删除其他医师的排班。")
    if schedule.appointments.exists():
        messages.error(request, "该排班已有预约记录，不能删除，可改为暂停预约。")
        return redirect("schedule_detail", pk=pk)
    if request.method == "POST":
        name = str(schedule)
        schedule.delete()
        log_action(request, "医师排班", "删除排班", pk, name)
        messages.success(request, "排班已删除。")
        return redirect("schedule_list")
    return render(request, "confirm_delete.html", {
        "title": "删除医师排班", "object": schedule, "cancel_url": reverse_lazy("schedule_detail", kwargs={"pk": pk}),
    })


@menu_required("can_appointment")
def appointment_list(request):
    appointments = appointment_scope(request.user)
    keyword = request.GET.get("keyword", "").strip()
    status = request.GET.get("status", "")
    doctor_id = request.GET.get("doctor", "")
    start_date = parse_date(request.GET.get("start_date", ""))
    end_date = parse_date(request.GET.get("end_date", ""))
    if keyword:
        appointments = appointments.filter(Q(appointment_no__icontains=keyword) | Q(patient__first_name__icontains=keyword) | Q(schedule__doctor__user__first_name__icontains=keyword))
    if doctor_id.isdigit():
        appointments = appointments.filter(schedule__doctor_id=doctor_id)
    if status in Appointment.Status.values:
        appointments = appointments.filter(status=status)
    if start_date:
        appointments = appointments.filter(schedule__date__gte=start_date)
    if end_date:
        appointments = appointments.filter(schedule__date__lte=end_date)
    return render(request, "appointments/list.html", {
        "appointments": paginate(request, appointments),
        "doctors": Doctor.objects.select_related("user"),
        "keyword": keyword,
        "selected_status": status,
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
    })


@menu_required("can_appointment")
def appointment_create(request):
    form = AppointmentForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        appointment = form.save(commit=False)
        if request.user.role == User.Role.PATIENT:
            appointment.patient = request.user
        appointment.save()
        log_action(request, "预约挂号", "创建预约", appointment.appointment_no, f"患者：{appointment.patient.display_name}")
        messages.success(request, f"预约成功，预约编号：{appointment.appointment_no}")
        return redirect("appointment_detail", pk=appointment.pk)
    return render(request, "form.html", {"title": "创建预约挂号", "form": form, "submit_label": "提交预约"})


@menu_required("can_appointment")
def appointment_detail(request, pk):
    appointment = get_object_or_404(appointment_scope(request.user), pk=pk)
    can_edit = request.user.role != User.Role.PATIENT or appointment.status == Appointment.Status.BOOKED
    return render(request, "appointments/detail.html", {"appointment": appointment, "can_edit": can_edit})


@menu_required("can_appointment")
def appointment_edit(request, pk):
    appointment = get_object_or_404(appointment_scope(request.user), pk=pk)
    if request.user.role == User.Role.PATIENT and appointment.status != Appointment.Status.BOOKED:
        raise PermissionDenied("该预约当前不能修改。")
    form = AppointmentForm(request.POST or None, instance=appointment, user=request.user)
    if request.method == "POST" and form.is_valid():
        appointment = form.save()
        log_action(request, "预约挂号", "维护明细", appointment.appointment_no, f"状态：{appointment.get_status_display()}")
        messages.success(request, "预约明细已更新。")
        return redirect("appointment_detail", pk=appointment.pk)
    return render(request, "form.html", {"title": "维护预约明细", "form": form, "submit_label": "保存修改"})


@require_POST
@menu_required("can_appointment")
def appointment_cancel(request, pk):
    appointment = get_object_or_404(appointment_scope(request.user), pk=pk)
    if appointment.status != Appointment.Status.BOOKED or hasattr(appointment, "visit"):
        messages.error(request, "当前预约不能取消。")
    else:
        appointment.status = Appointment.Status.CANCELLED
        appointment.save(update_fields=["status", "updated_at"])
        log_action(request, "预约挂号", "取消预约", appointment.appointment_no)
        messages.success(request, "预约已取消。")
    return redirect("appointment_detail", pk=pk)


@menu_required("can_visit")
def visit_list(request):
    visits = visit_scope(request.user)
    keyword = request.GET.get("keyword", "").strip()
    status = request.GET.get("status", "")
    start_date = parse_date(request.GET.get("start_date", ""))
    end_date = parse_date(request.GET.get("end_date", ""))
    if keyword:
        visits = visits.filter(Q(appointment__appointment_no__icontains=keyword) | Q(appointment__patient__first_name__icontains=keyword) | Q(diagnosis__icontains=keyword))
    if status in Visit.Status.values:
        visits = visits.filter(status=status)
    if start_date:
        visits = visits.filter(visit_time__date__gte=start_date)
    if end_date:
        visits = visits.filter(visit_time__date__lte=end_date)
    return render(request, "visits/list.html", {
        "visits": paginate(request, visits),
        "keyword": keyword,
        "selected_status": status,
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
        "can_manage": request.user.role in (User.Role.ADMIN, User.Role.DOCTOR),
    })


@staff_required
@menu_required("can_visit")
def visit_create(request):
    form = VisitForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        visit = form.save(commit=False)
        visit.operator = request.user
        visit.save()
        VisitHistory.objects.create(visit=visit, action="创建就诊登记", note=form.cleaned_data.get("history_note", ""), operator=request.user)
        if visit.status == Visit.Status.FINISHED:
            visit.appointment.status = Appointment.Status.COMPLETED
            visit.appointment.save(update_fields=["status", "updated_at"])
        log_action(request, "就诊登记", "创建登记", visit.pk, visit.appointment.appointment_no)
        messages.success(request, "就诊登记已创建。")
        return redirect("visit_detail", pk=visit.pk)
    return render(request, "form.html", {"title": "就诊登记处理", "form": form, "submit_label": "保存登记"})


@menu_required("can_visit")
def visit_detail(request, pk):
    visit = get_object_or_404(visit_scope(request.user), pk=pk)
    return render(request, "visits/detail.html", {
        "visit": visit,
        "histories": visit.histories.select_related("operator"),
        "can_manage": request.user.role in (User.Role.ADMIN, User.Role.DOCTOR),
    })


@staff_required
@menu_required("can_visit")
def visit_edit(request, pk):
    visit = get_object_or_404(visit_scope(request.user), pk=pk)
    form = VisitForm(request.POST or None, request.FILES or None, instance=visit, user=request.user)
    if request.method == "POST" and form.is_valid():
        visit = form.save(commit=False)
        visit.operator = request.user
        visit.save()
        VisitHistory.objects.create(
            visit=visit,
            action=f"状态更新为{visit.get_status_display()}",
            note=form.cleaned_data.get("history_note", ""),
            operator=request.user,
        )
        appointment = visit.appointment
        if visit.status == Visit.Status.FINISHED:
            appointment.status = Appointment.Status.COMPLETED
        elif appointment.status == Appointment.Status.COMPLETED:
            appointment.status = Appointment.Status.BOOKED
        appointment.save(update_fields=["status", "updated_at"])
        log_action(request, "就诊登记", "状态流转", visit.pk, f"{visit.get_status_display()}；{visit.note}")
        messages.success(request, "就诊状态与留痕已保存。")
        return redirect("visit_detail", pk=visit.pk)
    return render(request, "form.html", {"title": "就诊确认与状态流转", "form": form, "submit_label": "保存处理结果"})


@menu_required("can_statistics")
def statistics(request):
    appointments = filter_appointments(request, appointment_scope(request.user))
    result = summarize_appointments(appointments)
    return render(request, "statistics.html", {
        "stats": result["stats"],
        "chart_data": result["chart_data"],
        "records": appointments[:20],
        "doctors": Doctor.objects.select_related("user"),
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
        "selected_doctor": request.GET.get("doctor", ""),
        "selected_status": request.GET.get("status", ""),
    })


@menu_required("can_statistics")
def export_appointments(request):
    appointments = filter_appointments(request, appointment_scope(request.user))
    df = appointment_dataframe(appointments).copy()
    if not df.empty:
        df["schedule_date"] = df["schedule_date"].dt.strftime("%Y-%m-%d")
        df["status"] = df["status"].map(dict(Appointment.Status.choices))
        df["created_at"] = pd_to_local_string(df["created_at"])
    df = df.rename(columns={
        "appointment_no": "预约编号", "patient_name": "患者姓名", "patient_username": "患者账号",
        "doctor_name": "医师姓名", "department": "科室", "schedule_date": "出诊日期",
        "status": "预约状态", "created_at": "创建时间",
    })
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = "attachment; filename=appointments.csv"
    response.write("\ufeff")
    response.write(df.to_csv(index=False))
    return response


def pd_to_local_string(series):
    return series.astype(str).str.replace("T", " ", regex=False).str.slice(0, 19)


@menu_required("can_statistics")
def print_report(request):
    appointments = filter_appointments(request, appointment_scope(request.user))
    result = summarize_appointments(appointments)
    selected_doctor = request.GET.get("doctor", "")
    selected_status = request.GET.get("status", "")
    doctor = Doctor.objects.filter(pk=selected_doctor).first() if selected_doctor.isdigit() else None
    return render(request, "print_report.html", {
        "stats": result["stats"],
        "records": appointments,
        "generated_at": timezone.localtime(),
        "filters": {
            "start_date": request.GET.get("start_date", ""),
            "end_date": request.GET.get("end_date", ""),
            "selected_doctor": selected_doctor,
            "doctor_name": doctor.user.display_name if doctor else "",
            "selected_status": selected_status,
            "status_display": dict(Appointment.Status.choices).get(selected_status, ""),
        },
    })


@menu_required("can_statistics")
def operation_logs(request):
    logs = OperationLog.objects.select_related("operator")
    if request.user.role == User.Role.DOCTOR:
        logs = logs.filter(operator=request.user)
    keyword = request.GET.get("keyword", "").strip()
    module = request.GET.get("module", "")
    start_date = parse_date(request.GET.get("start_date", ""))
    end_date = parse_date(request.GET.get("end_date", ""))
    if keyword:
        logs = logs.filter(Q(operator__username__icontains=keyword) | Q(operator__first_name__icontains=keyword) | Q(action__icontains=keyword) | Q(object_id__icontains=keyword))
    if module:
        logs = logs.filter(module=module)
    if start_date:
        logs = logs.filter(created_at__date__gte=start_date)
    if end_date:
        logs = logs.filter(created_at__date__lte=end_date)
    module_choices = OperationLog.objects.order_by("module").values_list("module", flat=True).distinct()
    return render(request, "logs.html", {
        "logs": paginate(request, logs, 15),
        "keyword": keyword,
        "selected_module": module,
        "module_choices": module_choices,
        "start_date": request.GET.get("start_date", ""),
        "end_date": request.GET.get("end_date", ""),
    })
