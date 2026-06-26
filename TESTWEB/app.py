import datetime as dt
import json
import os
import random
import secrets
import sys
from functools import wraps

sys.stdout.reconfigure(encoding="utf-8")

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from flask_wtf.file import FileAllowed, FileField
from wtforms import DateField, PasswordField, SelectField, StringField, SubmitField, TelField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, ValidationError
from werkzeug.security import check_password_hash, generate_password_hash


basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config["SECRET_KEY"] = "khoa-bi-mat-sieu-cap-vipro-123456"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "tutoring_center.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER_AVATARS"] = os.path.join(basedir, "static", "avatars")
app.config["UPLOAD_FOLDER_COURSES"] = os.path.join(basedir, "static", "course_images")

os.makedirs(app.config["UPLOAD_FOLDER_AVATARS"], exist_ok=True)
os.makedirs(app.config["UPLOAD_FOLDER_COURSES"], exist_ok=True)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Vui lòng đăng nhập để sử dụng tính năng này."
login_manager.login_message_category = "info"


ROLES = ("admin", "manager", "teacher", "student", "parent")
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
ROLE_LABELS = {"admin": "Admin", "manager": "Quản lý", "teacher": "Giáo viên", "student": "Học sinh", "parent": "Phụ huynh"}
SUBJECT_COLORS = [
    "#4f46e5", "#0891b2", "#059669", "#d97706", "#dc2626",
    "#7c3aed", "#db2777", "#0d9488", "#ca8a04", "#2563eb",
    "#9333ea", "#e11d48",
]


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ──────────────────────── MODELS ────────────────────────

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    fullname = db.Column(db.String(100), nullable=False)
    user_code = db.Column(db.String(20), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")
    phone = db.Column(db.String(20))
    parent_phone = db.Column(db.String(20))
    birth_date = db.Column(db.Date)
    position = db.Column(db.String(100))
    password_hash = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    avatar = db.Column(db.String(100), default="default.jpg")
    salary_rate_per_hour = db.Column(db.Integer, default=0)
    linked_student_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    linked_student = db.relationship("User", remote_side=[id], uselist=False)
    courses_taught = db.relationship("Course", back_populates="teacher", foreign_keys="Course.teacher_id")
    schedules = db.relationship("Schedule", back_populates="teacher", foreign_keys="Schedule.teacher_id")
    enrollments = db.relationship("Enrollment", back_populates="student", foreign_keys="Enrollment.student_id")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash or "", password)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_manager(self):
        return self.role == "manager"


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_name = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(80), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    classroom = db.Column(db.String(40))
    description = db.Column(db.Text)
    tuition_amount = db.Column(db.Integer, default=0)
    tuition_type = db.Column(db.String(20), default="monthly")
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)

    teacher = db.relationship("User", back_populates="courses_taught", foreign_keys=[teacher_id])
    schedules = db.relationship("Schedule", back_populates="course", cascade="all, delete-orphan")
    enrollments = db.relationship("Enrollment", back_populates="course", cascade="all, delete-orphan")
    tuition_payments = db.relationship("TuitionPayment", back_populates="course", cascade="all, delete-orphan")


class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    classroom = db.Column(db.String(40), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    duration_hours = db.Column(db.Float, nullable=False)

    course = db.relationship("Course", back_populates="schedules")
    teacher = db.relationship("User", back_populates="schedules", foreign_keys=[teacher_id])


class Enrollment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    status = db.Column(db.String(20), default="active")
    enrolled_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

    student = db.relationship("User", back_populates="enrollments", foreign_keys=[student_id])
    course = db.relationship("Course", back_populates="enrollments")
    __table_args__ = (db.UniqueConstraint("student_id", "course_id", name="uq_student_course"),)


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, default=dt.date.today)
    status = db.Column(db.String(20), nullable=False, default="present")
    note = db.Column(db.Text)
    marked_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    student = db.relationship("User", foreign_keys=[student_id])
    course = db.relationship("Course")
    marked_by = db.relationship("User", foreign_keys=[marked_by_id])
    __table_args__ = (db.UniqueConstraint("student_id", "course_id", "date", name="uq_attendance_student_course_date"),)


class TeacherPayroll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    month = db.Column(db.String(7), nullable=False)
    total_classes = db.Column(db.Integer, default=0)
    total_hours = db.Column(db.Float, default=0)
    salary_amount = db.Column(db.Integer, default=0)
    calculated_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

    teacher = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("teacher_id", "month", name="uq_teacher_payroll_month"),)


class TeachingRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    classroom = db.Column(db.String(40), nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    hours_taught = db.Column(db.Float, nullable=False)
    hourly_rate = db.Column(db.Integer, nullable=False, default=0)
    amount_earned = db.Column(db.Integer, nullable=False, default=0)
    confirmed_by_teacher = db.Column(db.Boolean, default=False)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    teacher = db.relationship("User", foreign_keys=[teacher_id])
    course = db.relationship("Course")
    __table_args__ = (db.UniqueConstraint("teacher_id", "course_id", "date", name="uq_teaching_record_session"),)


class TuitionPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False, default=0)
    payment_type = db.Column(db.String(20), nullable=False, default="monthly")
    payment_date = db.Column(db.Date, nullable=False, default=dt.date.today)
    status = db.Column(db.String(20), nullable=False, default="paid")
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

    student = db.relationship("User", foreign_keys=[student_id])
    course = db.relationship("Course", back_populates="tuition_payments")


# ──────────────────────── EXAM MODELS ────────────────────────

class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    duration_minutes = db.Column(db.Integer, default=30)
    is_active = db.Column(db.Boolean, default=True)
    shuffle_questions = db.Column(db.Boolean, default=True)
    shuffle_answers = db.Column(db.Boolean, default=True)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

    course = db.relationship("Course")
    creator = db.relationship("User", foreign_keys=[created_by])
    questions = db.relationship("ExamQuestion", back_populates="exam", cascade="all, delete-orphan", order_by="ExamQuestion.order_index")
    submissions = db.relationship("ExamSubmission", back_populates="exam", cascade="all, delete-orphan")

    @property
    def total_points(self):
        return sum(q.points for q in self.questions)

    @property
    def question_count(self):
        return len(self.questions)

    @property
    def status_label(self):
        now = dt.datetime.utcnow()
        if not self.is_active:
            return "closed"
        if self.start_time and now < self.start_time:
            return "upcoming"
        if self.end_time and now > self.end_time:
            return "closed"
        return "open"


class ExamQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exam.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(20), nullable=False, default="single")  # single, multi, truefalse
    points = db.Column(db.Float, default=1.0)
    order_index = db.Column(db.Integer, default=0)

    exam = db.relationship("Exam", back_populates="questions")
    answers = db.relationship("ExamAnswer", back_populates="question", cascade="all, delete-orphan", order_by="ExamAnswer.id")


class ExamAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("exam_question.id"), nullable=False)
    answer_text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, default=False)

    question = db.relationship("ExamQuestion", back_populates="answers")


class ExamSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exam.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    started_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)
    total_score = db.Column(db.Float, default=0)
    max_score = db.Column(db.Float, default=0)
    is_graded = db.Column(db.Boolean, default=False)

    exam = db.relationship("Exam", back_populates="submissions")
    student = db.relationship("User", foreign_keys=[student_id])
    answers = db.relationship("SubmissionAnswer", back_populates="submission", cascade="all, delete-orphan")

    @property
    def percentage(self):
        if self.max_score == 0:
            return 0
        return round(self.total_score / self.max_score * 100, 1)

    __table_args__ = (db.UniqueConstraint("exam_id", "student_id", name="uq_exam_student"),)


class SubmissionAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("exam_submission.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("exam_question.id"), nullable=False)
    selected_answer_ids = db.Column(db.Text, default="[]")  # JSON array of answer IDs
    is_correct = db.Column(db.Boolean, default=False)
    points_earned = db.Column(db.Float, default=0)

    submission = db.relationship("ExamSubmission", back_populates="answers")
    question = db.relationship("ExamQuestion")

    def get_selected_ids(self):
        try:
            return json.loads(self.selected_answer_ids or "[]")
        except (json.JSONDecodeError, TypeError):
            return []


# ──────────────────────── FORMS ────────────────────────

class RegistrationForm(FlaskForm):
    user_code = StringField("Mã người dùng", validators=[DataRequired(), Length(min=3, max=20)])
    fullname = StringField("Họ và tên", validators=[DataRequired(), Length(min=2, max=100)])
    username = StringField("Tên đăng nhập", validators=[DataRequired(), Length(min=4, max=80)])
    phone = TelField("Số điện thoại", validators=[Optional()])
    parent_phone = TelField("SĐT phụ huynh", validators=[Optional()])
    position = StringField("Lớp / Chức vụ", validators=[Optional(), Length(max=100)])
    role = SelectField(
        "Vai trò",
        choices=[("student", "Học sinh"), ("teacher", "Giáo viên"), ("parent", "Phụ huynh")],
        validators=[DataRequired()],
    )
    password = PasswordField("Mật khẩu", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Nhập lại mật khẩu", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Đăng ký")

    def validate_username(self, username):
        if User.query.filter_by(username=username.data).first():
            raise ValidationError("Tên đăng nhập đã tồn tại.")

    def validate_user_code(self, user_code):
        if User.query.filter_by(user_code=user_code.data).first():
            raise ValidationError("Mã người dùng đã tồn tại.")

    def validate_role(self, role):
        if role.data in ("admin", "manager"):
            raise ValidationError("Không thể đăng ký vai trò này.")


class LoginForm(FlaskForm):
    username = StringField("Tên đăng nhập", validators=[DataRequired()])
    password = PasswordField("Mật khẩu", validators=[DataRequired()])
    submit = SubmitField("Đăng nhập")


class UpdateProfileForm(FlaskForm):
    fullname = StringField("Họ và tên", validators=[DataRequired(), Length(min=2)])
    username = StringField("Tên đăng nhập", validators=[DataRequired(), Length(min=4)])
    phone = TelField("Số điện thoại", validators=[Optional()])
    parent_phone = TelField("SĐT phụ huynh", validators=[Optional()])
    position = StringField("Lớp / Chức vụ", validators=[Optional(), Length(max=100)])
    birth_date = DateField("Ngày sinh", validators=[Optional()])
    avatar = FileField("Avatar", validators=[FileAllowed(["jpg", "png", "jpeg"], "Chỉ nhận file ảnh!")])
    submit_profile = SubmitField("Cập nhật")

    def validate_username(self, username):
        if username.data != current_user.username and User.query.filter_by(username=username.data).first():
            raise ValidationError("Tên đăng nhập này đã có người sử dụng.")


class ChangePasswordForm(FlaskForm):
    old_password = PasswordField("Mật khẩu cũ", validators=[DataRequired()])
    new_password = PasswordField("Mật khẩu mới", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Xác nhận mật khẩu mới", validators=[DataRequired(), EqualTo("new_password")])
    submit_password = SubmitField("Đổi mật khẩu")


# ──────────────────────── HELPERS ────────────────────────

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


def first_day_of_month():
    today = dt.date.today()
    return today.replace(day=1)


def month_key(date_value=None):
    return (date_value or dt.date.today()).strftime("%Y-%m")


def week_bounds(date_value=None):
    anchor = date_value or dt.date.today()
    start = anchor - dt.timedelta(days=anchor.weekday())
    return start, start + dt.timedelta(days=6)


def month_bounds(month_value=None):
    if month_value:
        start = dt.datetime.strptime(month_value + "-01", "%Y-%m-%d").date()
    else:
        start = first_day_of_month()
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
    payroll.total_hours = round(sum(record.hours_taught for record in records), 2)
    payroll.salary_amount = int(sum(record.amount_earned for record in records))
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
    record.amount_earned = int(record.hours_taught * record.hourly_rate)
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
    total_hours = round(sum(record.hours_taught for record in records), 2)
    
    confirmed = sum(1 for r in records if r.confirmed_by_teacher)
    confirmed_hours = round(sum(r.hours_taught for r in records if r.confirmed_by_teacher), 2)
    confirmed_salary = int(sum(r.amount_earned for r in records if r.confirmed_by_teacher))
    
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
    return teaching_summary(teacher_id, first_day_of_month(), dt.date.today())


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


@app.context_processor
def inject_globals():
    return {
        "WEEKDAYS": dict(WEEKDAYS),
        "STATUS_LABELS": STATUS_LABELS,
        "TUITION_LABELS": TUITION_LABELS,
        "ROLE_LABELS": ROLE_LABELS,
        "current_month_summary": current_month_summary,
        "money": lambda value: f"{int(value or 0):,}".replace(",", "."),
    }


# ──────────────────────── AUTH ROUTES ────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = RegistrationForm()
    if form.validate_on_submit():
        if form.role.data in ("admin", "manager"):
            flash("Không thể đăng ký vai trò này.", "danger")
            return redirect(url_for("register"))
        user = User(
            username=form.username.data,
            fullname=form.fullname.data,
            user_code=form.user_code.data,
            role=form.role.data,
            phone=form.phone.data,
            parent_phone=form.parent_phone.data,
            position=form.position.data,
            is_active=True,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("Đăng ký tài khoản thành công.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data) and user.is_active:
            login_user(user)
            return redirect(request.args.get("next") or url_for("index"))
        flash("Sai tên đăng nhập, mật khẩu hoặc tài khoản đã bị khóa.", "danger")
    return render_template("login.html", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    profile_form = UpdateProfileForm()
    password_form = ChangePasswordForm()

    if profile_form.submit_profile.data and profile_form.validate():
        if profile_form.avatar.data:
            current_user.avatar = save_picture(profile_form.avatar.data, app.config["UPLOAD_FOLDER_AVATARS"])
        current_user.fullname = profile_form.fullname.data
        current_user.username = profile_form.username.data
        current_user.phone = profile_form.phone.data
        current_user.parent_phone = profile_form.parent_phone.data if current_user.role == "student" else None
        current_user.position = profile_form.position.data
        current_user.birth_date = profile_form.birth_date.data
        db.session.commit()
        flash("Cập nhật hồ sơ thành công.", "success")
        return redirect(url_for("profile"))

    if password_form.submit_password.data and password_form.validate():
        if not current_user.check_password(password_form.old_password.data):
            flash("Mật khẩu cũ không đúng.", "danger")
        else:
            current_user.set_password(password_form.new_password.data)
            db.session.commit()
            flash("Đổi mật khẩu thành công.", "success")
            return redirect(url_for("profile"))

    if request.method == "GET":
        profile_form.fullname.data = current_user.fullname
        profile_form.username.data = current_user.username
        profile_form.phone.data = current_user.phone
        profile_form.parent_phone.data = current_user.parent_phone
        profile_form.position.data = current_user.position
        profile_form.birth_date.data = current_user.birth_date

    image_file = url_for("static", filename="avatars/" + (current_user.avatar or "default.jpg"))
    return render_template("profile.html", profile_form=profile_form, password_form=password_form, image_file=image_file)


# ──────────────────────── DASHBOARD ────────────────────────

@app.route("/")
@login_required
def index():
    today = dt.date.today()

    # Default variables to prevent any jinja2.exceptions.UndefinedError
    defaults = {
        "dashboard_scope": "center",
        "student": None,
        "teacher_data": None,
        "student_data": None,
        "unpaid_tuition": 0,
        "timetable_grid": None,
        "anchor": today,
        "recent_attendance": [],
        "payroll_history": [],
        "exams_data": [],
        "activities": [],
        "unpaid_payments": [],
        "recent_payments": [],
        "recent_teaching_records": [],
        "schedules": [],
        "total_students": 0,
        "total_teachers": 0,
        "monthly_revenue": 0,
        "unpaid_tuition_count": 0,
        "total_teaching_hours": 0,
        "total_teacher_payroll": 0
    }

    if current_user.role == "teacher":
        teacher_data = teacher_dashboard_data(current_user)
        user_schedules = schedules_for_user(current_user)
        start_week, end_week = week_bounds(today)
        timetable_grid = build_timetable_grid(user_schedules, start_week, end_week)
        
        # Recent attendance
        course_ids = [c.id for c in Course.query.filter_by(teacher_id=current_user.id).all()]
        recent_attendance = (
            Attendance.query.filter(Attendance.course_id.in_(course_ids))
            .order_by(Attendance.date.desc(), Attendance.created_at.desc())
            .limit(10).all()
        ) if course_ids else []

        # Payroll history
        payroll_history = (
            TeacherPayroll.query.filter_by(teacher_id=current_user.id)
            .order_by(TeacherPayroll.month.desc())
            .limit(5).all()
        )

        # Exams with submissions info
        teacher_exams = Exam.query.filter_by(created_by=current_user.id).order_by(Exam.created_at.desc()).all()
        exams_data = []
        for exam in teacher_exams:
            pending_grading = ExamSubmission.query.filter_by(exam_id=exam.id, is_graded=False).count()
            total_subs = ExamSubmission.query.filter_by(exam_id=exam.id).count()
            exams_data.append({
                "exam": exam,
                "pending_grading": pending_grading,
                "total_submissions": total_subs
            })

        # Activity feed
        activities = []
        exam_ids = [e.id for e in teacher_exams]
        if exam_ids:
            subs = ExamSubmission.query.filter(ExamSubmission.exam_id.in_(exam_ids)).order_by(ExamSubmission.submitted_at.desc()).limit(10).all()
            for s in subs:
                activities.append({
                    "type": "exam_submission",
                    "title": f"Nộp bài kiểm tra: {s.exam.title}",
                    "desc": f"Học sinh {s.student.fullname} đã nộp bài. Trạng thái: {'Đã chấm' if s.is_graded else 'Chờ chấm'}",
                    "time": s.submitted_at,
                    "icon": "file-check"
                })
        records = TeachingRecord.query.filter_by(teacher_id=current_user.id).order_by(TeachingRecord.date.desc()).limit(10).all()
        for r in records:
            activities.append({
                "type": "teaching_record",
                "title": f"Báo giảng ngày {r.date.strftime('%d/%m/%Y')}",
                "desc": f"Khóa {r.course.course_name} ({r.hours_taught}h) - {r.status.upper()}",
                "time": dt.datetime.combine(r.date, dt.time.min),
                "icon": "clipboard-check"
            })
        activities.sort(key=lambda x: x["time"], reverse=True)
        activities = activities[:8]

        context = {
            "dashboard_scope": "teacher",
            "teacher_data": teacher_data,
            "timetable_grid": timetable_grid,
            "recent_attendance": recent_attendance,
            "payroll_history": payroll_history,
            "exams_data": exams_data,
            "activities": activities
        }
        return render_template("index.html", **{**defaults, **context})

    if current_user.role in ("student", "parent"):
        student_id = current_user.id if current_user.role == "student" else current_user.linked_student_id
        student = db.session.get(User, student_id) if student_id else None
        
        if student:
            student_data = student_dashboard_data(student)
            
            # Unpaid tuition
            unpaid_tuition = (
                db.session.query(db.func.sum(TuitionPayment.amount))
                .filter(
                    TuitionPayment.student_id == student.id,
                    TuitionPayment.status.in_(["unpaid", "partial"])
                ).scalar() or 0
            )

            # Timetable
            user_schedules = schedules_for_user(student)
            start_week, end_week = week_bounds(today)
            timetable_grid = build_timetable_grid(user_schedules, start_week, end_week)

            # Unpaid payments
            unpaid_payments = TuitionPayment.query.filter(
                TuitionPayment.student_id == student.id,
                TuitionPayment.status.in_(["unpaid", "partial"])
            ).order_by(TuitionPayment.payment_date.asc()).all()

            # Exams portal
            course_ids = [e.course_id for e in Enrollment.query.filter_by(student_id=student.id, status="active").all()]
            student_exams = Exam.query.filter(Exam.course_id.in_(course_ids), Exam.is_active == True).order_by(Exam.created_at.desc()).all() if course_ids else []
            exams_data = []
            for exam in student_exams:
                submission = ExamSubmission.query.filter_by(exam_id=exam.id, student_id=student.id).first()
                status = "not_started"
                score_str = ""
                if submission:
                    status = "graded" if submission.is_graded else "submitted"
                    score_str = f"{submission.total_score}/{submission.max_score}"
                exams_data.append({
                    "exam": exam,
                    "status": status,
                    "score_str": score_str,
                    "submission_id": submission.id if submission else None
                })

            # Activities
            activities = []
            att_records = Attendance.query.filter_by(student_id=student.id).order_by(Attendance.date.desc()).limit(10).all()
            for att in att_records:
                status_vi = "Có mặt" if att.status == "present" else "Vắng mặt" if att.status == "absent" else "Đi trễ"
                activities.append({
                    "type": "attendance",
                    "title": f"Điểm danh: {status_vi}",
                    "desc": f"Khóa {att.course.course_name} ngày {att.date.strftime('%d/%m/%Y')}",
                    "time": dt.datetime.combine(att.date, dt.time.min),
                    "icon": "user-check"
                })
            payments = TuitionPayment.query.filter_by(student_id=student.id).order_by(TuitionPayment.payment_date.desc()).limit(10).all()
            for p in payments:
                activities.append({
                    "type": "payment",
                    "title": f"Đóng học phí: {p.amount:,} đ",
                    "desc": f"Khóa {p.course.course_name} ({p.status})",
                    "time": dt.datetime.combine(p.payment_date, dt.time.min),
                    "icon": "coins"
                })
            subs = ExamSubmission.query.filter_by(student_id=student.id).order_by(ExamSubmission.submitted_at.desc()).limit(10).all()
            for s in subs:
                desc = f"Điểm số: {s.total_score}/{s.max_score}" if s.is_graded else "Đang chờ chấm"
                activities.append({
                    "type": "exam",
                    "title": f"Nộp bài kiểm tra: {s.exam.title}",
                    "desc": desc,
                    "time": s.submitted_at,
                    "icon": "file-question"
                })
            activities.sort(key=lambda x: x["time"], reverse=True)
            activities = activities[:8]

            context = {
                "dashboard_scope": "student",
                "student_data": student_data,
                "student": student,
                "unpaid_tuition": unpaid_tuition,
                "timetable_grid": timetable_grid,
                "unpaid_payments": unpaid_payments,
                "exams_data": exams_data,
                "activities": activities
            }
            return render_template("index.html", **{**defaults, **context})
        
        context = {
            "dashboard_scope": "student",
            "student_data": None,
            "student": None
        }
        return render_template("index.html", **{**defaults, **context})

    # Admin / Manager dashboard
    month_start = first_day_of_month()
    total_students = User.query.filter_by(role="student").count()
    total_teachers = User.query.filter_by(role="teacher").count()
    total_courses = Course.query.count()
    total_classes_today = Schedule.query.filter_by(weekday=today.weekday()).count()
    monthly_revenue = (
        db.session.query(db.func.coalesce(db.func.sum(TuitionPayment.amount), 0))
        .filter(TuitionPayment.payment_date >= month_start, TuitionPayment.status.in_(["paid", "partial"]))
        .scalar()
    )
    unpaid_tuition_count = TuitionPayment.query.filter(TuitionPayment.status.in_(["unpaid", "partial"])).count()
    teachers_list = User.query.filter_by(role="teacher").all()
    payroll_rows = [current_month_summary(teacher.id) for teacher in teachers_list]
    total_teaching_hours = sum(row["total_hours"] for row in payroll_rows)
    total_teacher_payroll = sum(row["salary"] for row in payroll_rows)

    # Timetable
    all_schedules = Schedule.query.order_by(Schedule.weekday, Schedule.start_time).all()
    start_week, end_week = week_bounds(today)
    timetable_grid = build_timetable_grid(all_schedules, start_week, end_week)

    # Recent attendance
    recent_attendance = Attendance.query.order_by(Attendance.date.desc(), Attendance.created_at.desc()).limit(15).all()

    # Payroll/tuition summaries
    recent_payments = TuitionPayment.query.order_by(TuitionPayment.payment_date.desc()).limit(6).all()
    recent_teaching_records = TeachingRecord.query.order_by(TeachingRecord.date.desc()).limit(6).all()

    # Center exams
    center_exams = Exam.query.order_by(Exam.created_at.desc()).limit(8).all()
    exams_data = []
    for exam in center_exams:
        total_subs = ExamSubmission.query.filter_by(exam_id=exam.id).count()
        exams_data.append({
            "exam": exam,
            "total_submissions": total_subs
        })

    # Center activities
    activities = []
    payments = TuitionPayment.query.order_by(TuitionPayment.payment_date.desc()).limit(15).all()
    for p in payments:
        activities.append({
            "type": "payment",
            "title": f"Học phí: {p.student.fullname}",
            "desc": f"Khóa {p.course.course_name}: {p.amount:,} đ ({p.status})",
            "time": dt.datetime.combine(p.payment_date, dt.time.min),
            "icon": "coins"
        })
    teaching_recs = TeachingRecord.query.order_by(TeachingRecord.date.desc()).limit(15).all()
    for tr in teaching_recs:
        activities.append({
            "type": "teaching_record",
            "title": f"Báo giảng: {tr.teacher.fullname}",
            "desc": f"Khóa {tr.course.course_name} ({tr.hours_taught}h) - {tr.status}",
            "time": dt.datetime.combine(tr.date, dt.time.min),
            "icon": "clipboard-check"
        })
    subs = ExamSubmission.query.order_by(ExamSubmission.submitted_at.desc()).limit(15).all()
    for s in subs:
        activities.append({
            "type": "exam",
            "title": f"Bài thi: {s.student.fullname}",
            "desc": f"Môn {s.exam.course.course_name} - {'Đang chờ chấm' if not s.is_graded else f'{s.total_score}/{s.max_score}'}",
            "time": s.submitted_at,
            "icon": "file-question"
        })
    
    # Sort and slice
    activities.sort(key=lambda x: x["time"], reverse=True)
    activities = activities[:10]

    context = {
        "dashboard_scope": "center",
        "total_students": total_students,
        "total_teachers": total_teachers,
        "total_courses": total_courses,
        "total_classes_today": total_classes_today,
        "monthly_revenue": monthly_revenue,
        "unpaid_tuition_count": unpaid_tuition_count,
        "total_teaching_hours": total_teaching_hours,
        "total_teacher_payroll": total_teacher_payroll,
        "timetable_grid": timetable_grid,
        "recent_attendance": recent_attendance,
        "recent_payments": recent_payments,
        "recent_teaching_records": recent_teaching_records,
        "exams_data": exams_data,
        "activities": activities,
        "schedules": all_schedules
    }
    return render_template("index.html", **{**defaults, **context})


# ──────────────────────── COURSES ────────────────────────

@app.route("/courses")
@login_required
def courses():
    query = Course.query
    if current_user.role == "teacher":
        query = query.filter_by(teacher_id=current_user.id)
    elif current_user.role in ("student", "parent"):
        student_ids = get_accessible_student_ids()
        course_ids = [enrollment.course_id for enrollment in Enrollment.query.filter(Enrollment.student_id.in_(student_ids)).all()]
        query = query.filter(Course.id.in_(course_ids)) if course_ids else query.filter(db.text("0=1"))
    return render_template("courses.html", courses=query.order_by(Course.course_name).all())


@app.route("/courses/new", methods=["GET", "POST"])
@login_required
@manager_or_admin_required
def add_course():
    teachers = User.query.filter_by(role="teacher").order_by(User.fullname).all()
    if request.method == "POST":
        course = Course(
            course_name=request.form["course_name"],
            subject=request.form["subject"],
            teacher_id=request.form.get("teacher_id") or None,
            classroom=request.form.get("classroom"),
            description=request.form.get("description"),
            tuition_amount=money(request.form.get("tuition_amount")),
            tuition_type=request.form.get("tuition_type", "monthly"),
            start_date=parse_date(request.form.get("start_date")),
            end_date=parse_date(request.form.get("end_date")),
            is_active=bool(request.form.get("is_active")),
        )
        db.session.add(course)
        db.session.commit()
        flash("Đã tạo khóa học.", "success")
        return redirect(url_for("courses"))
    return render_template("course_form.html", course=None, teachers=teachers)


@app.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
@login_required
@manager_or_admin_required
def edit_course(course_id):
    course = db.session.get(Course, course_id) or abort(404)
    teachers = User.query.filter_by(role="teacher").order_by(User.fullname).all()
    if request.method == "POST":
        course.course_name = request.form["course_name"]
        course.subject = request.form["subject"]
        course.teacher_id = request.form.get("teacher_id") or None
        course.classroom = request.form.get("classroom")
        course.description = request.form.get("description")
        course.tuition_amount = money(request.form.get("tuition_amount"))
        course.tuition_type = request.form.get("tuition_type", "monthly")
        course.start_date = parse_date(request.form.get("start_date"))
        course.end_date = parse_date(request.form.get("end_date"))
        course.is_active = bool(request.form.get("is_active"))
        db.session.commit()
        flash("Đã cập nhật khóa học.", "success")
        return redirect(url_for("courses"))
    return render_template("course_form.html", course=course, teachers=teachers)


@app.route("/courses/<int:course_id>/delete", methods=["POST"])
@login_required
@manager_or_admin_required
def delete_course(course_id):
    db.session.delete(db.session.get(Course, course_id) or abort(404))
    db.session.commit()
    flash("Đã xóa khóa học.", "success")
    return redirect(url_for("courses"))


# ──────────────────────── SCHEDULES ────────────────────────

@app.route("/schedules", methods=["GET", "POST"])
@login_required
@manager_or_admin_required
def schedules():
    courses_list = Course.query.order_by(Course.course_name).all()
    teachers = User.query.filter_by(role="teacher").order_by(User.fullname).all()
    if request.method == "POST":
        start = parse_time(request.form["start_time"])
        end = parse_time(request.form["end_time"])
        schedule = Schedule(  # type: ignore[call-arg]
            course_id=request.form["course_id"],
            teacher_id=request.form["teacher_id"],
            classroom=request.form["classroom"],
            weekday=int(request.form["weekday"]),
            start_time=start,
            end_time=end,
            duration_hours=duration_hours(start, end),
        )
        course = db.session.get(Course, int(request.form["course_id"]))
        if course:
            course.teacher_id = schedule.teacher_id
            course.classroom = schedule.classroom
        db.session.add(schedule)
        db.session.commit()
        flash("Đã tạo lịch học.", "success")
        return redirect(url_for("schedules"))
    all_schedules = Schedule.query.order_by(Schedule.weekday, Schedule.start_time).all()
    return render_template("schedules.html", schedules=all_schedules, courses=courses_list, teachers=teachers)


@app.route("/schedules/<int:schedule_id>/edit", methods=["GET", "POST"])
@login_required
@manager_or_admin_required
def edit_schedule(schedule_id):
    schedule = db.session.get(Schedule, schedule_id) or abort(404)
    courses_list = Course.query.order_by(Course.course_name).all()
    teachers = User.query.filter_by(role="teacher").order_by(User.fullname).all()
    if request.method == "POST":
        start = parse_time(request.form["start_time"])
        end = parse_time(request.form["end_time"])
        schedule.course_id = request.form["course_id"]
        schedule.teacher_id = request.form["teacher_id"]
        schedule.classroom = request.form["classroom"]
        schedule.weekday = int(request.form["weekday"])
        schedule.start_time = start
        schedule.end_time = end
        schedule.duration_hours = duration_hours(start, end)
        db.session.commit()
        flash("Đã cập nhật lịch học.", "success")
        return redirect(url_for("schedules"))
    return render_template("schedule_form.html", schedule=schedule, courses=courses_list, teachers=teachers)


@app.route("/schedules/<int:schedule_id>/delete", methods=["POST"])
@login_required
@manager_or_admin_required
def delete_schedule(schedule_id):
    db.session.delete(db.session.get(Schedule, schedule_id) or abort(404))
    db.session.commit()
    flash("Đã xóa lịch học.", "success")
    return redirect(url_for("schedules"))


# ──────────────────────── TIMETABLE ────────────────────────

@app.route("/timetable")
@login_required
def center_timetable():
    if current_user.role not in ("admin", "manager"):
        return redirect(url_for("my_schedule"))
    view_mode = request.args.get("view", "week")
    anchor = parse_date(request.args.get("date")) or dt.date.today()
    start, end = month_bounds(anchor.strftime("%Y-%m")) if view_mode == "month" else week_bounds(anchor)
    user_schedules = schedules_for_user(current_user)
    occurrences = schedule_occurrences(user_schedules, start, end)
    timetable_grid = build_timetable_grid(user_schedules, start, end)
    color_map = get_course_color_map(user_schedules)
    return render_template("timetable.html", title="Thời khóa biểu trung tâm", occurrences=occurrences,
                           view_mode=view_mode, anchor=anchor, timetable_grid=timetable_grid, color_map=color_map)


@app.route("/teacher-timetable")
@app.route("/teacher-timetable/<int:teacher_id>")
@login_required
def teacher_timetable(teacher_id=None):
    # Security: teachers can only see their own timetable
    if current_user.role == "teacher":
        teacher_id = current_user.id
    elif current_user.role not in ("admin", "manager"):
        flash("Bạn không có quyền xem lịch giáo viên.", "danger")
        return redirect(url_for("index"))
    teacher = db.session.get(User, teacher_id) if teacher_id else None
    schedules_query = Schedule.query.filter_by(teacher_id=teacher_id) if teacher_id else Schedule.query
    view_mode = request.args.get("view", "week")
    anchor = parse_date(request.args.get("date")) or dt.date.today()
    start, end = month_bounds(anchor.strftime("%Y-%m")) if view_mode == "month" else week_bounds(anchor)
    schedules_list = schedules_query.order_by(Schedule.weekday, Schedule.start_time).all()
    occurrences = schedule_occurrences(schedules_list, start, end)
    timetable_grid = build_timetable_grid(schedules_list, start, end)
    color_map = get_course_color_map(schedules_list)
    return render_template(
        "timetable.html",
        title="Thời khóa biểu giáo viên",
        occurrences=occurrences,
        view_mode=view_mode,
        anchor=anchor,
        selected_user=teacher,
        teachers=User.query.filter_by(role="teacher").all() if current_user.role in ("admin", "manager") else [],
        timetable_grid=timetable_grid,
        color_map=color_map,
    )


@app.route("/student-timetable")
@app.route("/student-timetable/<int:student_id>")
@login_required
def student_timetable(student_id=None):
    # Security: students can only see their own timetable
    if current_user.role == "student":
        student_id = current_user.id
    elif current_user.role == "parent":
        student_id = current_user.linked_student_id
    elif current_user.role not in ("admin", "manager"):
        flash("Bạn không có quyền xem lịch học sinh.", "danger")
        return redirect(url_for("index"))
    # Extra check: if student/parent, don't allow passing arbitrary student_id via URL
    if current_user.role == "student" and student_id != current_user.id:
        student_id = current_user.id
    if current_user.role == "parent" and student_id != current_user.linked_student_id:
        student_id = current_user.linked_student_id

    student = db.session.get(User, student_id) if student_id else None
    if student_id:
        course_ids = [enrollment.course_id for enrollment in Enrollment.query.filter_by(student_id=student_id, status="active").all()]
        schedules_list = Schedule.query.filter(Schedule.course_id.in_(course_ids)).order_by(Schedule.weekday, Schedule.start_time).all() if course_ids else []
    else:
        schedules_list = Schedule.query.order_by(Schedule.weekday, Schedule.start_time).all()
    view_mode = request.args.get("view", "week")
    anchor = parse_date(request.args.get("date")) or dt.date.today()
    start, end = month_bounds(anchor.strftime("%Y-%m")) if view_mode == "month" else week_bounds(anchor)
    timetable_grid = build_timetable_grid(schedules_list, start, end)
    color_map = get_course_color_map(schedules_list)
    return render_template(
        "timetable.html",
        title="Thời khóa biểu học sinh",
        occurrences=schedule_occurrences(schedules_list, start, end),
        view_mode=view_mode,
        anchor=anchor,
        selected_user=student,
        students=User.query.filter_by(role="student").all() if current_user.role in ("admin", "manager") else [],
        timetable_grid=timetable_grid,
        color_map=color_map,
    )


@app.route("/my_schedule")
@login_required
def my_schedule():
    view_mode = request.args.get("view", "week")
    anchor = parse_date(request.args.get("date")) or dt.date.today()
    start, end = month_bounds(anchor.strftime("%Y-%m")) if view_mode == "month" else week_bounds(anchor)
    user_schedules = schedules_for_user(current_user)
    timetable_grid = build_timetable_grid(user_schedules, start, end)
    color_map = get_course_color_map(user_schedules)
    return render_template(
        "timetable.html",
        title="Lịch của tôi",
        occurrences=schedule_occurrences(user_schedules, start, end),
        view_mode=view_mode,
        anchor=anchor,
        timetable_grid=timetable_grid,
        color_map=color_map,
    )


# ──────────────────────── ATTENDANCE ────────────────────────

@app.route("/attendance")
@login_required
@teacher_manager_admin_required
def attendance():
    if current_user.role == "teacher":
        courses_list = Course.query.filter_by(teacher_id=current_user.id).order_by(Course.course_name).all()
    else:
        courses_list = Course.query.order_by(Course.course_name).all()
    records = Attendance.query.order_by(Attendance.date.desc(), Attendance.id.desc()).limit(100).all()
    if current_user.role == "teacher":
        teacher_course_ids = [course.id for course in courses_list]
        records = [record for record in records if record.course_id in teacher_course_ids]
    return render_template("attendance.html", courses=courses_list, records=records)


@app.route("/my-students")
@login_required
def my_students():
    if current_user.role != "teacher":
        flash("Trang này chỉ dành cho giáo viên.", "danger")
        return redirect(url_for("index"))
    students = students_for_teacher(current_user.id)
    return render_template("my_students.html", students=students)


@app.route("/attendance/course/<int:course_id>", methods=["GET", "POST"])
@login_required
@teacher_manager_admin_required
def mark_attendance(course_id):
    course = db.session.get(Course, course_id) or abort(404)
    if current_user.role == "teacher" and course.teacher_id != current_user.id:
        flash("Bạn chỉ được chấm điểm danh lớp mình phụ trách.", "danger")
        return redirect(url_for("attendance"))
    date_value = parse_date(request.form.get("date") or request.args.get("date")) or dt.date.today()
    students = [enrollment.student for enrollment in course.enrollments if enrollment.status == "active"]

    if request.method == "POST":
        for student in students:
            status = request.form.get(f"status_{student.id}", "present")
            record = Attendance.query.filter_by(student_id=student.id, course_id=course.id, date=date_value).first()
            if not record:
                session_schedule = matching_schedule(course, date_value)
                record = Attendance(
                    student_id=student.id,
                    course_id=course.id,
                    date=date_value,
                    schedule_id=session_schedule.id if session_schedule else None,
                )
                db.session.add(record)
            record.status = status
            record.note = request.form.get(f"note_{student.id}")
            record.marked_by_id = current_user.id
        db.session.flush()
        sync_teaching_record(course, date_value)
        db.session.commit()
        flash("Đã lưu điểm danh.", "success")
        return redirect(url_for("mark_attendance", course_id=course.id, date=date_value.isoformat()))

    existing = {record.student_id: record for record in Attendance.query.filter_by(course_id=course.id, date=date_value).all()}
    return render_template("mark_attendance.html", course=course, students=students, date_value=date_value, existing=existing)


# ──────────────────────── PAYROLL ────────────────────────

@app.route("/payroll")
@login_required
def payroll():
    if current_user.role == "teacher":
        teachers = [current_user]
    elif current_user.role in ("admin", "manager"):
        teachers = User.query.filter_by(role="teacher").order_by(User.fullname).all()
    else:
        flash("Bạn không có quyền xem bảng lương.", "danger")
        return redirect(url_for("index"))
    month = request.args.get("month") or month_key()
    start, end = month_bounds(month)
    rows = [{"teacher": teacher, **teaching_summary(teacher.id, start, end)} for teacher in teachers]
    return render_template("payroll.html", rows=rows, month=month)


@app.route("/payroll/<int:teacher_id>")
@login_required
def payroll_detail(teacher_id):
    if current_user.role == "teacher" and teacher_id != current_user.id:
        flash("Bạn chỉ được xem bảng lương của chính mình.", "danger")
        return redirect(url_for("payroll"))
    if current_user.role not in ("admin", "manager", "teacher"):
        flash("Bạn không có quyền xem bảng lương.", "danger")
        return redirect(url_for("index"))

    teacher = db.session.get(User, teacher_id) or abort(404)
    if teacher.role != "teacher":
        abort(404)
    month = request.args.get("month") or month_key()
    start, end = month_bounds(month)
    records = (
        TeachingRecord.query.filter(
            TeachingRecord.teacher_id == teacher.id,
            TeachingRecord.date >= start,
            TeachingRecord.date <= end,
        )
        .order_by(TeachingRecord.date.desc(), TeachingRecord.start_time.desc())
        .all()
    )
    summary = teaching_summary(teacher.id, start, end)
    return render_template("payroll_detail.html", teacher=teacher, records=records, summary=summary, month=month)


# ──────────────────────── TEACHING RECORDS (CONFIRM) ────────────────────────

@app.route("/teaching/my-records")
@login_required
def my_teaching_records():
    if current_user.role not in ("admin", "manager", "teacher"):
        flash("Bạn không có quyền truy cập.", "danger")
        return redirect(url_for("index"))
    if current_user.role == "teacher":
        teacher_id = current_user.id
    else:
        teacher_id = request.args.get("teacher_id", type=int)
    month = request.args.get("month") or month_key()
    start, end = month_bounds(month)
    query = TeachingRecord.query.filter(TeachingRecord.date >= start, TeachingRecord.date <= end)
    if teacher_id:
        query = query.filter_by(teacher_id=teacher_id)
    records = query.order_by(TeachingRecord.date.desc(), TeachingRecord.start_time.desc()).all()
    teachers = User.query.filter_by(role="teacher").order_by(User.fullname).all() if current_user.role in ("admin", "manager") else []
    return render_template("teaching_records.html", records=records, month=month, teachers=teachers, selected_teacher_id=teacher_id)


@app.route("/teaching/confirm/<int:record_id>", methods=["POST"])
@login_required
def confirm_teaching(record_id):
    record = db.session.get(TeachingRecord, record_id) or abort(404)
    if current_user.role == "teacher" and record.teacher_id != current_user.id:
        flash("Bạn chỉ được xác nhận buổi dạy của mình.", "danger")
        return redirect(url_for("my_teaching_records"))
    if current_user.role not in ("admin", "manager", "teacher"):
        abort(403)
    record.confirmed_by_teacher = True
    record.confirmed_at = dt.datetime.utcnow()
    db.session.commit()
    flash("Đã xác nhận buổi dạy.", "success")
    return redirect(request.referrer or url_for("my_teaching_records"))


# ──────────────────────── TUITION ────────────────────────

@app.route("/tuition", methods=["GET", "POST"])
@login_required
def tuition():
    if current_user.role in ("student", "parent"):
        student_ids = get_accessible_student_ids()
        payments = TuitionPayment.query.filter(TuitionPayment.student_id.in_(student_ids)).order_by(TuitionPayment.payment_date.desc()).all()
        return render_template("tuition.html", payments=payments, students=[], courses=[], readonly=True)

    if current_user.role not in ("admin", "manager"):
        flash("Bạn không có quyền quản lý học phí.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        payment = TuitionPayment(
            student_id=request.form["student_id"],
            course_id=request.form["course_id"],
            amount=money(request.form.get("amount")),
            payment_type=request.form.get("payment_type", "monthly"),
            payment_date=parse_date(request.form.get("payment_date")) or dt.date.today(),
            status=request.form.get("status", "paid"),
            note=request.form.get("note"),
        )
        db.session.add(payment)
        db.session.commit()
        flash("Đã ghi nhận học phí.", "success")
        return redirect(url_for("tuition"))

    payments = TuitionPayment.query.order_by(TuitionPayment.payment_date.desc()).all()
    return render_template(
        "tuition.html",
        payments=payments,
        students=User.query.filter_by(role="student").order_by(User.fullname).all(),
        courses=Course.query.order_by(Course.course_name).all(),
        readonly=False,
    )


@app.route("/tuition/<int:payment_id>/edit", methods=["POST"])
@login_required
@manager_or_admin_required
def edit_tuition(payment_id):
    payment = db.session.get(TuitionPayment, payment_id) or abort(404)
    payment.amount = money(request.form.get("amount"))
    payment.status = request.form.get("status", payment.status)
    payment.note = request.form.get("note")
    db.session.commit()
    flash("Đã cập nhật học phí.", "success")
    return redirect(url_for("tuition"))


# ──────────────────────── USER MANAGEMENT ────────────────────────

@app.route("/users/<role_name>")
@login_required
@manager_or_admin_required
def manage_users(role_name):
    if role_name not in ("students", "teachers", "parents", "staff"):
        abort(404)
    role_map = {"students": ["student"], "teachers": ["teacher"], "parents": ["parent"], "staff": ["admin", "manager"]}
    users = User.query.filter(User.role.in_(role_map[role_name])).order_by(User.fullname).all()
    students = User.query.filter_by(role="student").order_by(User.fullname).all()
    return render_template("manage_users.html", users=users, role_name=role_name, students=students)


@app.route("/users", methods=["POST"])
@login_required
@manager_or_admin_required
def add_user():
    role = request.form["role"]
    if current_user.role == "manager" and role == "admin":
        flash("Quản lý không được tạo tài khoản admin.", "danger")
        return redirect(request.referrer or url_for("index"))
    user = User(
        username=request.form["username"],
        fullname=request.form["fullname"],
        user_code=request.form["user_code"],
        role=role,
        phone=request.form.get("phone"),
        position=request.form.get("position"),
        salary_rate_per_hour=money(request.form.get("salary_rate_per_hour")),
        linked_student_id=request.form.get("linked_student_id") or None,
        is_active=True,
    )
    user.set_password(request.form.get("password") or "123456")
    db.session.add(user)
    db.session.commit()
    flash("Đã thêm người dùng.", "success")
    return redirect(request.referrer or url_for("manage_users", role_name="students"))


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@manager_or_admin_required
def edit_user(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if current_user.role == "manager" and user.role == "admin":
        flash("Quản lý không được thay đổi tài khoản admin.", "danger")
        return redirect(url_for("manage_users", role_name="staff"))
    students = User.query.filter_by(role="student").order_by(User.fullname).all()
    if request.method == "POST":
        new_role = request.form["role"]
        if current_user.role == "manager" and (user.role == "admin" or new_role == "admin"):
            flash("Quản lý không được thay đổi quyền admin.", "danger")
            return redirect(url_for("manage_users", role_name="staff"))
        user.fullname = request.form["fullname"]
        user.username = request.form["username"]
        user.user_code = request.form["user_code"]
        user.role = new_role
        user.phone = request.form.get("phone")
        user.position = request.form.get("position")
        user.salary_rate_per_hour = money(request.form.get("salary_rate_per_hour"))
        user.linked_student_id = request.form.get("linked_student_id") or None
        user.is_active = bool(request.form.get("is_active"))
        db.session.commit()
        flash("Đã cập nhật người dùng.", "success")
        return redirect(url_for("manage_users", role_name="teachers" if user.role == "teacher" else "students"))
    return render_template("edit_user.html", user=user, students=students)


@app.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@manager_or_admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id or (current_user.role == "manager" and user.role == "admin"):
        flash("Không thể xóa tài khoản này.", "danger")
        return redirect(request.referrer or url_for("index"))
    db.session.delete(user)
    db.session.commit()
    flash("Đã xóa người dùng.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@manager_or_admin_required
def reset_password(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if current_user.role == "manager" and user.role == "admin":
        flash("Quản lý không được reset mật khẩu admin.", "danger")
        return redirect(request.referrer or url_for("index"))
    user.set_password(request.form.get("password") or "123456")
    db.session.commit()
    flash("Đã reset mật khẩu.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/enrollments", methods=["POST"])
@login_required
@manager_or_admin_required
def add_enrollment():
    enrollment = Enrollment(student_id=request.form["student_id"], course_id=request.form["course_id"], status="active")
    db.session.add(enrollment)
    db.session.commit()
    flash("Đã ghi danh học sinh.", "success")
    return redirect(url_for("courses"))


# ──────────────────────── EXAMS ────────────────────────

@app.route("/exams")
@login_required
def exam_list():
    if current_user.role in ("admin", "manager"):
        exams = Exam.query.order_by(Exam.created_at.desc()).all()
    elif current_user.role == "teacher":
        exams = Exam.query.filter_by(created_by=current_user.id).order_by(Exam.created_at.desc()).all()
    elif current_user.role in ("student", "parent"):
        student_id = current_user.id if current_user.role == "student" else current_user.linked_student_id
        if student_id:
            course_ids = [e.course_id for e in Enrollment.query.filter_by(student_id=student_id, status="active").all()]
            exams = Exam.query.filter(Exam.course_id.in_(course_ids), Exam.is_active == True).order_by(Exam.created_at.desc()).all() if course_ids else []
        else:
            exams = []
    else:
        exams = []
    submissions_map = {}
    if current_user.role == "student":
        for sub in ExamSubmission.query.filter_by(student_id=current_user.id).all():
            submissions_map[sub.exam_id] = sub
    return render_template("exam_list.html", exams=exams, submissions_map=submissions_map)


@app.route("/exams/new", methods=["GET", "POST"])
@login_required
def create_exam():
    if current_user.role not in ("admin", "manager", "teacher"):
        abort(403)
    if current_user.role == "teacher":
        courses_list = Course.query.filter_by(teacher_id=current_user.id).order_by(Course.course_name).all()
    else:
        courses_list = Course.query.order_by(Course.course_name).all()

    if request.method == "POST":
        exam = Exam(
            title=request.form["title"],
            course_id=int(request.form["course_id"]),
            created_by=current_user.id,
            duration_minutes=int(request.form.get("duration_minutes", 30)),
            shuffle_questions=bool(request.form.get("shuffle_questions")),
            shuffle_answers=bool(request.form.get("shuffle_answers")),
            is_active=bool(request.form.get("is_active", True)),
        )
        start_time_str = request.form.get("start_time")
        end_time_str = request.form.get("end_time")
        if start_time_str:
            exam.start_time = dt.datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M")
        if end_time_str:
            exam.end_time = dt.datetime.strptime(end_time_str, "%Y-%m-%dT%H:%M")

        # Verify teacher owns the course
        if current_user.role == "teacher":
            course = db.session.get(Course, exam.course_id)
            if not course or course.teacher_id != current_user.id:
                flash("Bạn chỉ được tạo bài kiểm tra cho lớp mình.", "danger")
                return redirect(url_for("exam_list"))

        db.session.add(exam)
        db.session.flush()

        # Parse questions from form
        q_idx = 0
        while f"question_{q_idx}_text" in request.form:
            q_text = request.form[f"question_{q_idx}_text"]
            q_type = request.form.get(f"question_{q_idx}_type", "single")
            q_points = float(request.form.get(f"question_{q_idx}_points", 1))
            if q_text.strip():
                question = ExamQuestion(
                    exam_id=exam.id,
                    question_text=q_text,
                    question_type=q_type,
                    points=q_points,
                    order_index=q_idx,
                )
                db.session.add(question)
                db.session.flush()

                a_idx = 0
                while f"question_{q_idx}_answer_{a_idx}_text" in request.form:
                    a_text = request.form[f"question_{q_idx}_answer_{a_idx}_text"]
                    if a_text.strip():
                        if q_type == "truefalse":
                            is_correct = request.form.get(f"question_{q_idx}_correct") == str(a_idx)
                        elif q_type == "multi":
                            is_correct = request.form.get(f"question_{q_idx}_answer_{a_idx}_correct") == "1"
                        else:
                            is_correct = request.form.get(f"question_{q_idx}_correct") == str(a_idx)
                        answer = ExamAnswer(
                            question_id=question.id,
                            answer_text=a_text,
                            is_correct=is_correct,
                        )
                        db.session.add(answer)
                    a_idx += 1
            q_idx += 1

        db.session.commit()
        flash("Đã tạo bài kiểm tra.", "success")
        return redirect(url_for("exam_list"))

    return render_template("exam_form.html", exam=None, courses=courses_list)


@app.route("/exams/<int:exam_id>/edit", methods=["GET", "POST"])
@login_required
def edit_exam(exam_id):
    exam = db.session.get(Exam, exam_id) or abort(404)
    if current_user.role == "teacher" and exam.created_by != current_user.id:
        abort(403)
    if current_user.role not in ("admin", "manager", "teacher"):
        abort(403)

    if current_user.role == "teacher":
        courses_list = Course.query.filter_by(teacher_id=current_user.id).order_by(Course.course_name).all()
    else:
        courses_list = Course.query.order_by(Course.course_name).all()

    if request.method == "POST":
        exam.title = request.form["title"]
        exam.course_id = int(request.form["course_id"])
        exam.duration_minutes = int(request.form.get("duration_minutes", 30))
        exam.shuffle_questions = bool(request.form.get("shuffle_questions"))
        exam.shuffle_answers = bool(request.form.get("shuffle_answers"))
        exam.is_active = bool(request.form.get("is_active"))
        start_time_str = request.form.get("start_time")
        end_time_str = request.form.get("end_time")
        exam.start_time = dt.datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M") if start_time_str else None
        exam.end_time = dt.datetime.strptime(end_time_str, "%Y-%m-%dT%H:%M") if end_time_str else None

        # Delete old questions
        for q in exam.questions:
            db.session.delete(q)
        db.session.flush()

        # Re-add questions
        q_idx = 0
        while f"question_{q_idx}_text" in request.form:
            q_text = request.form[f"question_{q_idx}_text"]
            q_type = request.form.get(f"question_{q_idx}_type", "single")
            q_points = float(request.form.get(f"question_{q_idx}_points", 1))
            if q_text.strip():
                question = ExamQuestion(
                    exam_id=exam.id,
                    question_text=q_text,
                    question_type=q_type,
                    points=q_points,
                    order_index=q_idx,
                )
                db.session.add(question)
                db.session.flush()

                a_idx = 0
                while f"question_{q_idx}_answer_{a_idx}_text" in request.form:
                    a_text = request.form[f"question_{q_idx}_answer_{a_idx}_text"]
                    if a_text.strip():
                        if q_type == "truefalse":
                            is_correct = request.form.get(f"question_{q_idx}_correct") == str(a_idx)
                        elif q_type == "multi":
                            is_correct = request.form.get(f"question_{q_idx}_answer_{a_idx}_correct") == "1"
                        else:
                            is_correct = request.form.get(f"question_{q_idx}_correct") == str(a_idx)
                        answer = ExamAnswer(
                            question_id=question.id,
                            answer_text=a_text,
                            is_correct=is_correct,
                        )
                        db.session.add(answer)
                    a_idx += 1
            q_idx += 1

        db.session.commit()
        flash("Đã cập nhật bài kiểm tra.", "success")
        return redirect(url_for("exam_list"))

    return render_template("exam_form.html", exam=exam, courses=courses_list)


@app.route("/exams/<int:exam_id>/delete", methods=["POST"])
@login_required
def delete_exam(exam_id):
    exam = db.session.get(Exam, exam_id) or abort(404)
    if current_user.role == "teacher" and exam.created_by != current_user.id:
        abort(403)
    if current_user.role not in ("admin", "manager", "teacher"):
        abort(403)
    db.session.delete(exam)
    db.session.commit()
    flash("Đã xóa bài kiểm tra.", "success")
    return redirect(url_for("exam_list"))


@app.route("/exams/<int:exam_id>/take", methods=["GET", "POST"])
@login_required
def take_exam(exam_id):
    if current_user.role != "student":
        flash("Chỉ học sinh mới được làm bài kiểm tra.", "danger")
        return redirect(url_for("exam_list"))

    exam = db.session.get(Exam, exam_id) or abort(404)

    # Check student is enrolled
    course_ids = [e.course_id for e in Enrollment.query.filter_by(student_id=current_user.id, status="active").all()]
    if exam.course_id not in course_ids:
        flash("Bạn không có quyền làm bài kiểm tra này.", "danger")
        return redirect(url_for("exam_list"))

    # Check exam status
    if exam.status_label != "open":
        flash("Bài kiểm tra chưa mở hoặc đã đóng.", "warning")
        return redirect(url_for("exam_list"))

    # Check existing submission
    existing = ExamSubmission.query.filter_by(exam_id=exam.id, student_id=current_user.id).first()
    if existing and existing.is_graded:
        flash("Bạn đã làm bài kiểm tra này rồi.", "info")
        return redirect(url_for("exam_result", exam_id=exam.id))

    questions = list(exam.questions)
    if exam.shuffle_questions:
        random.shuffle(questions)

    if exam.shuffle_answers:
        for q in questions:
            q._shuffled_answers = list(q.answers)
            random.shuffle(q._shuffled_answers)
        else:
            for q in questions:
                q._shuffled_answers = list(q.answers)
    else:
        for q in questions:
            q._shuffled_answers = list(q.answers)

    if request.method == "POST":
        submission = existing or ExamSubmission(
            exam_id=exam.id,
            student_id=current_user.id,
            started_at=dt.datetime.utcnow(),
        )
        if not existing:
            db.session.add(submission)
            db.session.flush()

        total_score = 0
        max_score = 0

        for question in exam.questions:
            max_score += question.points
            correct_ids = {a.id for a in question.answers if a.is_correct}

            if question.question_type == "multi":
                selected_ids = [int(x) for x in request.form.getlist(f"q_{question.id}")]
            else:
                val = request.form.get(f"q_{question.id}")
                selected_ids = [int(val)] if val else []

            selected_set = set(selected_ids)
            is_correct = selected_set == correct_ids and len(selected_ids) > 0
            points_earned = question.points if is_correct else 0
            total_score += points_earned

            # Remove old answer if re-submitting
            SubmissionAnswer.query.filter_by(submission_id=submission.id, question_id=question.id).delete()
            sa = SubmissionAnswer(
                submission_id=submission.id,
                question_id=question.id,
                selected_answer_ids=json.dumps(selected_ids),
                is_correct=is_correct,
                points_earned=points_earned,
            )
            db.session.add(sa)

        submission.total_score = total_score
        submission.max_score = max_score
        submission.is_graded = True
        submission.submitted_at = dt.datetime.utcnow()
        db.session.commit()
        flash(f"Đã nộp bài! Điểm: {total_score}/{max_score}", "success")
        return redirect(url_for("exam_result", exam_id=exam.id))

    return render_template("exam_take.html", exam=exam, questions=questions)


@app.route("/exams/<int:exam_id>/result")
@login_required
def exam_result(exam_id):
    exam = db.session.get(Exam, exam_id) or abort(404)

    if current_user.role == "student":
        submission = ExamSubmission.query.filter_by(exam_id=exam.id, student_id=current_user.id).first()
        if not submission:
            flash("Bạn chưa làm bài kiểm tra này.", "warning")
            return redirect(url_for("exam_list"))
        return render_template("exam_result.html", exam=exam, submission=submission, single_view=True)

    if current_user.role in ("admin", "manager"):
        submissions = ExamSubmission.query.filter_by(exam_id=exam.id).order_by(ExamSubmission.total_score.desc()).all()
    elif current_user.role == "teacher":
        if exam.created_by != current_user.id:
            abort(403)
        submissions = ExamSubmission.query.filter_by(exam_id=exam.id).order_by(ExamSubmission.total_score.desc()).all()
    else:
        abort(403)

    return render_template("exam_result.html", exam=exam, submissions=submissions, single_view=False)


# ──────────────────────── SEED / MIGRATE ────────────────────────

def seed_sample_data():
    if User.query.count():
        return

    users = [
        ("admin", "Nguyễn Văn Admin", "ADMIN001", "admin", "0912345678", "Giám đốc", 0),
        ("manager", "Trần Thị Quản Lý", "QL001", "manager", "0987654321", "Quản lý học vụ", 0),
        ("gvtoan", "Cô Lan - Toán", "GV001", "teacher", "0938123456", "Giáo viên Toán", 150000),
        ("gvanh", "Thầy Minh - Anh", "GV002", "teacher", "0978123456", "Giáo viên Anh", 200000),
        ("hs001", "Nguyễn Thị Hoa", "HS001", "student", "0123456789", "Lớp 9", 0),
        ("hs002", "Trần Văn An", "HS002", "student", "0123456790", "Lớp 10", 0),
        ("ph001", "Phụ huynh Hoa", "PH001", "parent", "0987000000", "Phụ huynh", 0),
    ]
    created = {}
    for username, fullname, code, role, phone, position, rate in users:
        user = User(
            username=username,
            fullname=fullname,
            user_code=code,
            role=role,
            phone=phone,
            position=position,
            salary_rate_per_hour=rate,
            is_active=True,
        )
        user.set_password("123456")
        db.session.add(user)
        created[username] = user
    db.session.flush()
    created["ph001"].linked_student_id = created["hs001"].id

    courses_data = [
        ("Toán 9 nâng cao", "Toán", created["gvtoan"], "P101", 1200000, "monthly", "2026-06-01", "2026-12-31"),
        ("Anh văn 10 giao tiếp", "Anh văn", created["gvanh"], "P102", 5000000, "full_course", "2026-06-15", "2026-10-15"),
    ]
    courses_created = []
    for name, subject, teacher, room, tuition, tuition_type, start, end in courses_data:
        course = Course(
            course_name=name,
            subject=subject,
            teacher_id=teacher.id,
            classroom=room,
            description=f"Chương trình {name} tại trung tâm.",
            tuition_amount=tuition,
            tuition_type=tuition_type,
            start_date=parse_date(start),
            end_date=parse_date(end),
            is_active=True,
        )
        db.session.add(course)
        courses_created.append(course)
    db.session.flush()

    schedule_rows = [
        (courses_created[0], created["gvtoan"], "P101", 0, "18:00", "19:30"),
        (courses_created[0], created["gvtoan"], "P101", 2, "18:00", "20:00"),
        (courses_created[1], created["gvanh"], "P102", 5, "08:00", "10:00"),
    ]
    for course, teacher, room, weekday, start_value, end_value in schedule_rows:
        start = parse_time(start_value)
        end = parse_time(end_value)
        db.session.add(
            Schedule(
                course_id=course.id,
                teacher_id=teacher.id,
                classroom=room,
                weekday=weekday,
                start_time=start,
                end_time=end,
                duration_hours=duration_hours(start, end),
            )
        )

    db.session.add(Enrollment(student_id=created["hs001"].id, course_id=courses_created[0].id))
    db.session.add(Enrollment(student_id=created["hs002"].id, course_id=courses_created[1].id))
    db.session.add(
        TuitionPayment(
            student_id=created["hs001"].id,
            course_id=courses_created[0].id,
            amount=1200000,
            payment_type="monthly",
            payment_date=dt.date.today(),
            status="paid",
            note="Học phí tháng hiện tại",
        )
    )
    db.session.commit()


def table_columns(table_name):
    rows = db.session.execute(db.text(f"PRAGMA table_info({table_name})")).fetchall()
    return {row[1] for row in rows}


def add_column_if_missing(table_name, column_name, ddl):
    if column_name not in table_columns(table_name):
        db.session.execute(db.text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
        db.session.commit()


def migrate_existing_sqlite_schema():
    inspector = db.inspect(db.engine)
    tables = set(inspector.get_table_names())

    if "user" in tables:
        add_column_if_missing("user", "salary_rate_per_hour", "INTEGER DEFAULT 0")
        add_column_if_missing("user", "linked_student_id", "INTEGER")

    if "course" in tables:
        add_column_if_missing("course", "course_name", "VARCHAR(120) DEFAULT ''")
        add_column_if_missing("course", "classroom", "VARCHAR(40)")
        add_column_if_missing("course", "description", "TEXT")
        add_column_if_missing("course", "tuition_amount", "INTEGER DEFAULT 0")
        add_column_if_missing("course", "tuition_type", "VARCHAR(20) DEFAULT 'monthly'")
        add_column_if_missing("course", "start_date", "DATE")
        add_column_if_missing("course", "end_date", "DATE")
        add_column_if_missing("course", "is_active", "BOOLEAN DEFAULT 1")
        columns = table_columns("course")
        if "name" in columns:
            db.session.execute(db.text("UPDATE course SET course_name = name WHERE course_name IS NULL OR course_name = ''"))
        if "summary" in columns:
            db.session.execute(db.text("UPDATE course SET description = summary WHERE description IS NULL"))
        if "fee_per_session" in columns:
            db.session.execute(db.text("UPDATE course SET tuition_amount = fee_per_session WHERE tuition_amount IS NULL OR tuition_amount = 0"))
        db.session.commit()

    if "schedule" in tables:
        add_column_if_missing("schedule", "weekday", "INTEGER DEFAULT 0")
        add_column_if_missing("schedule", "classroom", "VARCHAR(40) DEFAULT ''")
        add_column_if_missing("schedule", "duration_hours", "FLOAT DEFAULT 1.5")
        columns = table_columns("schedule")
        if "day_of_week" in columns:
            db.session.execute(db.text("UPDATE schedule SET weekday = CASE WHEN day_of_week BETWEEN 1 AND 7 THEN day_of_week - 1 ELSE 0 END"))
        if "room" in columns:
            db.session.execute(db.text("UPDATE schedule SET classroom = room WHERE classroom IS NULL OR classroom = ''"))
        db.session.commit()

    if "attendance" in tables:
        add_column_if_missing("attendance", "course_id", "INTEGER DEFAULT 1")
        add_column_if_missing("attendance", "marked_by_id", "INTEGER")
        add_column_if_missing("attendance", "updated_at", "DATETIME")
        columns = table_columns("attendance")
        if "teacher_id" in columns:
            db.session.execute(db.text("UPDATE attendance SET marked_by_id = teacher_id WHERE marked_by_id IS NULL"))
        if "schedule_id" in columns and "schedule" in tables:
            db.session.execute(
                db.text(
                    "UPDATE attendance SET course_id = "
                    "(SELECT schedule.course_id FROM schedule WHERE schedule.id = attendance.schedule_id) "
                    "WHERE course_id IS NULL OR course_id = 1"
                )
            )
        db.session.commit()

    if "teaching_record" in tables:
        add_column_if_missing("teaching_record", "confirmed_by_teacher", "BOOLEAN DEFAULT 0")
        add_column_if_missing("teaching_record", "confirmed_at", "DATETIME")


def backfill_teaching_records_from_attendance():
    pairs = (
        db.session.query(Attendance.course_id, Attendance.date)
        .filter(Attendance.status == "present")
        .distinct()
        .all()
    )
    for course_id, class_date in pairs:
        course = db.session.get(Course, course_id)
        if course:
            sync_teaching_record(course, class_date)
    db.session.commit()


def initialize_database():
    db.create_all()
    migrate_existing_sqlite_schema()
    backfill_teaching_records_from_attendance()
    seed_sample_data()


if __name__ == "__main__":
    with app.app_context():
        initialize_database()
    app.run(debug=True, host="0.0.0.0", port=5002)
