"""
Import Service — Orchestrates the lifecycle of an ImportSession.
Handles upload, parsing, preview, updating, confirmation, cancellation, and temp file cleanup.

MathType production pipeline:
  - After parser extracts MTEF, create/get FormulaAsset by content_hash (deduplicate).
  - If embedded MathML/LaTeX metadata exists → save immediately, mark converted.
  - If no metadata → create FormulaAsset as pending, queue worker job after confirm.
  - Never block import for conversion; questions import with pending assets.
  - Remap temp UUIDs to FormulaAsset.id in question_text, context, options, statements, explanation.
"""

import hashlib
import os
import json
import re
import uuid
import datetime as dt
from database import db
from models import ImportSession, QuestionBank, BankQuestion, BankQuestionOption, FormulaAsset
from services.question_normalizer import normalize_questions
from services.question_validator import validate_questions
from services.docx_parser import parse_docx
from services.pdf_parser import parse_pdf

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
        
        ALLOWED_IMPORT_EXTENSIONS = {"docx", "pdf", "tex", "latex"}
        file_ext = os.path.splitext(filename)[1].lower().lstrip(".")
        if file_ext not in ALLOWED_IMPORT_EXTENSIONS:
            raise ValueError(f"Định dạng file .{file_ext} không được hỗ trợ. Chỉ nhận DOCX, PDF, LaTeX (.tex, .latex).")

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
            if file_ext == "docx":
                raw_questions = parse_docx(temp_file_path)
            elif file_ext == "pdf":
                raw_questions = parse_pdf(temp_file_path)
            elif file_ext in ("tex", "latex"):
                from services.latex_parser import parse_latex
                raw_questions = parse_latex(temp_file_path)
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
        
        FormulaAsset handling:
          - Deduplicate by content_hash (SHA-256).
          - MathType formulas with metadata → conversion_status='converted', verification_status='verified'.
          - MathType formulas without metadata → conversion_status='pending', verification_status='needs_review'.
          - OMML formulas → conversion_status='converted', verification_status='verified'.
          - Remap temp UUIDs → FormulaAsset.id in all text fields.
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

                # Process formulas and remap UUIDs → FormulaAsset IDs
                uuid_map = {}
                formulas_data = q_data.get("formulas", {})
                for old_uuid, f_data in formulas_data.items():
                    # Compute content_hash if not already present
                    content_hash = f_data.get("content_hash")
                    if not content_hash:
                        # Generate hash from available data
                        hash_source = f_data.get("latex") or f_data.get("mathml") or f_data.get("mtef_data") or old_uuid
                        content_hash = hashlib.sha256(hash_source.encode("utf-8") if isinstance(hash_source, str) else hash_source).hexdigest()
                        
                    # Deduplicate by content_hash
                    existing_asset = db.session.query(FormulaAsset).filter_by(content_hash=content_hash).first()
                    if existing_asset:
                        # A previous import may have created a pending asset
                        # before SVG preview extraction was available. Enrich
                        # it so every later bank/exam view can display the
                        # formula immediately after confirmation.
                        preview_url = f_data.get("preview_url")
                        if preview_url and not existing_asset.svg_cache_key:
                            existing_asset.svg_cache_key = preview_url

                        incoming_status = f_data.get("conversion_status")
                        if incoming_status == "converted":
                            if f_data.get("mathml"):
                                existing_asset.mathml = f_data["mathml"]
                            if f_data.get("latex"):
                                existing_asset.latex = f_data["latex"]
                            existing_asset.conversion_status = "converted"
                            if not f_data.get("needs_review", False):
                                existing_asset.verification_status = "verified"
                        uuid_map[old_uuid] = existing_asset.id
                    else:
                        # Determine conversion and verification status
                        conversion_status = f_data.get("conversion_status", "pending")
                        needs_review = f_data.get("needs_review", False)
                        
                        if conversion_status == "converted" and not needs_review:
                            verification_status = "verified"
                        elif needs_review:
                            verification_status = "needs_review"
                        else:
                            verification_status = "needs_review"
                        
                        new_asset = FormulaAsset(
                            content_hash=content_hash,
                            mathml=f_data.get("mathml"),
                            latex=f_data.get("latex"),
                            mtef_data=f_data.get("mtef_data"),
                            converter_name=f_data.get("converter_name"),
                            converter_version=f_data.get("converter_version"),
                            source_format=f_data.get("source_format"),
                            parse_confidence=f_data.get("parse_confidence", 1.0),
                            conversion_status=conversion_status,
                            verification_status=verification_status,
                            svg_cache_key=f_data.get("preview_url"),
                        )
                        
                        db.session.add(new_asset)
                        db.session.flush()  # get new_asset.id
                        uuid_map[old_uuid] = new_asset.id

                # Helper to remap UUIDs in text
                def remap_text(text):
                    if not text:
                        return text
                    for old_u, new_u in uuid_map.items():
                        text = text.replace(f"[[formula:{old_u}]]", f"[[formula:{new_u}]]")
                    return text

                q_type = q_data.get("question_type", "single")
                if q_type == "truefalse":
                    q_type = "true_false"

                conf_scores = q_data.get("confidence_scores")
                conf_json = json.dumps(conf_scores) if isinstance(conf_scores, dict) else None

                bq = BankQuestion(
                    bank_id=bank.id,
                    question_text=remap_text(q_data.get("question_text", "")),
                    context=remap_text(q_data.get("context", "")),
                    image_url=q_data.get("image_url", ""),
                    question_type=q_type,
                    difficulty_level=q_data.get("difficulty_level", "nhan_biet"),
                    points=float(q_data.get("points", 1.0)),
                    explanation=remap_text(q_data.get("explanation", "")),
                    confidence_scores=conf_json,
                    subject=bank.subject,
                    grade=bank.grade,
                    topic=bank.topic,
                    created_by=user_id
                )
                db.session.add(bq)
                db.session.flush()  # get bq.id

                # Save options (for single, multiple_choice, short_answer)
                for idx, opt_data in enumerate(q_data.get("options", [])):
                    opt = BankQuestionOption(
                        question_id=bq.id,
                        option_text=remap_text(opt_data["text"]),
                        is_correct=bool(opt_data.get("is_correct", False)),
                        order_index=idx
                    )
                    db.session.add(opt)

                # Save statements (for true_false)
                for idx, stmt_data in enumerate(q_data.get("statements", [])):
                    stmt_label = stmt_data.get("id", chr(97 + idx))
                    stmt_text_raw = stmt_data['text']
                    stmt_text = f"{stmt_label}) {stmt_text_raw}" if not stmt_text_raw.startswith(f"{stmt_label})") else stmt_text_raw
                    opt = BankQuestionOption(
                        question_id=bq.id,
                        option_text=remap_text(stmt_text),
                        is_correct=bool(stmt_data.get("answer", False)),
                        order_index=idx
                    )
                    db.session.add(opt)

                imported_count += 1

            session.status = "confirmed"
            db.session.commit()

            # Queue pending formula conversions (non-blocking)
            ImportService._queue_pending_conversions()

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
    def _queue_pending_conversions():
        """
        Queue pending MathType formula conversions.
        Called after successful import confirmation.
        
        In production: this would push jobs to a task queue (Celery, RQ, etc.)
        For now: attempt conversion via worker client if available.
        """
        try:
            from services.mathtype_converter import MathTypeWorkerClient
            client = MathTypeWorkerClient()
            
            if not client.is_available:
                # Worker not configured - assets stay pending
                return
            
            pending_assets = db.session.query(FormulaAsset).filter_by(
                conversion_status="pending",
                source_format="MathType"
            ).all()
            
            for asset in pending_assets:
                if not asset.mtef_data:
                    continue
                try:
                    result = client.convert(asset.mtef_data, asset.content_hash)
                    if result.get("status") == "converted":
                        asset.mathml = result.get("mathml")
                        asset.latex = result.get("latex")
                        asset.converter_name = result.get("converter_name")
                        asset.converter_version = result.get("converter_version")
                        asset.conversion_status = "converted"
                        asset.verification_status = "verified"
                        if result.get("svg_url"):
                            asset.svg_cache_key = result.get("svg_url")
                    # If still pending, leave as-is for retry
                except Exception as e:
                    print(f"[ImportService] Worker conversion error for {asset.id}: {e}")
                    
            db.session.commit()
        except Exception as e:
            print(f"[ImportService] Queue pending conversions error: {e}")

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
                        for img_src in re.findall(r'/static/uploads/questions/([^\"\'\\s>)]+)', text_field):
                            referenced_files.add(os.path.basename(img_src))
                            
            for opt in db.session.query(BankQuestionOption).all():
                if hasattr(opt, 'image_url') and opt.image_url:
                    referenced_files.add(os.path.basename(opt.image_url))
                if opt.option_text:
                    for img_src in re.findall(r'/static/uploads/questions/([^\"\'\\s>)]+)', opt.option_text):
                        referenced_files.add(os.path.basename(img_src))

            # 2. Exam questions
            for eq in db.session.query(ExamQuestion).all():
                if eq.image_url:
                    referenced_files.add(os.path.basename(eq.image_url))
                for text_field in [eq.question_text, eq.explanation, eq.context]:
                    if text_field:
                        for img_src in re.findall(r'/static/uploads/questions/([^\"\'\\s>)]+)', text_field):
                            referenced_files.add(os.path.basename(img_src))

            # 3. Active import sessions
            for s in db.session.query(ImportSession).all():
                for q in s.get_parsed_questions():
                    if q.get('image_url'):
                        referenced_files.add(os.path.basename(q['image_url']))
                    for field in [q.get('question_text', ''), q.get('explanation', ''), q.get('context', '')]:
                        if field:
                            for img_src in re.findall(r'/static/uploads/questions/([^\"\'\\s>)]+)', field):
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
