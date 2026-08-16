"""
Aiken Format Parser — Parses questions written in standard Aiken format.

Format specification:
Question text (can span multiple lines or include equations)
A. First option
B. Second option
C. Third option
D. Fourth option
ANSWER: A
"""

import re


def parse_aiken(file_stream_or_path_or_str):
    """
    Parse an Aiken format text stream, file path, or string content.

    Returns:
        list of raw question dicts
    """
    if hasattr(file_stream_or_path_or_str, "read"):
        content = file_stream_or_path_or_str.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="ignore")
    elif isinstance(file_stream_or_path_or_str, str):
        if file_stream_or_path_or_str.endswith(".txt") or file_stream_or_path_or_str.endswith(".aiken"):
            with open(file_stream_or_path_or_str, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        else:
            content = file_stream_or_path_or_str
    else:
        content = str(file_stream_or_path_or_str)

    lines = [line.strip() for line in content.splitlines()]
    
    raw_questions = []
    current_text_lines = []
    current_options = []
    
    opt_pattern = re.compile(r'^([A-Z])[.:)]\s*(.*)')
    ans_pattern = re.compile(r'^ANSWER:\s*([A-Z])', re.IGNORECASE)

    for line in lines:
        if not line:
            continue

        ans_match = ans_pattern.match(line)
        if ans_match:
            correct_letter = ans_match.group(1).upper()
            q_text = " ".join(current_text_lines).strip()
            
            # Match options correctness
            for opt in current_options:
                if opt["letter"] == correct_letter:
                    opt["is_correct"] = True

            if q_text:
                raw_questions.append({
                    "question_text": q_text,
                    "question_type": "single",
                    "difficulty_level": "nhan_biet",
                    "explanation": "",
                    "options": current_options,
                    "statements": [],
                    "raw_correct": correct_letter,
                    "confidence_scores": {
                        "question": 0.98,
                        "type": 0.98,
                        "image": 1.0,
                        "answer": 0.98
                    }
                })

            current_text_lines = []
            current_options = []
            continue

        opt_match = opt_pattern.match(line)
        if opt_match:
            letter = opt_match.group(1).upper()
            opt_text = opt_match.group(2).strip()
            current_options.append({
                "letter": letter,
                "text": opt_text,
                "is_correct": False,
                "order_index": len(current_options)
            })
            continue

        # Otherwise part of question text
        current_text_lines.append(line)

    return raw_questions
