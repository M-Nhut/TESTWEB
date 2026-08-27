import datetime as dt
import json
import uuid
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from database import db

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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class Enrollment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    status = db.Column(db.String(20), default="active")
    enrolled_at = db.Column(db.DateTime, default=dt.datetime.utcnow)

    student = db.relationship("User", back_populates="enrollments", foreign_keys=[student_id])
    course = db.relationship("Course", back_populates="enrollments")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


# ──────────────────────── QUESTION BANK MODELS ────────────────────────

class QuestionBank(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    subject = db.Column(db.String(80), nullable=False)
    grade = db.Column(db.String(40))
    topic = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    creator = db.relationship("User", foreign_keys=[created_by])
    questions = db.relationship("BankQuestion", back_populates="bank", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def question_count(self):
        return len(self.questions)

    def stats_by_difficulty(self):
        counts = {"nhan_biet": 0, "van_dung": 0, "van_dung_cao": 0}
        for q in self.questions:
            if q.difficulty_level in counts:
                counts[q.difficulty_level] += 1
        return counts

    def stats_by_type(self):
        counts = {"single": 0, "multiple_choice": 0, "true_false": 0, "short_answer": 0, "essay": 0}
        for q in self.questions:
            qtype = "true_false" if q.question_type == "truefalse" else q.question_type
            if qtype in counts:
                counts[qtype] += 1
            else:
                counts["single"] += 1
        return counts


class BankQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bank_id = db.Column(db.Integer, db.ForeignKey("question_bank.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    context = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    question_type = db.Column(db.String(30), nullable=False, default="single")  # single, multiple_choice, true_false, short_answer, essay
    difficulty_level = db.Column(db.String(20), nullable=False, default="nhan_biet")  # nhan_biet, van_dung, van_dung_cao
    points = db.Column(db.Float, default=1.0)
    explanation = db.Column(db.Text)
    subject = db.Column(db.String(80))
    grade = db.Column(db.String(40))
    topic = db.Column(db.String(200))
    confidence_scores = db.Column(db.Text, nullable=True)  # JSON string
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    bank = db.relationship("QuestionBank", back_populates="questions")
    creator = db.relationship("User", foreign_keys=[created_by])
    options = db.relationship("BankQuestionOption", back_populates="question", cascade="all, delete-orphan", order_by="BankQuestionOption.order_index")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self):
        opts = [opt.to_dict() for opt in self.options]
        stmts = []
        if self.question_type in ("true_false", "truefalse"):
            for opt in self.options:
                text = opt.option_text
                stmt_id = text[:1].lower() if text and len(text) > 1 and text[1] in (")", ".", ":") else ""
                stmt_body = text[2:].strip() if stmt_id else text
                stmts.append({
                    "id": stmt_id,
                    "text": stmt_body,
                    "full_text": text,
                    "answer": opt.is_correct
                })
        return {
            "id": self.id,
            "bank_id": self.bank_id,
            "question_text": self.question_text,
            "context": self.context or "",
            "image_url": self.image_url or "",
            "question_type": "true_false" if self.question_type == "truefalse" else self.question_type,
            "difficulty_level": self.difficulty_level,
            "points": self.points,
            "explanation": self.explanation or "",
            "options": opts,
            "statements": stmts
        }


class BankQuestionOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("bank_question.id"), nullable=False)
    option_text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, default=False)
    order_index = db.Column(db.Integer, default=0)

    question = db.relationship("BankQuestion", back_populates="options")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_dict(self):
        return {
            "id": self.id,
            "option_text": self.option_text,
            "is_correct": self.is_correct,
            "order_index": self.order_index
        }


# ──────────────────────── IMPORT SESSION ────────────────────────

class ImportSession(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    bank_id = db.Column(db.Integer, db.ForeignKey("question_bank.id"), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(10), nullable=False)  # csv, docx, pdf
    file_path = db.Column(db.String(500))
    status = db.Column(db.String(20), nullable=False, default="uploaded")  # uploaded, processing, preview, confirmed, cancelled, failed
    parsed_data = db.Column(db.Text)  # JSON: list of normalized questions
    valid_count = db.Column(db.Integer, default=0)
    warning_count = db.Column(db.Integer, default=0)
    error_count = db.Column(db.Integer, default=0)
    total_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    expires_at = db.Column(db.DateTime)

    user = db.relationship("User", foreign_keys=[user_id])
    bank = db.relationship("QuestionBank", foreign_keys=[bank_id])

    def __init__(self, **kwargs):
        if "expires_at" not in kwargs:
            kwargs["expires_at"] = dt.datetime.utcnow() + dt.timedelta(hours=2)
        super().__init__(**kwargs)

    def get_parsed_questions(self):
        try:
            return json.loads(self.parsed_data or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def set_parsed_questions(self, questions):
        self.parsed_data = json.dumps(questions, ensure_ascii=False)


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
    # New fields for question bank integration
    question_bank_id = db.Column(db.Integer, db.ForeignKey("question_bank.id"), nullable=True)
    exam_type = db.Column(db.String(20), default="exam")  # exam, practice
    exam_category = db.Column(db.String(50), default="Kiểm tra thường kỳ")  # Kiểm tra thường kỳ, Kiểm tra giữa kỳ, Kiểm tra cuối kỳ
    total_questions = db.Column(db.Integer, nullable=True)
    difficulty_config = db.Column(db.Text, nullable=True)  # JSON: {"nhan_biet":40,"van_dung":30,"van_dung_cao":30}
    question_type_config = db.Column(db.Text, nullable=True)  # JSON: {"single":10,"truefalse":5,"short_answer":5}

    course = db.relationship("Course")
    creator = db.relationship("User", foreign_keys=[created_by])
    question_bank = db.relationship("QuestionBank", foreign_keys=[question_bank_id])
    questions = db.relationship("ExamQuestion", back_populates="exam", cascade="all, delete-orphan", order_by="ExamQuestion.order_index")
    submissions = db.relationship("ExamSubmission", back_populates="exam", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def total_points(self):
        return sum(q.points for q in self.questions)

    @property
    def question_count(self):
        return len(self.questions)

    @property
    def status_label(self):
        now = dt.datetime.now()
        if not self.is_active:
            return "closed"
        if self.start_time and now < self.start_time:
            return "upcoming"
        if self.end_time and now > self.end_time:
            return "closed"
        return "open"

    def get_difficulty_config(self):
        try:
            return json.loads(self.difficulty_config or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_question_type_config(self):
        try:
            return json.loads(self.question_type_config or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}


class ExamQuestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exam.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    context = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    question_type = db.Column(db.String(30), nullable=False, default="single")  # single, multiple_choice, true_false, short_answer, essay
    points = db.Column(db.Float, default=1.0)
    order_index = db.Column(db.Integer, default=0)
    # New fields
    bank_question_id = db.Column(db.Integer, db.ForeignKey("bank_question.id"), nullable=True)
    difficulty_level = db.Column(db.String(20), nullable=True)  # nhan_biet, van_dung, van_dung_cao
    explanation = db.Column(db.Text, nullable=True)

    exam = db.relationship("Exam", back_populates="questions")
    answers = db.relationship("ExamAnswer", back_populates="question", cascade="all, delete-orphan", order_by="ExamAnswer.id")
    bank_question = db.relationship("BankQuestion", foreign_keys=[bank_question_id])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class ExamAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("exam_question.id"), nullable=False)
    answer_text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, default=False)

    question = db.relationship("ExamQuestion", back_populates="answers")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class ExamSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exam.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    started_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)
    total_score = db.Column(db.Float, default=0)
    max_score = db.Column(db.Float, default=0)
    is_graded = db.Column(db.Boolean, default=False)
    # New fields
    exam_type = db.Column(db.String(20), default="exam")  # exam, practice
    time_spent_seconds = db.Column(db.Integer, nullable=True)
    correct_count = db.Column(db.Integer, default=0)
    wrong_count = db.Column(db.Integer, default=0)

    exam = db.relationship("Exam", back_populates="submissions")
    student = db.relationship("User", foreign_keys=[student_id])
    answers = db.relationship("SubmissionAnswer", back_populates="submission", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def percentage(self):
        if self.max_score == 0:
            return 0
        return round(self.total_score / self.max_score * 100, 1)




class SubmissionAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("exam_submission.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("exam_question.id"), nullable=False)
    selected_answer_ids = db.Column(db.Text, default="[]")  # JSON array of answer IDs
    is_correct = db.Column(db.Boolean, default=False)
    points_earned = db.Column(db.Float, default=0)
    # New fields
    answer_text = db.Column(db.Text, nullable=True)  # For short_answer type
    time_spent_seconds = db.Column(db.Integer, nullable=True)

    submission = db.relationship("ExamSubmission", back_populates="answers")
    question = db.relationship("ExamQuestion")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_selected_ids(self):
        try:
            return json.loads(self.selected_answer_ids or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def get_answer_payload(self):
        try:
            val = json.loads(self.answer_text or "{}")
            if isinstance(val, dict):
                return val
            return {"text": str(val)}
        except (json.JSONDecodeError, TypeError):
            return {"text": self.answer_text or ""}


# ──────────────────────── STUDENT PERFORMANCE ────────────────────────

class StudentPerformance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    subject = db.Column(db.String(80), nullable=False)
    topic = db.Column(db.String(200), nullable=True)
    total_attempts = db.Column(db.Integer, default=0)
    avg_score = db.Column(db.Float, default=0)
    best_score = db.Column(db.Float, default=0)
    worst_score = db.Column(db.Float, default=10)
    latest_score = db.Column(db.Float, default=0)
    score_trend = db.Column(db.String(20), default="stable")  # improving, declining, stable
    accuracy_rate = db.Column(db.Float, default=0)
    nhan_biet_accuracy = db.Column(db.Float, default=0)
    van_dung_accuracy = db.Column(db.Float, default=0)
    van_dung_cao_accuracy = db.Column(db.Float, default=0)
    single_accuracy = db.Column(db.Float, default=0)
    truefalse_accuracy = db.Column(db.Float, default=0)
    short_answer_accuracy = db.Column(db.Float, default=0)
    weak_topics = db.Column(db.Text, default="[]")  # JSON array
    strong_topics = db.Column(db.Text, default="[]")  # JSON array
    adaptive_difficulty = db.Column(db.String(20), default="standard")  # reinforce, standard, challenge
    updated_at = db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    student = db.relationship("User", foreign_keys=[student_id])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def get_weak_topics(self):
        try:
            return json.loads(self.weak_topics or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def get_strong_topics(self):
        try:
            return json.loads(self.strong_topics or "[]")
        except (json.JSONDecodeError, TypeError):
            return []


# ──────────────────────── FORMULA ASSETS ────────────────────────

class FormulaAsset(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mtef_data = db.Column(db.Text, nullable=True)  # zlib-compressed base64 MTEF
    mathml = db.Column(db.Text, nullable=True)
    latex = db.Column(db.Text, nullable=True)
    source_format = db.Column(db.String(20), nullable=True)  # OMML, MathType, LaTeX, PDF
    converter_name = db.Column(db.String(100), nullable=True)
    converter_version = db.Column(db.String(50), nullable=True)
    content_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)  # SHA-256
    parse_confidence = db.Column(db.Float, default=1.0)
    conversion_status = db.Column(db.String(20), default="pending")  # pending, converted, fallback_svg, failed
    verification_status = db.Column(db.String(20), default="verified")  # verified, needs_review, failed
    svg_cache_key = db.Column(db.String(100), nullable=True)  # filesystem/object storage key, no SVG binary in DB
    created_at = db.Column(db.DateTime, default=dt.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def to_api_dict(self):
        """Return dict safe for API responses (no MTEF binary data)."""
        return {
            "id": self.id,
            "mathml": self.mathml,
            "latex": self.latex,
            "source_format": self.source_format,
            "conversion_status": self.conversion_status,
            "verification_status": self.verification_status,
            "svg_cache_key": self.svg_cache_key,
        }

