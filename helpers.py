import datetime as dt
import os
import secrets
from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user
from database import db
from models import (
    User, Course, Schedule, Enrollment, Attendance,
    TeacherPayroll, TeachingRecord, TuitionPayment, ExamSubmission
)

# ──────────────────────── CONFIG GLOBALS ────────────────────────

WEEKDAYS = [
    (0, "Thứ 2"),
    (1, "Thứ 3"),
    (2, "Thứ 4"),
    (3, "Thứ 5"),
    (4, "Thứ 6"),
    (5, "Thứ 7"),
    (6, "Chủ nhật"),
]
STATUS_LABELS = {"present": "Có mặt", "absent": "Vắng", "late": "Đi trễ"}
TUITION_LABELS = {"monthly": "Theo tháng", "full_course": "Trọn khóa"}
ROLE_LABELS = {
    "admin": "Admin",
    "manager": "Quản lý",
    "teacher": "Giáo viên",
    "student": "Học sinh",
    "parent": "Phụ huynh"
}
SUBJECT_COLORS = [
    "#4f46e5", "#0891b2", "#059669", "#d97706", "#dc2626",
    "#7c3aed", "#db2777", "#0d9488", "#ca8a04", "#2563eb",
    "#9333ea", "#e11d48",
]

# ──────────────────────── HELPERS & DECORATORS ────────────────────────

def save_picture(form_picture, folder_path):
    random_hex = secrets.token_hex(8)
    _, file_ext = os.path.splitext(form_picture.filename)
    picture_name = random_hex + file_ext
    form_picture.save(os.path.join(folder_path, picture_name))
    return picture_name


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            if current_user.role == "admin" or current_user.role in allowed_roles:
                return view(*args, **kwargs)
            flash("Bạn không có quyền truy cập trang này.", "danger")
            return redirect(url_for("index"))

        return wrapped

    return decorator


def manager_or_admin_required(view):
    return role_required("admin", "manager")(view)


def teacher_manager_admin_required(view):
    return role_required("admin", "manager", "teacher")(view)


def parse_date(value):
    return dt.datetime.strptime(value, "%Y-%m-%d").date() if value else None


def parse_time(value):
    return dt.datetime.strptime(value, "%H:%M").time()


def money(value):
    return int(value or 0)


def duration_hours(start_time, end_time):
    today = dt.date.today()
    start = dt.datetime.combine(today, start_time)
    end = dt.datetime.combine(today, end_time)
    return round((end - start).total_seconds() / 3600, 2)


def resolve_student_id(val):
    if not val:
        return None
    # 1. Try to treat val as integer ID
    try:
        val_int = int(val)
        user = db.session.get(User, val_int)
        if user and user.role == "student":
            return user.id
    except ValueError:
        pass

    # 2. Try to look up by username (case-insensitive) or user_code (case-insensitive)
    user = User.query.filter(
        (User.role == "student") &
        ((User.username == val.lower()) | (User.user_code == val.upper()) | (User.user_code == val) | (User.username == val))
    ).first()
    if user:
        return user.id

    return None


def month_key(date_value=None):
    return (date_value or dt.date.today()).strftime("%Y-%m")


def week_bounds(date_value=None):
    anchor = date_value or dt.date.today()
    start = anchor - dt.timedelta(days=anchor.weekday())
    return start, start + dt.timedelta(days=6)


def month_bounds(month_value=None):
    start = dt.datetime.strptime(month_value + "-01", "%Y-%m-%d").date() if month_value else dt.date.today().replace(day=1)
    next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return start, next_month - dt.timedelta(days=1)


def get_accessible_student_ids():
    if current_user.role in ("admin", "manager"):
        return [user.id for user in User.query.filter_by(role="student").all()]
    if current_user.role == "student":
        return [current_user.id]
    if current_user.role == "parent" and current_user.linked_student_id:
        return [current_user.linked_student_id]
    return []


def schedules_for_user(user):
    if user.role in ("admin", "manager"):
        return Schedule.query.order_by(Schedule.weekday, Schedule.start_time).all()
    if user.role == "teacher":
        return Schedule.query.filter_by(teacher_id=user.id).order_by(Schedule.weekday, Schedule.start_time).all()
    student_id = user.id if user.role == "student" else user.linked_student_id
    course_ids = [enrollment.course_id for enrollment in Enrollment.query.filter_by(student_id=student_id, status="active").all()]
    if not course_ids:
        return []
    return Schedule.query.filter(Schedule.course_id.in_(course_ids)).order_by(Schedule.weekday, Schedule.start_time).all()


