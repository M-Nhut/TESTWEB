import re
import uuid
import hashlib
from services.latex_renderer import render_latex_block

def parse_latex(file_path):
    r"""
    Parse LaTeX (.tex, .latex) files to extract questions.
    Supports:
    1. Standard text formats (Câu 1:, A. B. C. D.)
    2. LaTeX environments (\begin{ex} ... \end{ex}, \choice)
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Remove LaTeX comments
    content = re.sub(r'(?<!\\)%.*$', '', content, flags=re.MULTILINE)

    raw_questions = []
    
    # Common Vietnamese exam templates define their own ``bt`` (bài tập)
    # environment.  The previous parser only looked for ex/question/bai,
    # which made files such as ``ch_thucte_12.tex`` return zero questions.
    ex_pattern = re.compile(
        r'\\begin\{(bt|ex|question|bai)\}(.*?)\\end\{\1\}',
        re.DOTALL | re.IGNORECASE,
    )
    matches = list(ex_pattern.finditer(content))
    
    if matches:
        for match in matches:
            q_text = match.group(2).strip()
            section_prefix = content[:match.start()].lower()
            section_markers = [
                (section_prefix.rfind(r"\cauds"), "true_false"),
                (section_prefix.rfind(r"\caukq"), "short_answer"),
                (section_prefix.rfind(r"\cautl"), "essay"),
                (section_prefix.rfind(r"\caulc"), "single"),
            ]
            section_type = max(section_markers, key=lambda item: item[0])[1]
            options = []
            statements = []

            # ``bt`` documents usually contain the statement before the
            # first enumerate and use ``\item`` for true/false statements.
            # Split the solution before parsing items; otherwise the solution
            # enumerate would be mistaken for answer choices.
            statement_part, solution_part = re.split(
                r'\\loigiai\s*', q_text, maxsplit=1, flags=re.IGNORECASE
            ) if re.search(r'\\loigiai\s*', q_text, re.IGNORECASE) else (q_text, '')
            q_text = _clean_latex_text(statement_part.strip())

            enum_match = re.search(
                r'\\begin\{enumerate\}(.*?)\\end\{enumerate\}',
                statement_part,
                re.DOTALL | re.IGNORECASE,
            )
            if enum_match:
                before_enum = statement_part[:enum_match.start()].strip()
                item_source = enum_match.group(1)
                item_matches = re.findall(
                    r'\\item(?:\s*\[[^]]*\])?\s*(.*?)(?=\\item|$)',
                    item_source,
                    re.DOTALL | re.IGNORECASE,
                )
                item_matches = [_clean_latex_text(item).strip() for item in item_matches if item.strip()]
                if item_matches:
                    q_text = _clean_latex_text(before_enum)
                    # A bt environment with a), b), c), d) items is the
                    # standard Vietnamese true/false question format.
                    if re.search(r'\\item', item_source, re.IGNORECASE):
                        for idx, item_text in enumerate(item_matches):
                            statements.append({
                                "id": chr(97 + idx),
                                "text": item_text,
                                "answer": None,
                            })
                        # populated below after the base question is built
                    q_text = q_text.strip()
            
            # ex_test uses command-based structures rather than A./B. lines.
            # Parse braced arguments with nesting support because formulas
            # commonly contain commands such as \dfrac{a}{b}.
            choice_match = _extract_command_arguments(q_text, r'choiceTF')
            if choice_match:
                q_text = q_text[:choice_match[0]].strip()
                statements = []
                for i, opt_text in enumerate(choice_match[1]):
                    is_correct, opt_text = _extract_answer_marker(opt_text)
                    statements.append({
                        "id": chr(97 + i),
                        "text": _clean_latex_text(opt_text),
                        "answer": is_correct,
                    })
            else:
                choice_match = _extract_command_arguments(q_text, r'choice')

            if choice_match and not statements:
                q_text = q_text[:choice_match[0]].strip()
                for i, opt_text in enumerate(choice_match[1]):
                    is_correct, opt_text = _extract_answer_marker(opt_text)
                    options.append({
                        "letter": chr(65+i),
                        "text": _clean_latex_text(opt_text),
                        "is_correct": is_correct,
                        "order_index": i
                    })

            short_answer = _extract_command_arguments(q_text, r'shortans')
            if short_answer and not options and not statements:
                q_text = q_text[:short_answer[0]].strip()
                answer = _clean_latex_text(short_answer[1][0])
                options.append({"letter": "A", "text": answer, "is_correct": True, "order_index": 0})
            
            # If no \choice found, fallback to standard text option parsing (A. B. C. D.)
            # In the short-answer and tự luận sections, labels such as
            # ``a)`` are sub-questions, not multiple-choice options.
            if not options and not statements and section_type not in ("short_answer", "essay"):
                opt_pattern = re.compile(r'(?:^|\s+)(A|B|C|D)[\.\:\)]\s+(.*?)(?=(?:\s+(?:A|B|C|D)[\.\:\)]\s+|$))', re.IGNORECASE | re.DOTALL)
                opt_matches = opt_pattern.findall(q_text)
                if opt_matches:
                    for i, (letter, opt_text) in enumerate(opt_matches):
                        options.append({
                            "letter": letter.upper(),
                            "text": opt_text.strip(),
                            "is_correct": False,
                            "order_index": i
                        })
                    # Remove options from q_text
                    first_option = re.search(r'(?:^|\s+)(?:A|B|C|D)[\.\:\)]\s+', q_text, re.IGNORECASE)
                    q_text = q_text[:first_option.start()].strip() if first_option else q_text

            raw_questions.append({
                "question_text": q_text,
                "context": "",
                "question_type": (
                    "true_false" if statements else
                    ("short_answer" if section_type == "short_answer" else
                     ("essay" if section_type == "essay" and not options else section_type))
                ),
                "difficulty_level": "",
                "explanation": _clean_latex_text(solution_part.strip()),
                "options": options,
                "statements": statements,
                "raw_correct": "",
                "image_url": "",
                "formulas": {},
                "confidence_scores": {
                    "question": 0.9,
                    "type": 0.9,
                    "image": 1.0,
                    "answer": 0.8
                }
            })
    else:
        # Fallback to plain text parsing line by line
        lines = content.split('\n')
        current_q = None
        q_num_pattern = re.compile(r'^(?:Câu|Bài|Ví dụ)\s*(\d+)\s*[.\:)\-]*\s*(.*)', re.IGNORECASE)
        opt_pattern = re.compile(r"^(['’'*]?)\s*(?:\[|\()?([A-E])[.:)\-\]\】]\s*(.*)")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            q_match = q_num_pattern.match(line)
            if q_match:
                if current_q:
                    raw_questions.append(current_q)
                current_q = {
                    "question_text": q_match.group(2),
                    "context": "",
                    "question_type": "single",
                    "difficulty_level": "",
                    "explanation": "",
                    "options": [],
                    "statements": [],
                    "raw_correct": "",
                    "image_url": "",
                    "formulas": {},
                    "confidence_scores": {
                        "question": 0.8,
                        "type": 0.8,
                        "image": 1.0,
                        "answer": 0.7
                    }
                }
                continue
                
            opt_match = opt_pattern.match(line)
            if opt_match and current_q:
                prefix = opt_match.group(1)
                letter = opt_match.group(2).upper()
                opt_text = opt_match.group(3).strip()
                is_corr = bool(prefix in ("'", "’", "*"))
                if opt_text.endswith("*"):
                    opt_text = opt_text[:-1].strip()
                    is_corr = True
                    
                current_q["options"].append({
                    "letter": letter,
                    "text": opt_text,
                    "is_correct": is_corr,
                    "order_index": len(current_q["options"])
                })
                continue
                
            if current_q and not current_q["options"]:
                current_q["question_text"] += "\n" + line
                
        if current_q:
            raw_questions.append(current_q)

    # Post-process every user-visible field, including true/false statements
    # and explanations.  Previously only question_text and options were
    # processed, so formulas inside \item were left as raw LaTeX.
    for q in raw_questions:
        q["question_text"] = _extract_assets(q["question_text"], q["formulas"])
        q["question_text"] = _extract_formulas(_clean_latex_text(q["question_text"]), q["formulas"])
        for opt in q["options"]:
            opt["text"] = _extract_formulas(_clean_latex_text(_extract_assets(opt["text"], q["formulas"])), q["formulas"])
        for stmt in q["statements"]:
            stmt["text"] = _extract_formulas(_clean_latex_text(_extract_assets(stmt["text"], q["formulas"])), q["formulas"])
        q["context"] = _extract_formulas(_clean_latex_text(_extract_assets(q.get("context", ""), q["formulas"])), q["formulas"])
        q["explanation"] = _extract_formulas(_clean_latex_text(_extract_assets(q.get("explanation", ""), q["formulas"])), q["formulas"])

    return raw_questions

def _extract_formulas(text, formulas_dict):
    """
    Extract LaTeX math mode $...$ and $$...$$ into FormulaAsset placeholders.
    """
    if not text:
        return text
        
    # Process longest/multiline delimiters first.  ``ch_thucte_12.tex`` uses
    # both inline ``$...$`` and display ``\[...\]`` math.
    pattern = re.compile(
        r'(\$\$(.*?)\$\$|\\\[(.*?)\\\]|\\\((.*?)\\\)|'
        r'\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}(.*?)'
        r'\\end\{\5\}|\$(.*?)\$)',
        re.DOTALL,
    )
    
    def replacer(match):
        groups = match.groups()
        # Groups 2, 3, 4 are the standard delimiters. For equation-like
        # environments, group 5 contains the body; group 4 is only the
        # environment name. The final group is `$...$`.
        latex_content = next(
            (groups[index] for index in (1, 2, 3, 5, 6) if groups[index] is not None),
            '',
        )
        latex_content = latex_content.strip()
        
        if not latex_content:
            return match.group(0)
            
        f_id = str(uuid.uuid4())
        formulas_dict[f_id] = {
            "latex": latex_content,
            "source_format": "LaTeX",
            "needs_review": False,
            "content_hash": hashlib.sha256(latex_content.encode("utf-8")).hexdigest(),
            "conversion_status": "converted",
            "parse_confidence": 1.0,
        }
        return f" [[formula:{f_id}]] "

    return pattern.sub(replacer, text)


def _extract_command_arguments(text, command):
    """Extract all braced arguments from an ex_test command.

    Returns ``(start_index, arguments)`` or ``None``. This intentionally
    parses balanced braces instead of using ``[^}]`` so nested LaTeX works.
    """
    match = re.search(r'\\' + command + r'\b', text, re.IGNORECASE)
    if not match:
        return None
    pos = match.end()
    args = []
    while pos < len(text):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text) or text[pos] != '{':
            break
        start = pos + 1
        depth = 1
        pos += 1
        while pos < len(text) and depth:
            if text[pos] == '\\':
                pos += 2
                continue
            if pos < len(text) and text[pos] == '{':
                depth += 1
            elif pos < len(text) and text[pos] == '}':
                depth -= 1
            pos += 1
        if depth:
            return None
        args.append(text[start:pos - 1])
    return (match.start(), args) if args else None


def _extract_answer_marker(text):
    """Return ``(is_correct, text_without_marker)`` for ex_test choices."""
    is_correct = bool(re.search(r'\\True\b', text, re.IGNORECASE))
    text = re.sub(r'\\(?:True|False)\b\s*', '', text, flags=re.IGNORECASE)
    return is_correct, text.strip()


def _clean_latex_text(text):
    """Remove PDF-only LaTeX presentation constructs before MathJax render."""
    if not text:
        return text

    # Keep the text inside structural environments but remove their wrappers.
    text = re.sub(
        r'\\(?:begin|end)\{(?:center|flushleft|flushright|itemize|enumerate|itemchoice|tcolorbox|minipage)\}(?:\[[^]]*\])?',
        '', text, flags=re.IGNORECASE,
    )
    text = re.sub(r'\\itemch?\s*', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\\(?:item|noindent|par|quad|qquad|hspace|vspace)(?:\{[^{}]*\}|\[[^]]*\])?\s*', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\\text\{([^{}]*)\}', r'\1', text)
    text = re.sub(r'\\(?:textbf|textit|textrm|textsf|emph)\{([^{}]*)\}', r'\1', text)
    text = re.sub(r'\\(?:left|right)\b', '', text)
    text = re.sub(r'\\(?:,|;|:|!)', ' ', text)
    text = re.sub(r'\\(?:label|tag)\{[^{}]*\}', '', text)
    return re.sub(r'[ \t]+', ' ', text).strip()


def _extract_assets(text, formulas_dict):
    """Replace non-MathJax LaTeX blocks by server-rendered SVG assets."""
    if not text:
        return text

    block_names = {"tikzpicture", "tabular", "tabularx", "picture", "verbatim", "lstlisting"}
    begin_pattern = re.compile(r'\\begin\{([^}]+)\}', re.IGNORECASE)
    end_pattern = re.compile(r'\\end\{([^}]+)\}', re.IGNORECASE)

    def replace_source(source):
        url = render_latex_block(source)
        asset_id = str(uuid.uuid4())
        formulas_dict[asset_id] = {
            "latex": None,
            "mathml": None,
            "source_format": "LaTeXBlock",
            "conversion_status": "fallback_svg" if url else "failed",
            "verification_status": "verified" if url else "needs_review",
            "needs_review": not bool(url),
            "preview_url": url,
            "svg_cache_key": url,
            "content_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "parse_confidence": 1.0 if url else 0.0,
        }
        return f" [[formula:{asset_id}]] "

    # Regex with a non-greedy body breaks nested tabular environments. Walk
    # the source and match begin/end pairs by depth instead.
    output = []
    cursor = 0
    while cursor < len(text):
        match = begin_pattern.search(text, cursor)
        if not match or match.group(1).lower() not in block_names:
            output.append(text[cursor:])
            break
        output.append(text[cursor:match.start()])
        env_name = match.group(1).lower()
        depth = 1
        scan = match.end()
        closing_start = None
        closing_end = None
        token_pattern = re.compile(r'\\(?:begin|end)\{([^}]+)\}', re.IGNORECASE)
        for token in token_pattern.finditer(text, scan):
            token_name = token.group(1).lower()
            if token_name != env_name:
                continue
            if token.group(0).lower().startswith('\\begin'):
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    closing_start, closing_end = token.start(), token.end()
                    break
        if closing_end is None:
            # Preserve malformed source for the caller to review.
            output.append(text[match.start():])
            break
        output.append(replace_source(text[match.start():closing_end]))
        cursor = closing_end
    return ''.join(output)
