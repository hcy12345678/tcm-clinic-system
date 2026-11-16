import pandas as pd
from django.utils.dateparse import parse_date
from .models import Appointment


def filter_appointments(request, queryset):
    start_date = parse_date(request.GET.get("start_date", ""))
    end_date = parse_date(request.GET.get("end_date", ""))
    doctor_id = request.GET.get("doctor", "")
    status = request.GET.get("status", "")
    if start_date:
        queryset = queryset.filter(schedule__date__gte=start_date)
    if end_date:
        queryset = queryset.filter(schedule__date__lte=end_date)
    if doctor_id.isdigit():
        queryset = queryset.filter(schedule__doctor_id=doctor_id)
    if status in Appointment.Status.values:
        queryset = queryset.filter(status=status)
    return queryset


def appointment_dataframe(queryset):
    rows = queryset.values_list(
        "appointment_no",
        "patient__first_name",
        "patient__username",
        "schedule__doctor__user__first_name",
        "schedule__doctor__department",
        "schedule__date",
        "status",
        "created_at",
    )
    columns = [
        "appointment_no", "patient_name", "patient_username", "doctor_name",
        "department", "schedule_date", "status", "created_at",
    ]
    df = pd.DataFrame(list(rows), columns=[
        "appointment_no", "patient_name", "patient_username", "doctor_name",
        "department", "schedule_date", "status", "created_at",
    ])
    if df.empty:
        return pd.DataFrame(columns=columns)
    df = df.drop_duplicates(subset=["appointment_no"])
    for column in ("patient_name", "doctor_name", "department"):
        df[column] = df[column].fillna("未填写")
    df["schedule_date"] = pd.to_datetime(df["schedule_date"], errors="coerce")
    return df


def summarize_appointments(queryset):
    df = appointment_dataframe(queryset)
    status_names = dict(Appointment.Status.choices)
    if df.empty:
        trend_labels, trend_values = [], []
        status_labels, status_values = [], []
        department_labels, department_values = [], []
    else:
        trend = df.dropna(subset=["schedule_date"]).groupby(df["schedule_date"].dt.strftime("%Y-%m-%d")).size()
        trend_labels = trend.index.tolist()
        trend_values = trend.astype(int).tolist()
        status_counts = df.groupby("status").size()
        status_labels = [status_names.get(item, item) for item in status_counts.index]
        status_values = status_counts.astype(int).tolist()
        departments = df.groupby("department").size().sort_values(ascending=False)
        department_labels = departments.index.tolist()
        department_values = departments.astype(int).tolist()
    visits = queryset.filter(visit__isnull=False)
    return {
        "stats": {
            "total_appointments": len(df),
            "total_visits": visits.count(),
            "completed_visits": visits.filter(visit__status="FINISHED").count(),
            "cancelled_appointments": int((df["status"] == Appointment.Status.CANCELLED).sum()) if not df.empty else 0,
        },
        "chart_data": {
            "trend_labels": trend_labels,
            "trend_values": trend_values,
            "status_labels": status_labels,
            "status_values": status_values,
            "department_labels": department_labels,
            "department_values": department_values,
        },
        "dataframe": df,
    }
