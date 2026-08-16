"""
GIFT Format Parser — Parses questions written in Moodle GIFT format.

Supports:
- Single choice: Question {=Correct ~Wrong1 ~Wrong2}
- Multiple answer: Question {~%50%Correct1 ~%50%Correct2 ~-100%Wrong}
- True/False: Question {TRUE} or {FALSE} or {T} or {F}
- Short Answer: Question {=Answer1 =Answer2}
- Essay: Question {}
"""

import re


def parse_gift(file_stream_or_path_or_str):
    """
    Parse a GIFT format text stream, file path, or string content.

    Returns:
        list of raw question dicts
    """
    if hasattr(file_stream_or_path_or_str, "read"):
        content = file_stream_or_path_or_str.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="ignore")
    elif isinstance(file_stream_or_path_or_str, str):
        if file_stream_or_path_or_str.endswith(".txt") or file_stream_or_path_or_str.endswith(".gift"):
            with open(file_stream_or_path_or_str, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        else:
            content = file_stream_or_path_or_str
    else:
        content = str(file_stream_or_path_or_str)

    raw_questions = []
    
    # Split blocks by blank lines or category lines
    blocks = re.split(r'\n\s*\n', content)

    for block in blocks:
        block = block.strip()
        if not block or block.startswith("//") or block.startswith("$CATEGORY"):
            continue

        # Extract title if present ::Title::
        title_match = re.match(r'^::(.*?)::\s*(.*)', block, re.DOTALL)
        if title_match:
            q_text_body = title_match.group(2).strip()
        else:
            q_text_body = block

        # Find GIFT answer block inside { ... }
        ans_block_match = re.search(r'\{(.*?)\}', q_text_body, re.DOTALL)
        if not ans_block_match:
            continue

        ans_content = ans_block_match.group(1).strip()
        
        # Replace answer block with clean question text
        question_text = re.sub(r'\{.*?\}', '', q_text_body).strip()
        # Remove comment lines
        question_text = "\n".join([l for l in question_text.splitlines() if not l.strip().startswith("//")]).strip()

        if not question_text:
            continue

        # 1. Essay: empty braces {}
        if not ans_content:
            raw_questions.append({
                "question_text": question_text,
                "question_type": "essay",
                "difficulty_level": "nhan_biet",
                "options": [],
                "statements": [],
                "explanation": ""
            })
            continue

        # 2. True / False: {TRUE}, {FALSE}, {T}, {F}
        tf_clean = ans_content.upper()
        if tf_clean in ("TRUE", "FALSE", "T", "F"):
            is_true = tf_clean in ("TRUE", "T")
            raw_questions.append({
                "question_text": question_text,
                "question_type": "true_false",
                "difficulty_level": "nhan_biet",
                "options": [],
                "statements": [
                    {"id": "a", "text": "Mệnh đề chính", "answer": is_true}
                ],
                "explanation": ""
            })
            continue

        # 3. Short Answer: only contains = (no ~)
        if "=" in ans_content and "~" not in ans_content:
            answers = [a.strip() for a in ans_content.split("=") if a.strip()]
            options = [{"text": a, "is_correct": True, "order_index": i} for i, a in enumerate(answers)]
            raw_questions.append({
                "question_text": question_text,
                "question_type": "short_answer",
                "difficulty_level": "nhan_biet",
                "options": options,
                "statements": [],
                "explanation": ""
            })
            continue

        # 4. Multiple choice / Multiple answer: contains ~ or =
        # Parse items starting with ~ or =
        items = re.findall(r'([=~][^=~]*)', ans_content)
        options = []
        correct_count = 0

        for idx, item in enumerate(items):
            item = item.strip()
            prefix = item[0]
            val = item[1:].strip()
            
            # Check for weight e.g. ~%50%Correct
            weight_match = re.match(r'^%(-?\d+(?:\.\d+)?)%(.*)', val)
            if weight_match:
                weight = float(weight_match.group(1))
                opt_text = weight_match.group(2).strip()
                is_corr = (weight > 0)
            else:
                opt_text = val
                is_corr = (prefix == "=")

            if is_corr:
                correct_count += 1

            options.append({
                "letter": chr(65 + idx),
                "text": opt_text,
                "is_correct": is_corr,
                "order_index": idx
            })

        q_type = "multiple_choice" if correct_count > 1 else "single"
        raw_questions.append({
            "question_text": question_text,
            "question_type": q_type,
            "difficulty_level": "nhan_biet",
            "options": options,
            "statements": [],
            "explanation": ""
        })

    return raw_questions
