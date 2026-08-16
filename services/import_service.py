"""
Import Service — Orchestrates the lifecycle of an ImportSession.
Handles upload, parsing, preview, updating, confirmation, cancellation, and temp file cleanup.
"""

import os
import json
import uuid
import datetime as dt
from database import db
from models import ImportSession, QuestionBank, BankQuestion, BankQuestionOption
from services.question_normalizer import normalize_questions
from services.question_validator import validate_questions
from services.csv_parser import parse_csv
from services.docx_parser import parse_docx
from services.pdf_parser import parse_pdf
from services.aiken_parser import parse_aiken
from services.gift_parser import parse_gift

UPLOAD_TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "temp")


def ensure_temp_dir():
    """Ensure upload temp directory exists."""
    os.makedirs(UPLOAD_TEMP_DIR, exist_ok=True)


class ImportService:

    @staticmethod
    def create_and_process_session(user_id, file_obj, filename, bank_id=None):
        """
        1. Save uploaded file to temp storage
        2. Create ImportSession DB record
        3. Parse file depending on type (csv, docx, pdf, aiken, gift, txt)
        4. Normalize & validate questions
        5. Save parsed JSON to ImportSession
        6. Return ImportSession instance
        """
        ensure_temp_dir()
        ImportService.cleanup_expired_temp_files()
        
        file_ext = os.path.splitext(filename)[1].lower().lstrip(".")
        if file_ext not in ("csv", "docx", "pdf", "aiken", "gift", "txt"):
            raise ValueError(f"Định dạng file .{file_ext} không được hỗ trợ. Chỉ nhận CSV, DOCX, PDF, Aiken, GIFT.")

        session_id = str(uuid.uuid4())
        safe_filename = f"{session_id}_{filename}"
        temp_file_path = os.path.join(UPLOAD_TEMP_DIR, safe_filename)
        
        # Save file to disk temporarily
        file_obj.save(temp_file_path)

        session = ImportSession(
            id=session_id,
            user_id=user_id,
            bank_id=bank_id,
            filename=filename,
            file_type=file_ext,
            file_path=temp_file_path,
            status="processing"
        )
        db.session.add(session)
        db.session.commit()

        try:
            # Parse based on file type
            if file_ext == "csv":
                raw_questions = parse_csv(temp_file_path)
            elif file_ext == "docx":
                raw_questions = parse_docx(temp_file_path)
            elif file_ext == "pdf":
                raw_questions = parse_pdf(temp_file_path)
            elif file_ext == "aiken":
                raw_questions = parse_aiken(temp_file_path)
            elif file_ext == "gift":
                raw_questions = parse_gift(temp_file_path)
            elif file_ext == "txt":
                # Detect whether txt is Aiken or GIFT
                with open(temp_file_path, "r", encoding="utf-8", errors="ignore") as f:
                    txt_sample = f.read(1024)
                if "ANSWER:" in txt_sample.upper():
                    raw_questions = parse_aiken(temp_file_path)
                elif "{" in txt_sample and "}" in txt_sample:
                    raw_questions = parse_gift(temp_file_path)
                else:
                    raw_questions = parse_aiken(temp_file_path)
            else:
                raw_questions = []

            # Normalize questions
            normalized = normalize_questions(raw_questions)

            # Get existing bank questions if bank_id provided for duplicate checking
            existing_bank_questions = []
            if bank_id:
                bank = db.session.get(QuestionBank, bank_id)
                if bank:
                    existing_bank_questions = bank.questions

            # Validate questions
            val_result = validate_questions(normalized, existing_bank_questions)
            validated_questions = val_result["questions"]
            stats = val_result["stats"]

            # Update session
            session.set_parsed_questions(validated_questions)
            session.total_count = stats["total"]
            session.valid_count = stats["valid"]
            session.warning_count = stats["warning"]
            session.error_count = stats["error"]
            session.status = "preview"
            
            db.session.commit()
            return session

        except Exception as e:
            session.status = "failed"
            db.session.commit()
            raise e

    @staticmethod
    def get_session(session_id):
        """Retrieve an ImportSession by ID."""
        return db.session.get(ImportSession, session_id)

    @staticmethod
    def update_preview_question(session_id, q_index, updated_question_data):
        """Update a specific question in the parsed data preview."""
        session = db.session.get(ImportSession, session_id)
        if not session or session.status != "preview":
            raise ValueError("Phiên import không tồn tại hoặc đã đóng.")

        questions = session.get_parsed_questions()
        if q_index < 0 or q_index >= len(questions):
            raise IndexError("Chỉ số câu hỏi không hợp lệ.")

        # Merge updated data
        target_q = questions[q_index]
        target_q.update(updated_question_data)
        
        # Reset errors/warnings and re-validate single question
        target_q["errors"] = []
        target_q["warnings"] = []
        
        # Re-validate all questions to keep stats accurate
        val_result = validate_questions(questions)
        session.set_parsed_questions(val_result["questions"])
        stats = val_result["stats"]
        session.total_count = stats["total"]
        session.valid_count = stats["valid"]
        session.warning_count = stats["warning"]
        session.error_count = stats["error"]
        
        db.session.commit()
        return session

    @staticmethod
    def confirm_import(session_id, bank_id, user_id):
        """
        Confirm import: Write valid and warning questions to database inside a transaction.
        """
        session = db.session.get(ImportSession, session_id)
        if not session:
            raise ValueError("Phiên import không tồn tại.")
        if session.status != "preview":
            raise ValueError("Phiên import đã được xác nhận hoặc đã hủy.")

        bank = db.session.get(QuestionBank, bank_id)
        if not bank:
            raise ValueError("Ngân hàng câu hỏi không tồn tại.")

        questions = session.get_parsed_questions()
        imported_count = 0

        try:
            # Transaction block
            for q_data in questions:
                # Skip error questions
                if q_data.get("status") == "error":
                    continue

                q_type = q_data.get("question_type", "single")
                if q_type == "truefalse":
                    q_type = "true_false"

                conf_scores = q_data.get("confidence_scores")
                conf_json = json.dumps(conf_scores) if isinstance(conf_scores, dict) else None

                bq = BankQuestion(
                    bank_id=bank.id,
                    question_text=q_data["question_text"],
                    context=q_data.get("context", ""),
                    image_url=q_data.get("image_url", ""),
                    question_type=q_type,
                    difficulty_level=q_data.get("difficulty_level", "nhan_biet"),
                    points=float(q_data.get("points", 1.0)),
                    explanation=q_data.get("explanation", ""),
                    confidence_scores=conf_json,
                    subject=bank.subject,
                    grade=bank.grade,
                    topic=bank.topic,
                    created_by=user_id
                )
                db.session.add(bq)
                db.session.flush() # get bq.id

                # Save options (for single, multiple_choice, short_answer)
                for idx, opt_data in enumerate(q_data.get("options", [])):
                    opt = BankQuestionOption(
                        question_id=bq.id,
                        option_text=opt_data["text"],
                        is_correct=bool(opt_data.get("is_correct", False)),
                        order_index=idx
                    )
                    db.session.add(opt)

                # Save statements (for true_false)
                for idx, stmt_data in enumerate(q_data.get("statements", [])):
                    stmt_label = stmt_data.get("id", chr(97 + idx))
                    stmt_text = f"{stmt_label}) {stmt_data['text']}" if not stmt_data['text'].startswith(f"{stmt_label})") else stmt_data['text']
                    opt = BankQuestionOption(
                        question_id=bq.id,
                        option_text=stmt_text,
                        is_correct=bool(stmt_data.get("answer", False)),
                        order_index=idx
                    )
                    db.session.add(opt)

                imported_count += 1

            session.status = "confirmed"
            db.session.commit()

            # Clean up temp file
            ImportService.cleanup_temp_file(session)

            return {
                "success": True,
                "imported_count": imported_count,
                "total_count": len(questions),
                "bank_id": bank.id,
                "bank_name": bank.name
            }

        except Exception as e:
            db.session.rollback()
            session.status = "failed"
            db.session.commit()
            raise e

    @staticmethod
    def cancel_session(session_id):
        """Cancel an import session and clean up temp files."""
        session = db.session.get(ImportSession, session_id)
        if session:
            ImportService.cleanup_temp_file(session)
            db.session.delete(session)
            db.session.commit()
        return True

    @staticmethod
    def cleanup_temp_file(session):
        """Remove temp file and extracted images on disk."""
        if not session:
            return
            
        # 1. Delete main uploaded file
        if session.file_path and os.path.exists(session.file_path):
            try:
                os.remove(session.file_path)
            except OSError:
                pass
                
        # 2. Delete any extracted temp images for this session
        try:
            temp_dir = os.path.join("static", "uploads", "import_temp", str(session.id))
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

    @staticmethod
    def cleanup_expired_temp_files(max_age_minutes=30):
        """Remove orphan files in uploads/temp older than max_age_minutes."""
        try:
            ensure_temp_dir()
            now = dt.datetime.now().timestamp()
            max_age_sec = max_age_minutes * 60
            for fname in os.listdir(UPLOAD_TEMP_DIR):
                fpath = os.path.join(UPLOAD_TEMP_DIR, fname)
                if os.path.isfile(fpath):
                    file_age = now - os.path.getmtime(fpath)
                    if file_age > max_age_sec:
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
        except Exception:
            pass

    @staticmethod
    def cleanup_orphan_question_images():
        """Remove image files in static/uploads/questions that are not referenced anywhere in DB."""
        try:
            from database import db
            from models import BankQuestion, BankQuestionOption, ExamQuestion, ImportSession
            
            referenced_files = set()
            
            # 1. Bank questions & options
            for bq in db.session.query(BankQuestion).all():
                if bq.image_url:
                    referenced_files.add(os.path.basename(bq.image_url))
                for text_field in [bq.question_text, bq.explanation, bq.context]:
                    if text_field:
                        for img_src in re.findall(r'/static/uploads/questions/([^\"\'\s>)]+)', text_field):
                            referenced_files.add(os.path.basename(img_src))
                            
            for opt in db.session.query(BankQuestionOption).all():
                if hasattr(opt, 'image_url') and opt.image_url:
                    referenced_files.add(os.path.basename(opt.image_url))
                if opt.option_text:
                    for img_src in re.findall(r'/static/uploads/questions/([^\"\'\s>)]+)', opt.option_text):
                        referenced_files.add(os.path.basename(img_src))

            # 2. Exam questions
            for eq in db.session.query(ExamQuestion).all():
                if eq.image_url:
                    referenced_files.add(os.path.basename(eq.image_url))
                for text_field in [eq.question_text, eq.explanation, eq.context]:
                    if text_field:
                        for img_src in re.findall(r'/static/uploads/questions/([^\"\'\s>)]+)', text_field):
                            referenced_files.add(os.path.basename(img_src))

            # 3. Active import sessions
            for s in db.session.query(ImportSession).all():
                for q in s.get_parsed_questions():
                    if q.get('image_url'):
                        referenced_files.add(os.path.basename(q['image_url']))
                    for field in [q.get('question_text', ''), q.get('explanation', ''), q.get('context', '')]:
                        if field:
                            for img_src in re.findall(r'/static/uploads/questions/([^\"\'\s>)]+)', field):
                                referenced_files.add(os.path.basename(img_src))

            # 4. Clean up unreferenced files in static/uploads/questions
            base_dir = os.path.dirname(os.path.dirname(__file__))
            upload_dir = os.path.join(base_dir, "static", "uploads", "questions")
            if not os.path.exists(upload_dir):
                return
                
            all_files = set(os.listdir(upload_dir))
            orphan_files = all_files - referenced_files
            
            for fname in orphan_files:
                fpath = os.path.join(upload_dir, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[ImportService] Orphan image cleanup error: {e}")
