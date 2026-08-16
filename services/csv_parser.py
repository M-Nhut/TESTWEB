"""
CSV Question Parser — Parses question banks from CSV files.
Supports UTF-8 and UTF-8-BOM encodings.
"""

import csv
import io
from services.question_normalizer import normalize_question


def parse_csv(file_stream_or_path):
    """
    Parse a CSV file/stream containing questions.
    
    Expected CSV Header:
    question_text,question_type,difficulty_level,option_a,option_b,option_c,option_d,correct_answer,explanation
    
    Returns:
        list of raw question dicts ready for normalization
    """
    raw_questions = []
    
    # Handle string path vs file-like object
    if isinstance(file_stream_or_path, str):
        with open(file_stream_or_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
    else:
        content = file_stream_or_path.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8-sig", errors="replace")
            
    reader = csv.DictReader(io.StringIO(content))
    
    # Normalize header names (lowercase, strip whitespace)
    if reader.fieldnames:
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames if name]
        
    for row_idx, row in enumerate(reader, start=2): # Line 2 is first data row
        question_text = row.get("question_text", "").strip()
        if not question_text:
            continue
            
        q_type = row.get("question_type", "").strip()
        diff = row.get("difficulty_level", "").strip()
        exp = row.get("explanation", "").strip()
        points = float(row.get("points", 1.0) or 1.0)
        
        correct_raw = row.get("correct_answer", "").strip().upper()
        
        # Collect options
        options = []
        option_keys = [("option_a", "A"), ("option_b", "B"), ("option_c", "C"), ("option_d", "D"), ("option_e", "E")]
        
        has_named_options = False
        for opt_key, letter in option_keys:
            if opt_key in row:
                has_named_options = True
                text = row.get(opt_key, "").strip()
                if text:
                    is_correct = False
                    if correct_raw == letter:
                        is_correct = True
                    elif correct_raw == text:
                        is_correct = True
                    options.append({
                        "text": text,
                        "is_correct": is_correct,
                        "order_index": len(options)
                    })
                    
        # If short_answer or options provided in correct_answer string
        if not has_named_options or q_type in ("short_answer", "trả lời ngắn"):
            if correct_raw and not options:
                # Multiple valid answers separated by |
                answers = [a.strip() for a in correct_raw.split("|") if a.strip()]
                for ans in answers:
                    options.append({
                        "text": ans,
                        "is_correct": True,
                        "order_index": len(options)
                    })
                    
        raw_questions.append({
            "question_text": question_text,
            "question_type": q_type,
            "difficulty_level": diff,
            "points": points,
            "explanation": exp,
            "options": options,
            "source_line": row_idx
        })
        
    return raw_questions
