"""前后端分离改造：JSON 接口层。

约定：
- 统一响应 {"code": 0, "message": "ok", "data": ...}
- 出错返回非 2xx，body 为 {"code": "FORBIDDEN", "message": "...", "errors": {...}}
- 认证用 Django Session + CSRF（同域部署，无需 Token）
"""

import csv
import json
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .audit import log_action
from .forms import AdminUserForm, AppointmentForm, ProfileForm, RegisterForm, ScheduleForm, VisitForm
from .models import Appointment, Doctor, OperationLog, RolePermission, Schedule, User, Visit, VisitHistory
from .statistics import filter_appointments, summarize_appointments

PAGE_SIZE = 10


# ---------------------------------------------------------------- 基础工具
def ok(data=None, status=200, **extra):
    body = {"code": 0, "message": "ok", "data": data}
    body.update(extra)
    return JsonResponse(body, status=status, json_dumps_params={"ensure_ascii": False})


def fail(message, status=400, code="BAD_REQUEST", errors=None):
    body = {"code": code, "message": message}
    if errors:
        body["errors"] = errors
    return JsonResponse(body, status=status, json_dumps_params={"ensure_ascii": False})


def payload(request):
    """兼容 JSON 与表单两种提交方式。"""
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}
    return request.POST.dict()


def form_errors(form):
    return {field: [str(err) for err in errs] for field, errs in form.errors.items()}


def first_error(errors):
    for field, messages in errors.items():
        if messages:
            label = "" if field == "__all__" else f"{field}: "
            return f"{label}{messages[0]}"
    return "提交的数据不合法。"


