"""
PDF Question Parser — Document Understanding Parser for Question Bank.
Extracts questions, context, options, true/false statements (a,b,c,d), images, and math formulas.
Filters out non-question content (Theory sections, Table of Contents, Standalone Answer Keys, Solutions).
"""

import os
import re
import uuid

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    try:
        import pymupdf as fitz
        HAS_FITZ = True
    except ImportError:
        HAS_FITZ = False

try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


def parse_pdf(file_stream_or_path, temp_img_dir=None):
    """
    Parse a PDF file to extract actual questions.
    Returns list of normalized raw question dicts.
    """
    if not HAS_FITZ:
        raise RuntimeError("Thư viện 'PyMuPDF' (fitz) chưa được cài đặt.")

    if isinstance(file_stream_or_path, str):
        doc = fitz.open(file_stream_or_path)
    else:
        file_bytes = file_stream_or_path.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")

    # Extract images embedded in PDF pages
    extracted_images = extract_images_from_pdf(doc)

    full_text_lines = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        
        # Scanned PDF fallback
        if len(text.strip()) < 30 and HAS_OCR:
            try:
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text = pytesseract.image_to_string(img, lang="vie")
            except Exception:
                pass
                
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in lines:
            full_text_lines.append({
                "text": line,
                "page": page_num
            })

    raw_questions = _parse_pdf_document_structure(full_text_lines, extracted_images)
    return raw_questions


def extract_images_from_pdf(doc, output_dir=None):
    """Extract embedded images from PDF pages and save to static uploads."""
    if output_dir is None:
        basedir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_dir = os.path.join(basedir, "static", "uploads", "questions")
    os.makedirs(output_dir, exist_ok=True)
    
    extracted_images = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            try:
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image.get("ext", "png")
                filename = f"img_{uuid.uuid4().hex[:10]}_p{page_num+1}_{img_index+1}.{image_ext}"
                file_path = os.path.join(output_dir, filename)
                with open(file_path, "wb") as f:
                    f.write(image_bytes)
                rel_url = f"/static/uploads/questions/{filename}"
                extracted_images.append({
                    "page": page_num,
                    "url": rel_url,
                    "path": file_path
                })
            except Exception:
                pass
    return extracted_images