def schedule_occurrences(schedules, start_date, end_date):
    rows = []
    current = start_date
    while current <= end_date:
        for schedule in schedules:
            if schedule.weekday == current.weekday():
                rows.append({"date": current, "schedule": schedule})
        current += dt.timedelta(days=1)
    return sorted(rows, key=lambda row: (row["date"], row["schedule"].start_time))


def students_for_teacher(teacher_id):
    return (
        User.query.join(Enrollment, Enrollment.student_id == User.id)
        .join(Course, Course.id == Enrollment.course_id)
        .filter(Course.teacher_id == teacher_id, Enrollment.status == "active", User.role == "student")
        .distinct()
        .order_by(User.fullname)
        .all()
    )


def matching_schedule(course, class_date):
    return (
        Schedule.query.filter_by(course_id=course.id, teacher_id=course.teacher_id, weekday=class_date.weekday())
        .order_by(Schedule.start_time)
        .first()
    ) or Schedule.query.filter_by(course_id=course.id, teacher_id=course.teacher_id).order_by(Schedule.start_time).first()


def rebuild_payroll_month(teacher_id, month):
    start, end = month_bounds(month)
    records = TeachingRecord.query.filter(
        TeachingRecord.teacher_id == teacher_id,
        TeachingRecord.date >= start,
        TeachingRecord.date <= end,
    ).all()
    payroll = TeacherPayroll.query.filter_by(teacher_id=teacher_id, month=month).first()
    if not payroll:
        payroll = TeacherPayroll(teacher_id=teacher_id, month=month)
        db.session.add(payroll)
    payroll.total_classes = len(records)
    payroll.total_hours = round(sum((record.hours_taught or 0.0) for record in records), 2)
    payroll.salary_amount = int(sum((record.amount_earned or 0) for record in records))
    payroll.calculated_at = dt.datetime.utcnow()
    return payroll


def sync_teaching_record(course, class_date):
    teacher = db.session.get(User, course.teacher_id) if course.teacher_id else None
    if not teacher:
        return None

    present_count = Attendance.query.filter_by(course_id=course.id, date=class_date, status="present").count()
    existing = TeachingRecord.query.filter_by(teacher_id=teacher.id, course_id=course.id, date=class_date).first()
    if present_count == 0:
        if existing:
            db.session.delete(existing)
        rebuild_payroll_month(teacher.id, month_key(class_date))
        return None

    schedule = matching_schedule(course, class_date)
    if not schedule:
        return None

    record = existing or TeachingRecord(teacher_id=teacher.id, course_id=course.id, date=class_date)
    record.classroom = schedule.classroom or course.classroom or ""
    record.start_time = schedule.start_time
    record.end_time = schedule.end_time
    record.hours_taught = schedule.duration_hours
    record.hourly_rate = teacher.salary_rate_per_hour or 0
    record.amount_earned = int((record.hours_taught or 0.0) * (record.hourly_rate or 0))
    db.session.add(record)
    rebuild_payroll_month(teacher.id, month_key(class_date))
    return record


def teaching_summary(teacher_id, start_date=None, end_date=None):
    query = TeachingRecord.query.filter_by(teacher_id=teacher_id)
    if start_date:
        query = query.filter(TeachingRecord.date >= start_date)
    if end_date:
        query = query.filter(TeachingRecord.date <= end_date)
    records = query.all()
    
    total_classes = len(records)
    total_hours = round(sum((record.hours_taught or 0.0) for record in records), 2)
    
    confirmed = sum(1 for r in records if r.confirmed_by_teacher)
    confirmed_hours = round(sum((r.hours_taught or 0.0) for r in records if r.confirmed_by_teacher), 2)
    confirmed_salary = int(sum((r.amount_earned or 0) for r in records if r.confirmed_by_teacher))
    
    unconfirmed = total_classes - confirmed
    return {
        "total_classes": total_classes,
        "total_hours": total_hours,
        "salary": confirmed_salary,
        "confirmed": confirmed,
        "confirmed_hours": confirmed_hours,
        "unconfirmed": unconfirmed
    }