def paginate(queryset, request, serializer):
    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        size = min(max(int(request.GET.get("page_size", PAGE_SIZE)), 1), 100)
    except (TypeError, ValueError):
        size = PAGE_SIZE
    total = queryset.count()
    total_pages = max((total + size - 1) // size, 1)
    page = min(page, total_pages)
    start = (page - 1) * size
    items = [serializer(obj) for obj in queryset[start:start + size]]
    return {"count": total, "page": page, "page_size": size, "total_pages": total_pages, "results": items}


# ---------------------------------------------------------------- 权限装饰器
def api_login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return fail("登录状态已失效，请重新登录。", 401, "UNAUTHENTICATED")
        return view_func(request, *args, **kwargs)

    return wrapper


def api_perm(field):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return fail("登录状态已失效，请重新登录。", 401, "UNAUTHENTICATED")
            if request.user.role == User.Role.ADMIN:
                return view_func(request, *args, **kwargs)
            permission, _ = RolePermission.objects.get_or_create(
                role=request.user.role,
                defaults=RolePermission.defaults_for(request.user.role),
            )
            if not getattr(permission, field):
                return fail("当前角色没有访问此功能的权限。", 403, "FORBIDDEN")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def api_staff_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return fail("登录状态已失效，请重新登录。", 401, "UNAUTHENTICATED")
        if request.user.role not in (User.Role.ADMIN, User.Role.DOCTOR):
            return fail("仅医师或管理员可以执行此操作。", 403, "FORBIDDEN")
        return view_func(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------- 数据范围
def appointment_scope(user, queryset):
    if user.role == User.Role.ADMIN:
        return queryset
    if user.role == User.Role.DOCTOR and hasattr(user, "doctor_profile"):
        return queryset.filter(schedule__doctor=user.doctor_profile)
    return queryset.filter(patient=user)


def visit_scope(user, queryset):
    if user.role == User.Role.ADMIN:
        return queryset
    if user.role == User.Role.DOCTOR and hasattr(user, "doctor_profile"):
        return queryset.filter(appointment__schedule__doctor=user.doctor_profile)
    return queryset.filter(appointment__patient=user)


def own_doctor(user):
    return getattr(user, "doctor_profile", None) if user.role == User.Role.DOCTOR else None


# ---------------------------------------------------------------- 序列化
def serialize_user(user):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "first_name": user.first_name,
        "role": user.role,
        "role_display": user.get_role_display(),
        "phone": user.phone,
        "gender": user.gender,
        "gender_display": user.get_gender_display() if user.gender else "",
        "birth_date": user.birth_date.isoformat() if user.birth_date else "",
        "email": user.email,
        "address": user.address,
        "is_active": user.is_active,
        "date_joined": user.date_joined.strftime("%Y-%m-%d %H:%M"),
    }


def serialize_doctor(doctor):
    return {
        "id": doctor.id,
        "employee_no": doctor.employee_no,
        "name": doctor.user.display_name,
        "department": doctor.department,
        "title": doctor.title,
        "specialty": doctor.specialty,
        "is_active": doctor.is_active,
    }


def serialize_schedule(schedule):
    return {
        "id": schedule.id,
        "doctor_id": schedule.doctor_id,
        "doctor_name": schedule.doctor.user.display_name,
        "department": schedule.doctor.department,
        "employee_no": schedule.doctor.employee_no,
        "date": schedule.date.isoformat(),
        "start_time": schedule.start_time.strftime("%H:%M"),
        "end_time": schedule.end_time.strftime("%H:%M"),
        "room": schedule.room,
        "total_slots": schedule.total_slots,
        "booked_slots": schedule.booked_slots,
        "remaining_slots": schedule.remaining_slots,
        "status": schedule.status,
        "status_display": schedule.get_status_display(),
    }


def serialize_appointment(appointment):
    schedule = appointment.schedule
    return {
        "id": appointment.id,
        "appointment_no": appointment.appointment_no,
        "patient_id": appointment.patient_id,
        "patient_name": appointment.patient.display_name,
        "patient_username": appointment.patient.username,
        "patient_phone": appointment.patient.phone,
        "symptoms": appointment.symptoms,
        "status": appointment.status,
        "status_display": appointment.get_status_display(),
        "created_at": appointment.created_at.strftime("%Y-%m-%d %H:%M"),
        "schedule": serialize_schedule(schedule),
        "has_visit": hasattr(appointment, "visit"),
        "visit_id": appointment.visit.id if hasattr(appointment, "visit") else None,
    }


def serialize_visit(visit):
    appointment = visit.appointment
    return {
        "id": visit.id,
        "appointment_id": appointment.id,
        "appointment_no": appointment.appointment_no,
        "patient_name": appointment.patient.display_name,
        "doctor_name": appointment.schedule.doctor.user.display_name,
        "department": appointment.schedule.doctor.department,
        "schedule_date": appointment.schedule.date.isoformat(),
        "visit_time": visit.visit_time.strftime("%Y-%m-%d %H:%M"),
        "diagnosis": visit.diagnosis,
        "treatment": visit.treatment,
        "prescription": visit.prescription,
        "status": visit.status,
        "status_display": visit.get_status_display(),
        "note": visit.note,
        "attachment": visit.attachment.url if visit.attachment else "",
        "operator": visit.operator.display_name,
        "created_at": visit.created_at.strftime("%Y-%m-%d %H:%M"),
        "updated_at": visit.updated_at.strftime("%Y-%m-%d %H:%M"),
        "histories": [
            {
                "action": item.action,
                "note": item.note,
                "operator": item.operator.display_name,
                "created_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
            }
            for item in visit.histories.all()[:20]
        ],
    }


def serialize_log(log):
    return {
        "id": log.id,
        "operator": log.operator.display_name if log.operator else "已删除用户",
        "module": log.module,
        "action": log.action,
        "object_id": log.object_id,
        "detail": log.detail,
        "ip_address": log.ip_address or "-",
        "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------------------------------------------------------------- 认证
@require_http_methods(["GET"])
@ensure_csrf_cookie
def auth_me(request):
    """前端启动时调用：拿到 CSRF token、当前用户与菜单权限。"""
    if not request.user.is_authenticated:
        return ok({"authenticated": False, "csrf_token": get_token(request)})

    permission, _ = RolePermission.objects.get_or_create(
        role=request.user.role,
        defaults=RolePermission.defaults_for(request.user.role),
    )
    perms = {
        "can_user": permission.can_user or request.user.role == User.Role.ADMIN,
        "can_schedule": permission.can_schedule or request.user.role == User.Role.ADMIN,
        "can_appointment": permission.can_appointment or request.user.role == User.Role.ADMIN,
        "can_visit": permission.can_visit or request.user.role == User.Role.ADMIN,
        "can_statistics": permission.can_statistics or request.user.role == User.Role.ADMIN,
    }
    return ok({
        "authenticated": True,
        "csrf_token": get_token(request),
        "user": serialize_user(request.user),
        "perms": perms,
    })


@require_http_methods(["POST"])
def auth_login(request):
    data = payload(request)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return fail("请输入账号和密码。")
    user = authenticate(request, username=username, password=password)
    if user is None:
        return fail("账号或密码不正确。", 401, "UNAUTHENTICATED")
    if not user.is_active:
        return fail("该账号已被停用。", 403, "FORBIDDEN")
    login(request, user)
    log_action(request, "用户", "登录系统", user.username)
    permission, _ = RolePermission.objects.get_or_create(
        role=user.role, defaults=RolePermission.defaults_for(user.role)
    )
    return ok({
        "user": serialize_user(user),
        "perms": {
            "can_user": permission.can_user or user.role == User.Role.ADMIN,
            "can_schedule": permission.can_schedule or user.role == User.Role.ADMIN,
            "can_appointment": permission.can_appointment or user.role == User.Role.ADMIN,
            "can_visit": permission.can_visit or user.role == User.Role.ADMIN,
            "can_statistics": permission.can_statistics or user.role == User.Role.ADMIN,
        },
        "csrf_token": get_token(request),
    })


@require_http_methods(["POST"])
@api_login_required
def auth_logout(request):
    log_action(request, "用户", "退出登录", request.user.username)
    logout(request)
    return ok()


@require_http_methods(["POST"])
def auth_register(request):
    data = payload(request)
    form = RegisterForm(data)
    if not form.is_valid():
        errors = form_errors(form)
        return fail(first_error(errors), 400, "VALIDATION_ERROR", errors)
    user = form.save()
    login(request, user)
    log_action(request, "用户", "注册账号", user.username)
    return ok({"user": serialize_user(user)})


@require_http_methods(["GET", "POST"])
@api_login_required
def auth_profile(request):
    if request.method == "GET":
        return ok(serialize_user(request.user))
    data = payload(request)
    form = ProfileForm(data, instance=request.user)
    if not form.is_valid():
        errors = form_errors(form)
        return fail(first_error(errors), 400, "VALIDATION_ERROR", errors)
    form.save()
    log_action(request, "用户", "修改个人资料", request.user.username)
    return ok(serialize_user(request.user))


# ---------------------------------------------------------------- 工作台
@require_http_methods(["GET"])
@api_login_required
def dashboard(request):
    today = timezone.localdate()
    appointments = appointment_scope(request.user, Appointment.objects.all())
    visits = visit_scope(request.user, Visit.objects.all())
    schedule_qs = Schedule.objects.all()
    if request.user.role == User.Role.DOCTOR and own_doctor(request.user):
        schedule_qs = schedule_qs.filter(doctor=own_doctor(request.user))

    cards = [
        {"key": "today_appointments", "label": "今日预约", "value": appointments.filter(schedule__date=today).count()},
        {"key": "pending_visits", "label": "待接诊", "value": visits.filter(status=Visit.Status.PENDING).count()},
        {"key": "today_schedules", "label": "今日排班", "value": schedule_qs.filter(date=today).count()},
        {"key": "active_doctors", "label": "出诊医师", "value": Doctor.objects.filter(is_active=True).count()},
    ]
    upcoming = schedule_qs.filter(date__gte=today).order_by("date", "start_time")[:5]
    recent = appointments.select_related("patient", "schedule__doctor__user").order_by("-created_at")[:6]
    return ok({
        "cards": cards,
        "upcoming_schedules": [serialize_schedule(item) for item in upcoming],
        "recent_appointments": [serialize_appointment(item) for item in recent],
        "today": today.isoformat(),
    })


# ---------------------------------------------------------------- 用户管理
@require_http_methods(["GET"])
@api_perm("can_user")
def user_list(request):
    queryset = User.objects.all().order_by("-date_joined")
    keyword = (request.GET.get("keyword") or "").strip()
    role = request.GET.get("role") or ""
    if keyword:
        queryset = queryset.filter(
            Q(username__icontains=keyword) | Q(first_name__icontains=keyword) | Q(phone__icontains=keyword)
        )
    if role in User.Role.values:
        queryset = queryset.filter(role=role)
    return ok(paginate(queryset, request, serialize_user))


@require_http_methods(["GET", "PUT"])
@api_perm("can_user")
def user_detail(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == "GET":
        return ok(serialize_user(user))
    data = payload(request)
    form = AdminUserForm(data, instance=user)
    if not form.is_valid():
        errors = form_errors(form)
        return fail(first_error(errors), 400, "VALIDATION_ERROR", errors)
    form.save()
    log_action(request, "用户", "编辑用户资料", user.username)
    return ok(serialize_user(user))


@require_http_methods(["GET", "POST"])
@api_perm("can_user")
def permissions(request):
    if request.method == "GET":
        rows = []
        for role_value, role_label in User.Role.choices:
            permission, _ = RolePermission.objects.get_or_create(
                role=role_value, defaults=RolePermission.defaults_for(role_value)
            )
            rows.append({
                "role": role_value,
                "role_display": role_label,
                "can_user": permission.can_user,
                "can_schedule": permission.can_schedule,
                "can_appointment": permission.can_appointment,
                "can_visit": permission.can_visit,
                "can_statistics": permission.can_statistics,
            })
        return ok({"roles": rows})

    data = payload(request)
    rows = data.get("roles") or []
    saved = 0
    for row in rows:
        role_value = row.get("role")
        if role_value not in User.Role.values:
            continue
        RolePermission.objects.update_or_create(
            role=role_value,
            defaults={
                "can_user": bool(row.get("can_user")),
                "can_schedule": bool(row.get("can_schedule")),
                "can_appointment": bool(row.get("can_appointment")),
                "can_visit": bool(row.get("can_visit")),
                "can_statistics": bool(row.get("can_statistics")),
            },
        )
        saved += 1
    log_action(request, "用户", "更新角色菜单权限", f"{saved} 个角色")
    return ok({"saved": saved})


# ---------------------------------------------------------------- 医师
@require_http_methods(["GET"])
@api_login_required
def doctor_list(request):
    queryset = Doctor.objects.filter(is_active=True).select_related("user").order_by("employee_no")
    return ok([serialize_doctor(item) for item in queryset])


# ---------------------------------------------------------------- 排班
@require_http_methods(["GET", "POST"])
@api_perm("can_schedule")
def schedule_list(request):
    if request.method == "GET":
        queryset = Schedule.objects.select_related("doctor__user").all()
        keyword = (request.GET.get("keyword") or "").strip()
        doctor_id = request.GET.get("doctor") or ""
        status = request.GET.get("status") or ""
        start_date = parse_date(request.GET.get("start_date") or "")
        end_date = parse_date(request.GET.get("end_date") or "")
        if keyword:
            queryset = queryset.filter(
                Q(doctor__user__first_name__icontains=keyword)
                | Q(doctor__user__username__icontains=keyword)
                | Q(doctor__department__icontains=keyword)
                | Q(room__icontains=keyword)
            )
        if doctor_id.isdigit():
            queryset = queryset.filter(doctor_id=doctor_id)
        if status in Schedule.Status.values:
            queryset = queryset.filter(status=status)
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        return ok(paginate(queryset.order_by("-date", "start_time"), request, serialize_schedule))

    if request.user.role == User.Role.PATIENT:
        return fail("患者只能查看排班，不能新增。", 403, "FORBIDDEN")

    data = dict(payload(request))
    doctor = own_doctor(request.user)
    if request.user.role == User.Role.DOCTOR:
        if not doctor:
            return fail("当前账号尚未建立医师档案，无法排班。", 403, "NO_DOCTOR_PROFILE")
        # 医师只能给自己排班，忽略前端传入的医师
        data["doctor"] = doctor.id
    form = ScheduleForm(data)
    if not form.is_valid():
        errors = form_errors(form)
        return fail(first_error(errors), 400, "VALIDATION_ERROR", errors)
    schedule = form.save()
    log_action(request, "排班", "新增排班", schedule.id, str(schedule))
    return ok(serialize_schedule(schedule), status=201)


@require_http_methods(["GET", "PUT", "DELETE"])
@api_perm("can_schedule")
def schedule_detail(request, pk):
    schedule = get_object_or_404(Schedule.objects.select_related("doctor__user"), pk=pk)
    if request.method == "GET":
        return ok(serialize_schedule(schedule))

    if not _can_touch_schedule(request.user, schedule):
        return fail("只能操作本人的排班。", 403, "FORBIDDEN")

    if request.method == "DELETE":
        if schedule.appointments.exists():
            return fail("该排班已有预约记录，不能删除，可改为「暂停预约」。", 400, "HAS_APPOINTMENTS")
        log_action(request, "排班", "删除排班", schedule.id, str(schedule))
        schedule.delete()
        return ok()

    data = dict(payload(request))
    doctor = own_doctor(request.user)
    if request.user.role == User.Role.DOCTOR:
        # 医师不能把排班改到别人名下
        data["doctor"] = doctor.id if doctor else schedule.doctor_id
    form = ScheduleForm(data, instance=schedule)
    if not form.is_valid():
        errors = form_errors(form)
        return fail(first_error(errors), 400, "VALIDATION_ERROR", errors)
    schedule = form.save()
    log_action(request, "排班", "编辑排班", schedule.id, str(schedule))
    return ok(serialize_schedule(schedule))


def _can_touch_schedule(user, schedule):
    if user.role == User.Role.ADMIN:
        return True
    doctor = own_doctor(user)
    return bool(doctor and schedule.doctor_id == doctor.id)


# ---------------------------------------------------------------- 预约
@require_http_methods(["GET", "POST"])
@api_perm("can_appointment")
def appointment_list(request):
    if request.method == "GET":
        queryset = appointment_scope(
            request.user,
            Appointment.objects.select_related("patient", "schedule__doctor__user"),
        ).order_by("-created_at")
        keyword = (request.GET.get("keyword") or "").strip()
        status = request.GET.get("status") or ""
        doctor_id = request.GET.get("doctor") or ""
        start_date = parse_date(request.GET.get("start_date") or "")
        end_date = parse_date(request.GET.get("end_date") or "")
        if keyword:
            queryset = queryset.filter(
                Q(appointment_no__icontains=keyword)
                | Q(patient__first_name__icontains=keyword)
                | Q(patient__username__icontains=keyword)
                | Q(schedule__doctor__user__first_name__icontains=keyword)
            )
        if status in Appointment.Status.values:
            queryset = queryset.filter(status=status)
        if doctor_id.isdigit():
            queryset = queryset.filter(schedule__doctor_id=doctor_id)
        if start_date:
            queryset = queryset.filter(schedule__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(schedule__date__lte=end_date)
        return ok(paginate(queryset, request, serialize_appointment))

    data = dict(payload(request))
    if request.user.role == User.Role.PATIENT:
        data["patient"] = request.user.id
        data.pop("status", None)
    form = AppointmentForm(data, user=request.user)
    if not form.is_valid():
        errors = form_errors(form)
        return fail(first_error(errors), 400, "VALIDATION_ERROR", errors)
    appointment = form.save(commit=False)
    try:
        appointment.full_clean()
    except ValidationError as exc:
        return fail("；".join(exc.messages), 400, "VALIDATION_ERROR")
    appointment.save()
    log_action(request, "预约", "创建预约", appointment.appointment_no, appointment.appointment_no)
    return ok(serialize_appointment(appointment), status=201)


@require_http_methods(["GET", "PUT"])
@api_perm("can_appointment")
def appointment_detail(request, pk):
    queryset = appointment_scope(
        request.user,
        Appointment.objects.select_related("patient", "schedule__doctor__user"),
    )
    appointment = get_object_or_404(queryset, pk=pk)
    if request.method == "GET":
        return ok(serialize_appointment(appointment))

    if appointment.status == Appointment.Status.CANCELLED:
        return fail("已取消的预约不能修改。", 400, "INVALID_STATUS")
    data = dict(payload(request))
    if request.user.role == User.Role.PATIENT:
        data["patient"] = request.user.id
        data.pop("status", None)
    form = AppointmentForm(data, instance=appointment, user=request.user)
    if not form.is_valid():
        errors = form_errors(form)
        return fail(first_error(errors), 400, "VALIDATION_ERROR", errors)
    appointment = form.save()
    log_action(request, "预约", "修改预约", appointment.appointment_no, appointment.appointment_no)
    return ok(serialize_appointment(appointment))


@require_http_methods(["POST"])
@api_perm("can_appointment")
def appointment_cancel(request, pk):
    queryset = appointment_scope(request.user, Appointment.objects.all())
    appointment = get_object_or_404(queryset, pk=pk)
    if appointment.status != Appointment.Status.BOOKED:
        return fail("只有「已预约」状态可以取消。", 400, "INVALID_STATUS")
    if hasattr(appointment, "visit"):
        return fail("该预约已产生就诊记录，不能取消。", 400, "HAS_VISIT")
    appointment.status = Appointment.Status.CANCELLED
    appointment.save(update_fields=["status", "updated_at"])
    log_action(request, "预约", "取消预约", appointment.appointment_no, appointment.appointment_no)
    return ok(serialize_appointment(appointment))


@require_http_methods(["GET"])
@api_perm("can_appointment")
def appointment_options(request):
    schedules = Schedule.objects.filter(
        status=Schedule.Status.OPEN, date__gte=timezone.localdate()
    ).select_related("doctor__user").order_by("date", "start_time")
    if request.user.role == User.Role.DOCTOR and own_doctor(request.user):
        schedules = schedules.filter(doctor=own_doctor(request.user))

    patients = User.objects.filter(role=User.Role.PATIENT, is_active=True).order_by("username")
    options = [
        {
            "value": item.id,
            "label": f"{item.date} {item.start_time:%H:%M}｜{item.doctor.user.display_name}｜余号 {item.remaining_slots}",
            "remaining_slots": item.remaining_slots,
        }
        for item in schedules
    ]
    return ok({
        "schedules": options,
        "patients": [{"value": item.id, "label": f"{item.display_name}（{item.username}）"} for item in patients],
        "statuses": [{"value": value, "label": label} for value, label in Appointment.Status.choices],
    })


# ---------------------------------------------------------------- 就诊
@require_http_methods(["GET", "POST"])
@api_perm("can_visit")
def visit_list(request):
    if request.method == "GET":
        queryset = visit_scope(
            request.user,
            Visit.objects.select_related(
                "appointment__patient", "appointment__schedule__doctor__user", "operator"
            ),
        ).order_by("-updated_at")
        keyword = (request.GET.get("keyword") or "").strip()
        status = request.GET.get("status") or ""
        if keyword:
            queryset = queryset.filter(
                Q(appointment__appointment_no__icontains=keyword)
                | Q(appointment__patient__first_name__icontains=keyword)
                | Q(diagnosis__icontains=keyword)
            )
        if status in Visit.Status.values:
            queryset = queryset.filter(status=status)
        return ok(paginate(queryset, request, serialize_visit))

    if request.user.role not in (User.Role.ADMIN, User.Role.DOCTOR):
        return fail("仅医师或管理员可以登记就诊。", 403, "FORBIDDEN")
    form = VisitForm(request.POST, request.FILES, user=request.user)
    if not form.is_valid():
        errors = form_errors(form)
        return fail(first_error(errors), 400, "VALIDATION_ERROR", errors)
    visit = form.save(commit=False)
    visit.operator = request.user
    visit.save()
    VisitHistory.objects.create(
        visit=visit,
        action="登记就诊",
        note=form.cleaned_data.get("history_note") or "创建就诊记录",
        operator=request.user,
    )
    log_action(request, "就诊", "登记就诊", visit.id, visit.appointment.appointment_no)
    return ok(serialize_visit(visit), status=201)


@require_http_methods(["GET", "POST"])
@api_perm("can_visit")
def visit_detail(request, pk):
    queryset = visit_scope(
        request.user,
        Visit.objects.select_related(
            "appointment__patient", "appointment__schedule__doctor__user", "operator"
        ),
    )
    visit = get_object_or_404(queryset, pk=pk)
    if request.method == "GET":
        return ok(serialize_visit(visit))

    if request.user.role not in (User.Role.ADMIN, User.Role.DOCTOR):
        return fail("仅医师或管理员可以修改就诊记录。", 403, "FORBIDDEN")
    previous_status = visit.status
    post_data = request.POST.copy()
    if not post_data.get("appointment"):
        post_data["appointment"] = visit.appointment_id
    form = VisitForm(post_data, request.FILES or None, instance=visit, user=request.user)
    if not form.is_valid():
        errors = form_errors(form)
        return fail(first_error(errors), 400, "VALIDATION_ERROR", errors)
    visit = form.save(commit=False)
    visit.operator = request.user
    visit.save()

    if previous_status != visit.status:
        VisitHistory.objects.create(
            visit=visit,
            action=f"状态更新为{visit.get_status_display()}",
            note=form.cleaned_data.get("history_note") or "",
            operator=request.user,
        )

    appointment = visit.appointment
    if visit.status == Visit.Status.FINISHED:
        appointment.status = Appointment.Status.COMPLETED
    elif appointment.status == Appointment.Status.COMPLETED:
        appointment.status = Appointment.Status.BOOKED
    appointment.save(update_fields=["status", "updated_at"])

    log_action(request, "就诊", "更新就诊记录", visit.id, appointment.appointment_no)
    return ok(serialize_visit(visit))


@require_http_methods(["GET"])
@api_perm("can_visit")
def visit_options(request):
    queryset = Appointment.objects.filter(
        status=Appointment.Status.BOOKED, visit__isnull=True
    ).select_related("patient", "schedule__doctor__user")
    if request.user.role == User.Role.DOCTOR and own_doctor(request.user):
        queryset = queryset.filter(schedule__doctor=own_doctor(request.user))
    return ok({
        "appointments": [
            {
                "value": item.id,
                "label": f"{item.appointment_no}｜{item.patient.display_name}｜{item.schedule.doctor.user.display_name}",
            }
            for item in queryset.order_by("-created_at")
        ],
        "statuses": [{"value": value, "label": label} for value, label in Visit.Status.choices],
    })


# ---------------------------------------------------------------- 统计与日志
@require_http_methods(["GET"])
@api_perm("can_statistics")
def statistics(request):
    queryset = filter_appointments(
        request,
        appointment_scope(
            request.user,
            Appointment.objects.select_related("patient", "schedule__doctor__user"),
        ),
    )
    summary = summarize_appointments(queryset)
    records = [
        {
            "appointment_no": item.appointment_no,
            "patient_name": item.patient.display_name,
            "doctor_name": item.schedule.doctor.user.display_name,
            "department": item.schedule.doctor.department or "-",
            "date": item.schedule.date.isoformat(),
            "status": item.status,
            "status_display": item.get_status_display(),
            "created_at": item.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for item in queryset.order_by("-created_at")[:20]
    ]
    return ok({
        "stats": summary["stats"],
        "chart_data": summary["chart_data"],
        "records": records,
        "doctors": [serialize_doctor(item) for item in Doctor.objects.filter(is_active=True).select_related("user")],
        "statuses": [{"value": value, "label": label} for value, label in Appointment.Status.choices],
    })


@require_http_methods(["GET"])
@api_perm("can_statistics")
def export_appointments(request):
    queryset = filter_appointments(
        request,
        appointment_scope(
            request.user,
            Appointment.objects.select_related("patient", "schedule__doctor__user"),
        ),
    )
    summary = summarize_appointments(queryset)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"appointments_{timezone.now():%Y%m%d%H%M}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["预约编号", "患者", "医师", "科室", "就诊日期", "状态", "预约时间"])
    status_names = dict(Appointment.Status.choices)
    for _, row in summary["dataframe"].iterrows():
        writer.writerow([
            row["appointment_no"],
            row["patient_name"] or row["patient_username"],
            row["doctor_name"],
            row["department"],
            row["schedule_date"].strftime("%Y-%m-%d") if row["schedule_date"] is not None and str(row["schedule_date"]) != "NaT" else "",
            status_names.get(row["status"], row["status"]),
            row["created_at"].strftime("%Y-%m-%d %H:%M") if row["created_at"] else "",
        ])
    log_action(request, "统计", "导出预约数据", filename)
    return response


@require_http_methods(["GET"])
@api_perm("can_statistics")
def operation_logs(request):
    if request.user.role != User.Role.ADMIN:
        return fail("操作日志仅管理员可查看。", 403, "FORBIDDEN")
    queryset = OperationLog.objects.select_related("operator").all()
    module = (request.GET.get("module") or "").strip()
    keyword = (request.GET.get("keyword") or "").strip()
    start_date = parse_date(request.GET.get("start_date") or "")
    end_date = parse_date(request.GET.get("end_date") or "")
    if module:
        queryset = queryset.filter(module=module)
    if keyword:
        queryset = queryset.filter(
            Q(action__icontains=keyword)
            | Q(detail__icontains=keyword)
            | Q(object_id__icontains=keyword)
            | Q(operator__first_name__icontains=keyword)
            | Q(operator__username__icontains=keyword)
        )
    if start_date:
        queryset = queryset.filter(created_at__date__gte=start_date)
    if end_date:
        queryset = queryset.filter(created_at__date__lte=end_date)
    data = paginate(queryset.order_by("-created_at"), request, serialize_log)
    data["modules"] = list(
        OperationLog.objects.values_list("module", flat=True).distinct().order_by("module")
    )
    return ok(data)