def _parse_pdf_document_structure(lines_with_page, extracted_images):
    """
    Document Understanding State-Machine Parser.
    Filters out theory, TOC, answer keys, solutions, instructions.
    Captures context blocks, questions, options, true/false statements (a,b,c,d), and math formulas.
    """
    q_header_pattern = re.compile(
        r'^(?:\[|\(|\【)?\s*(?:CÂU|Câu|Question|Bài|Ví dụ|Q|Q\.|Phần|Item)\s*(\d+)\s*[.\:)\-】\]]*\s*(.*)',
        re.IGNORECASE
    )
    alt_q_num_pattern = re.compile(r'^(?:\[|\()?(\d+)[\.\:\)\-]\s+(.*)')
    
    # Question verbs for implicit boundary detection
    q_verb_pattern = re.compile(
        r'^(?:Hãy|Cho|Tính|Xác định|Chọn|Phát biểu nào|Nhận xét nào|Điền vào|Viết|Tìm|Cho hình|Trong các)\b',
        re.IGNORECASE
    )

    option_pattern = re.compile(r"^(['’'*]?)\s*(?:\[|\()?([A-E])[.:)\-\]\】]\s*(.*)")
    inline_option_pattern = re.compile(r"(?:^|\s+|\t)(['’'*]?)\s*(?:\[|\()?([A-E])[.:)\-\]\】]\s*")
    tf_stmt_pattern = re.compile(r'^([a-d])[.:)]\s*(.*)')  # Lowercase a-d
    answer_pattern = re.compile(r'^(?:Đáp án|ĐÁP ÁN|Answer|Đáp án đúng)[:\s]+(.*)', re.IGNORECASE)
    diff_pattern = re.compile(r'^(?:Mức độ|MỨC ĐỘ|Level)[:\s]+(.*)', re.IGNORECASE)
    exp_pattern = re.compile(r'^(?:Giải thích|GIẢI THÍCH|Lời giải|Hướng dẫn giải)[:\s]+(.*)', re.IGNORECASE)
    
    context_intro_pattern = re.compile(
        r'^(?:Cho thông tin|Cho đoạn thông tin|Đọc đoạn văn|Dựa vào đoạn văn|Dựa vào hình|Cho dữ kiện)\b',
        re.IGNORECASE
    )

    # Section ignorer patterns (Theory, TOC, Standalone Answer Keys, Standalone Solutions)
    theory_title_pattern = re.compile(
        r'^(?:I|II|III|IV|V|VI|1|2|3|4|5)?[\.\s]*(?:KIẾN THỨC CƠ BẢN|LÝ THUYẾT|MỤC LỤC|TÓM TẮT LÝ THUYẾT|NỘI DUNG THAM KHẢO|HƯỚNG DẪN LÀM BÀI|CHÚ Ý)\b',
        re.IGNORECASE
    )
    standalone_anskey_pattern = re.compile(
        r'^(?:BẢNG ĐÁP ÁN|ĐÁP ÁN BÀI THI|ĐÁP ÁN CHO CÁC CÂU HỎI|ĐÁP ÁN TRẮC NGHIỆM)\b',
        re.IGNORECASE
    )
    standalone_solution_pattern = re.compile(
        r'^(?:HƯỚNG DẪN GIẢI CHI TIẾT|LỜI GIẢI CHI TIẾT|ĐÁP ÁN VÀ LỜI GIẢI)\b',
        re.IGNORECASE
    )
    section_header_pattern = re.compile(
        r'^(?:PHẦN|BÀI THI|ĐỀ THI|PART)\s*(?:I|II|III|IV|V|\d+)\b',
        re.IGNORECASE
    )

    section_qtype_patterns = [
        (re.compile(r'^(?:PHẦN|PART)\s*(?:I|1)\b|TRẮC NGHIỆM (?:NHIỀU LỰA CHỌN|1 ĐÁP ÁN)', re.IGNORECASE), "single"),
        (re.compile(r'^(?:PHẦN|PART)\s*(?:II|2)\b|TRẮC NGHIỆM ĐÚNG SAI|ĐÚNG\s*[\/\-]?\s*SAI', re.IGNORECASE), "true_false"),
        (re.compile(r'^(?:PHẦN|PART)\s*(?:III|3)\b|CÂU HỎI TRẢ LỜI NGẮN|TRẢ LỜI NGẮN', re.IGNORECASE), "short_answer"),
        (re.compile(r'^(?:PHẦN|PART)\s*(?:IV|4)\b|TỰ LUẬN', re.IGNORECASE), "essay"),
    ]

    raw_questions = []
    current_q = None
    current_context = ""
    current_section_qtype = "single"
    in_ignored_section = False
    in_standalone_answer_keys = False
    in_standalone_solutions = False

    for idx, item in enumerate(lines_with_page):
        line = item["text"].strip()
        page = item["page"]
        
        if not line:
            continue

        # Check section boundaries and update current_section_qtype
        for pat, stype in section_qtype_patterns:
            if pat.search(line):
                current_section_qtype = stype
                break

        if theory_title_pattern.match(line):
            in_ignored_section = True
            in_standalone_answer_keys = False
            in_standalone_solutions = False
            continue
            
        if standalone_anskey_pattern.match(line):
            in_standalone_answer_keys = True
            in_ignored_section = False
            in_standalone_solutions = False
            continue

        if standalone_solution_pattern.match(line):
            in_standalone_solutions = True
            in_ignored_section = False
            in_standalone_answer_keys = False
            continue

        # Ignore standalone answer keys section
        if in_standalone_answer_keys:
            if section_header_pattern.match(line):
                in_standalone_answer_keys = False
            else:
                continue

        # Ignore standalone solutions section (append solution text to previous question)
        if in_standalone_solutions:
            if section_header_pattern.match(line):
                in_standalone_solutions = False
            elif q_header_pattern.match(line):
                # Look ahead in lines to check if options A/B/C/D follow this header
                has_options = False
                for future_item in lines_with_page[idx+1:idx+10]:
                    fut_line = future_item["text"].strip()
                    if option_pattern.match(fut_line):
                        has_options = True
                        break
                    if q_header_pattern.match(fut_line) or section_header_pattern.match(fut_line):
                        break
                if has_options:
                    in_standalone_solutions = False
                else:
                    if raw_questions:
                        raw_questions[-1]["explanation"] = (raw_questions[-1].get("explanation", "") + " " + line).strip()
                    continue
            else:
                if raw_questions:
                    raw_questions[-1]["explanation"] = (raw_questions[-1].get("explanation", "") + " " + line).strip()
                continue

        # Ignore pure theory text block if we are in theory section
        if in_ignored_section:
            if q_header_pattern.match(line) or section_header_pattern.match(line):
                in_ignored_section = False
            else:
                continue

        # Check for Context / Reading Passage block intro
        if context_intro_pattern.search(line):
            current_context = line
            continue
        elif current_context and not current_q and not q_header_pattern.match(line):
            current_context += " " + line
            continue

        # Match Question Header: "Câu 1. ..." or "1. ..."
        q_match = q_header_pattern.match(line) or alt_q_num_pattern.match(line)
        is_implicit_question = False

        if not q_match and not current_q and q_verb_pattern.match(line):
            is_implicit_question = True

        if q_match or is_implicit_question:
            if current_q:
                raw_questions.append(current_q)

            if q_match:
                q_text = q_match.group(2).strip()
                q_confidence = 0.98
            else:
                q_text = line.strip()
                q_confidence = 0.85

            current_q = {
                "question_text": q_text,
                "context": current_context,
                "question_type": current_section_qtype,
                "difficulty_level": "",
                "explanation": "",
                "options": [],
                "statements": [],  # For true_false (a, b, c, d)
                "raw_correct": "",
                "image_url": "",
                "page": page,
                "confidence_scores": {
                    "question": q_confidence,
                    "type": 0.90,
                    "image": 0.90,
                    "answer": 0.50
                }
            }

            matching_imgs = [img for img in extracted_images if img["page"] == page]
            if matching_imgs:
                current_q["image_url"] = matching_imgs[0]["url"]
                current_q["confidence_scores"]["image"] = 0.85
            continue

        if not current_q:
            continue

        # Match True/False sub-statement (a) ... b) ... c) ... d) ...) BEFORE uppercase options
        stmt_match = tf_stmt_pattern.match(line)
        if stmt_match and (len(current_q["options"]) == 0):
            stmt_id = stmt_match.group(1).lower()  # 'a', 'b', 'c', 'd'
            stmt_text = stmt_match.group(2).strip()
            
            ans_val = None
            if re.search(r'\b(là đúng|là Đ|ĐÚNG|\(Đ\))\b', stmt_text, re.IGNORECASE):
                ans_val = True
            elif re.search(r'\b(là sai|là S|SAI|\(S\))\b', stmt_text, re.IGNORECASE):
                ans_val = False

            current_q["statements"].append({
                "id": stmt_id,
                "text": stmt_text,
                "answer": ans_val
            })
            current_q["question_type"] = "true_false"
            continue

        # Match Option (A. / B. / C. / D. and 'A. / 'B. / 'C. / 'D.)
        inline_matches = list(inline_option_pattern.finditer(line))
        if inline_matches and inline_matches[0].start() <= 3:
            for idx_m, m in enumerate(inline_matches):
                prefix = m.group(1)
                letter = m.group(2).upper()
                start_idx = m.end()
                end_idx = inline_matches[idx_m + 1].start() if idx_m + 1 < len(inline_matches) else len(line)
                
                opt_text = line[start_idx:end_idx].strip()
                is_corr = bool(prefix in ("'", "’", "’", "*")) or bool(
                    re.search(r'[*]|(?:\(đúng\))|(?:\(chính xác\))$', opt_text, re.IGNORECASE)
                )
                if opt_text.endswith("*"):
                    opt_text = opt_text[:-1].strip()

                current_q["options"].append({
                    "letter": letter,
                    "text": opt_text,
                    "is_correct": is_corr,
                    "order_index": len(current_q["options"])
                })
            continue

        # Match Answer Key line
        ans_match = answer_pattern.match(line)
        if ans_match:
            current_q["raw_correct"] = ans_match.group(1).strip()
            current_q["confidence_scores"]["answer"] = 0.95
            continue

        # Match Difficulty
        d_match = diff_pattern.match(line)
        if d_match:
            current_q["difficulty_level"] = d_match.group(1).strip()
            continue

        # Match Explanation
        e_match = exp_pattern.match(line)
        if e_match:
            current_q["explanation"] = e_match.group(1).strip()
            continue

        # Continuation text
        if current_q["explanation"]:
            current_q["explanation"] += " " + line
        elif not current_q["options"] and not current_q["statements"] and not current_q["raw_correct"]:
            current_q["question_text"] += " " + line

    if current_q:
        raw_questions.append(current_q)

    # Post-process questions for type classification, math normalization & answer matching
    for q in raw_questions:
        # Match correct options for single / multiple_choice
        raw_corr = q.get("raw_correct", "").upper()
        if raw_corr and q["options"]:
            # Check for multiple correct letters e.g. "A, B" or "A|C"
            corr_letters = set(re.findall(r'[A-E]', raw_corr))
            for opt in q["options"]:
                if opt.get("letter") in corr_letters or opt.get("text", "").upper() == raw_corr:
                    opt["is_correct"] = True

        # Infer/refine question_type
        if q["statements"]:
            if q.get("question_type") == "short_answer":
                pass  # Keep as multi-part short answer
            else:
                q["question_type"] = "true_false"
        elif q["options"]:
            correct_opts = [o for o in q["options"] if o.get("is_correct")]
            if len(correct_opts) > 1 or "nhiều đáp án" in q["question_text"].lower():
                q["question_type"] = "multiple_choice"
            elif not q.get("question_type"):
                q["question_type"] = "single"
        else:
            q_text_lower = q["question_text"].lower()
            if any(k in q_text_lower for k in ["tự luận", "hãy chứng minh", "trình bày", "phân tích", "giải thích", "so sánh"]):
                q["question_type"] = "essay"
            elif not q.get("question_type"):
                q["question_type"] = "short_answer"

        # Math formula preservation/normalization
        q["question_text"] = _normalize_latex_math(q["question_text"])
        if q.get("context"):
            q["context"] = _normalize_latex_math(q["context"])

    return raw_questions


def _normalize_latex_math(text):
    """Convert simple math expressions to standard LaTeX format ($ ... $)."""
    if not text:
        return ""
    # Wrap x^2, y_1, \frac{...}{...} if not already wrapped in $
    if "$" not in text:
        # Check for superscripts e.g. x^2 -> $x^2$
        text = re.sub(r'(\b[a-zA-Z]\^{\d+}|\b[a-zA-Z]\^\d+)', r'$\1$', text)
    return text