def teacher_dashboard_data(teacher):
    today = dt.date.today()
    week_start, week_end = week_bounds(today)
    month_start, month_end = month_bounds()
    own_courses = Course.query.filter_by(teacher_id=teacher.id).order_by(Course.course_name).all()
    own_students = students_for_teacher(teacher.id)
    own_schedules = schedules_for_user(teacher)
    week_occurrences = schedule_occurrences(own_schedules, week_start, week_end)
    upcoming = [row for row in schedule_occurrences(own_schedules, today, today + dt.timedelta(days=14)) if row["date"] >= today][:8]
    week_summary = teaching_summary(teacher.id, week_start, week_end)
    month_summary = teaching_summary(teacher.id, month_start, month_end)
    total_summary = teaching_summary(teacher.id)
    return {
        "assigned_classes": len(own_courses),
        "student_count": len(own_students),
        "classes_this_week": len({row["schedule"].course_id for row in week_occurrences}),
        "sessions_scheduled_this_week": len(week_occurrences),
        "sessions_completed": total_summary["total_classes"],
        "teaching_hours_week": week_summary["total_hours"],
        "teaching_hours_month": month_summary["total_hours"],
        "total_teaching_hours": total_summary["total_hours"],
        "current_month_salary": month_summary["salary"],
        "upcoming_classes": upcoming,
    }


def student_dashboard_data(student):
    today = dt.date.today()
    week_start, week_end = week_bounds(today)
    enrollments = Enrollment.query.filter_by(student_id=student.id, status="active").all()
    course_ids = [e.course_id for e in enrollments]
    courses = Course.query.filter(Course.id.in_(course_ids)).all() if course_ids else []
    schedules = schedules_for_user(student)
    upcoming = [row for row in schedule_occurrences(schedules, today, today + dt.timedelta(days=14)) if row["date"] >= today][:8]
    attendance_records = Attendance.query.filter(
        Attendance.student_id == student.id,
        Attendance.date >= today - dt.timedelta(days=30),
    ).order_by(Attendance.date.desc()).limit(20).all()
    total_att = Attendance.query.filter_by(student_id=student.id).count()
    present_att = Attendance.query.filter_by(student_id=student.id, status="present").count()
    payments = TuitionPayment.query.filter_by(student_id=student.id).order_by(TuitionPayment.payment_date.desc()).limit(5).all()
    exams_taken = ExamSubmission.query.filter_by(student_id=student.id, is_graded=True).count()
    return {
        "courses": courses,
        "course_count": len(courses),
        "upcoming_classes": upcoming,
        "attendance_records": attendance_records,
        "attendance_rate": round(present_att / total_att * 100, 1) if total_att > 0 else 100,
        "total_attendance": total_att,
        "payments": payments,
        "exams_taken": exams_taken,
    }


def current_month_summary(teacher_id):
    return teaching_summary(teacher_id, dt.date.today().replace(day=1), dt.date.today())


def build_timetable_grid(schedules_list, start_date, end_date):
    """Build a grid structure for university-style timetable display."""
    time_slots = []
    hour = 7
    while hour < 22:
        time_slots.append(dt.time(hour, 0))
        hour += 1

    weekday_columns = []
    current = start_date
    while current <= end_date:
        weekday_columns.append(current)
        current += dt.timedelta(days=1)

    grid = {}
    color_map = {}
    color_idx = 0
    for s in schedules_list:
        course_key = s.course_id
        if course_key not in color_map:
            color_map[course_key] = SUBJECT_COLORS[color_idx % len(SUBJECT_COLORS)]
            color_idx += 1

    for day in weekday_columns:
        for s in schedules_list:
            if s.weekday == day.weekday():
                start_minutes = s.start_time.hour * 60 + s.start_time.minute
                end_minutes = s.end_time.hour * 60 + s.end_time.minute
                duration_px = end_minutes - start_minutes
                top_offset = start_minutes - 7 * 60
                grid_key = (day.isoformat(), s.id)
                grid[grid_key] = {
                    "schedule": s,
                    "top": top_offset,
                    "height": duration_px,
                    "color": color_map.get(s.course_id, "#6366f1"),
                    "day": day,
                }

    return {
        "time_slots": time_slots,
        "weekday_columns": weekday_columns,
        "grid": grid,
        "color_map": color_map,
    }


def get_course_color_map(schedules_list):
    """Assign colors to courses for timetable display."""
    color_map = {}
    idx = 0
    for s in schedules_list:
        if s.course_id not in color_map:
            color_map[s.course_id] = SUBJECT_COLORS[idx % len(SUBJECT_COLORS)]
            idx += 1
    return color_map
