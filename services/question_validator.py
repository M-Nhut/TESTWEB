"""
Question Validator — Validates normalized questions before import.
Checks for errors, warnings, and potential duplicates.
"""

import re
import unicodedata
from services.question_normalizer import (
    VALID_DIFFICULTIES, VALID_QUESTION_TYPES, DIFFICULTY_LABELS, TYPE_LABELS,
    normalize_text, remove_diacritics
)


def _simplify_for_compare(text):
    """Simplify text for duplicate comparison: lowercase, no diacritics, no extra spaces."""
    if not text:
        return ""
    text = remove_diacritics(text.lower().strip())
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def _similarity_ratio(a, b):
    """Simple character-level similarity ratio between two strings."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    a_set = set(a.split())
    b_set = set(b.split())
    if not a_set or not b_set:
        return 0.0
    intersection = a_set & b_set
    union = a_set | b_set
    return len(intersection) / len(union) if union else 0.0


def validate_question(question, existing_texts=None):
    """
    Validate a single normalized question.
    Adds errors and warnings in-place to the question dict.
    Updates 'status' to 'error' if critical issues found.
    """
    errors = []
    warnings = []
    q_type = question.get("question_type", "single")
    if q_type == "truefalse":
        q_type = "true_false"
        question["question_type"] = "true_false"
    options = question.get("options", [])
    statements = question.get("statements", [])

    # ──── ERROR checks ────

    # 1. Empty question text
    if not normalize_text(question.get("question_text", "")):
        errors.append("Câu hỏi không có nội dung")

    # 2. Invalid question type
    if q_type not in VALID_QUESTION_TYPES:
        errors.append(
            f'Loại câu hỏi "{q_type}" không hợp lệ. '
            f'Chỉ chấp nhận: {", ".join(TYPE_LABELS.values())}'
        )

    # 3. Invalid difficulty
    diff = question.get("difficulty_level", "")
    if diff and diff not in VALID_DIFFICULTIES:
        errors.append(
            f'Mức độ "{diff}" không hợp lệ. '
            f'Chỉ chấp nhận: {", ".join(DIFFICULTY_LABELS.values())}'
        )

    # 4. Multiple choice / Single choice options validation
    if q_type in ("single", "multiple_choice"):
        if not options or len(options) == 0:
            errors.append("Không có phương án lựa chọn nào (A, B, C, D...)")
        else:
            empty_opts = [i for i, o in enumerate(options) if not normalize_text(o.get("text", ""))]
            if empty_opts:
                labels = [chr(65 + i) for i in empty_opts]
                errors.append(f'Phương án {", ".join(labels)} không có nội dung')

            correct_count = sum(1 for o in options if o.get("is_correct"))
            if correct_count == 0:
                warnings.append("Chưa chọn đáp án đúng. Giáo viên có thể bổ sung sau.")
            elif q_type == "single" and correct_count > 1:
                warnings.append(f"Câu hỏi trắc nghiệm 1 đáp án nhưng có {correct_count} đáp án đúng")

    # 5. True/False multi-statement validation
    if q_type == "true_false":
        if not statements and not options:
            errors.append("Câu Đúng/Sai chưa có các ý phát biểu (a, b, c, d)")
        else:
            missing_answers = sum(1 for s in statements if s.get("answer") is None)
            if missing_answers > 0:
                warnings.append(f"Có {missing_answers} ý Đúng/Sai chưa chọn đáp án (a, b, c, d)")

    # 6. Short Answer validation
    if q_type == "short_answer":
        correct_answers = [o for o in options if o.get("is_correct")]
        if not correct_answers and not options:
            warnings.append("Câu trả lời ngắn không có đáp án mẫu. Giáo viên sẽ chấm trực tiếp.")

    # 7. Essay validation
    if q_type == "essay":
        # Essay never requires options or answer key
        pass

    # ──── WARNING checks ────

    # 8. Duplicate check
    if existing_texts:
        simplified = _simplify_for_compare(question.get("question_text", ""))
        if simplified:
            for existing in existing_texts:
                ratio = _similarity_ratio(simplified, existing)
                if ratio > 0.85:
                    warnings.append("Có thể trùng với câu hỏi đã tồn tại trong ngân hàng")
                    break

    # Formula warnings
    if question.get("pdf_math_warning"):
        warnings.append("PDF không chứa dữ liệu công thức gốc; không đảm bảo chính xác. Cần kiểm tra lại các biểu thức toán học.")
        
    formulas = question.get("formulas", {})
    if any(not f.get("mathml") for f in formulas.values()):
        warnings.append("Có công thức phức tạp hoặc bị lỗi cấu trúc, cần giáo viên xem xét lại.")

    # 9. Points validation
    points = question.get("points", 1.0)
    if points <= 0:
        warnings.append(f"Điểm số ({points}) không hợp lệ, nên > 0")

    # 10. Low Confidence score warning
    conf = question.get("confidence_scores", {})
    if conf and isinstance(conf, dict):
        min_conf = min(conf.values()) if conf.values() else 1.0
        if min_conf < 0.6:
            warnings.append(f"Độ tin cậy trích xuất thấp ({int(min_conf*100)}%), cần giáo viên kiểm tra kỹ")

    # ──── Update status ────
    question["errors"] = errors
    question["warnings"] = warnings

    if errors:
        question["status"] = "error"
    elif warnings:
        question["status"] = "warning"
    else:
        question["status"] = "valid"

    return question


def validate_questions(questions, existing_bank_questions=None):
    """
    Validate a list of normalized questions.
    
    Args:
        questions: list of normalized question dicts
        existing_bank_questions: list of BankQuestion objects already in the bank
    
    Returns:
        dict with {
            'questions': validated list,
            'stats': {total, valid, warning, error}
        }
    """
    # Build set of existing question texts for duplicate detection
    existing_texts = set()
    if existing_bank_questions:
        for bq in existing_bank_questions:
            existing_texts.add(_simplify_for_compare(bq.question_text))

    # Also check within the import batch itself
    seen_texts = set()

    for q in questions:
        # Check for duplicates within the batch
        simplified = _simplify_for_compare(q.get("question_text", ""))
        if simplified and simplified in seen_texts:
            q.setdefault("warnings", []).append("Trùng lặp với câu hỏi khác trong cùng file import")
        elif simplified:
            seen_texts.add(simplified)

        validate_question(q, existing_texts)

    stats = {
        "total": len(questions),
        "valid": sum(1 for q in questions if q["status"] == "valid"),
        "warning": sum(1 for q in questions if q["status"] == "warning"),
        "error": sum(1 for q in questions if q["status"] == "error"),
    }

    return {"questions": questions, "stats": stats}
