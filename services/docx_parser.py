"""
DOCX Question Parser — Enhanced parser for DOCX files with OMML & MathType equations.

Strategy:
  1. Use macOS `textutil -convert html` to convert DOCX → HTML, extracting
     MathType formulas as rendered images (TIFF/PDF→PNG).
  2. Use `python-docx` to parse question structure, OMML math → LaTeX,
     options, statements, and explanations.
  3. Merge: replace WMF/EMF OLE placeholders with textutil-rendered images.
"""

import base64
import io
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

UPLOAD_QUESTIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads", "questions")


def ensure_questions_dir():
    os.makedirs(UPLOAD_QUESTIONS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
#  textutil-based MathType image extraction
# ---------------------------------------------------------------------------

def _extract_mathtype_images_via_textutil(docx_path):
    """
    Convert DOCX → HTML using macOS textutil, then extract all <img> images
    from the HTML (these include rendered MathType equations).
    Returns list of web-accessible image URLs.
    """
    images = []
    try:
        tmp_dir = tempfile.mkdtemp(prefix="docx_textutil_")
        html_path = os.path.join(tmp_dir, "output.html")

        result = subprocess.run(
            ["/usr/bin/textutil", "-convert", "html", "-output", html_path, docx_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        if result.returncode != 0 or not os.path.exists(html_path):
            print(f"[docx_parser] textutil conversion failed: {result.stderr.decode()}")
            return images

        with open(html_path, "r", encoding="utf-8", errors="replace") as f:
            html_content = f.read()

        ensure_questions_dir()

        # Extract base64 embedded images from HTML (data:image/...)
        b64_pattern = re.compile(r'<img\s[^>]*src="data:image/([^;]+);base64,([^"]+)"', re.IGNORECASE)
        for m in b64_pattern.finditer(html_content):
            img_format = m.group(1).lower()
            img_b64 = m.group(2)
            try:
                img_bytes = base64.b64decode(img_b64)
                png_bytes = _convert_any_to_png(img_bytes, img_format)
                if png_bytes:
                    filename = f"math_eq_{uuid.uuid4().hex[:8]}.png"
                    filepath = os.path.join(UPLOAD_QUESTIONS_DIR, filename)
                    with open(filepath, "wb") as f:
                        f.write(png_bytes)
                    images.append(f"/static/uploads/questions/{filename}")
            except Exception as e:
                print(f"[docx_parser] Failed to extract base64 image: {e}")

        # Extract file-referenced images from HTML
        file_img_pattern = re.compile(r'<img\s[^>]*src="([^"]+)"', re.IGNORECASE)
        for m in file_img_pattern.finditer(html_content):
            src = m.group(1)
            if src.startswith("data:"):
                continue  # already handled above

            # Resolve relative paths against tmp_dir
            img_path = os.path.join(tmp_dir, src) if not os.path.isabs(src) else src
            if os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as f:
                        img_bytes = f.read()

                    ext = os.path.splitext(img_path)[1].lower().strip(".")
                    png_bytes = _convert_any_to_png(img_bytes, ext)
                    if png_bytes:
                        filename = f"math_eq_{uuid.uuid4().hex[:8]}.png"
                        filepath = os.path.join(UPLOAD_QUESTIONS_DIR, filename)
                        with open(filepath, "wb") as f:
                            f.write(png_bytes)
                        images.append(f"/static/uploads/questions/{filename}")
                except Exception as e:
                    print(f"[docx_parser] Failed to process image file {img_path}: {e}")

        # Cleanup temp dir
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

    except Exception as e:
        print(f"[docx_parser] textutil extraction error: {e}")

    print(f"[docx_parser] textutil extracted {len(images)} images")
    return images


def _convert_any_to_png(img_bytes, fmt):
    """Convert image bytes of any format to PNG bytes using PIL."""
    if not img_bytes or len(img_bytes) < 50:
        return None

    # If already PNG, return as-is
    if img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return img_bytes

    if HAS_PIL:
        try:
            img = PILImage.open(io.BytesIO(img_bytes))
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result = buf.getvalue()
            if len(result) > 100:
                return result
        except Exception:
            pass

    # Fallback: try sips
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as f_in:
            f_in.write(img_bytes)
            in_path = f_in.name
        out_path = in_path + ".png"
        res = subprocess.run(
            ["/usr/bin/sips", "-s", "format", "png", in_path, "--out", out_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
        )
        if res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 100:
            with open(out_path, "rb") as f:
                return f.read()
    except Exception:
        pass
    finally:
        for p in [locals().get("in_path"), locals().get("out_path")]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
    return None


def extract_latex_from_wmf(wmf_bytes):
    """
    Extract LaTeX formula string from MathType WMF image binary data.
    MathType WMF files contain embedded MTEF binary payload inside META_ESCAPE.
    Supports DSMT4, DSMT5, DSMT6, DSMT7.
    """
    if not wmf_bytes:
        return ""
    
    mtef_version = 3
    idx = wmf_bytes.find(b"DSMT7\x00")
    if idx >= 0: mtef_version = 7
    if idx < 0: 
        idx = wmf_bytes.find(b"DSMT6\x00")
        if idx >= 0: mtef_version = 6
    if idx < 0: 
        idx = wmf_bytes.find(b"DSMT5\x00")
        if idx >= 0: mtef_version = 5
    if idx < 0: 
        idx = wmf_bytes.find(b"DSMT4\x00")
        if idx >= 0: mtef_version = 4
    if idx < 0: 
        idx = wmf_bytes.find(b"DSMT3\x00")
        if idx >= 0: mtef_version = 3
    if idx < 0: idx = wmf_bytes.find(b"DSMT2\x00")
    if idx < 0: idx = wmf_bytes.find(b"DSMT\x00")
    if idx < 0: idx = wmf_bytes.find(b"DSMT")
    if idx < 0: return ""
    
    # If the payload has the null byte from DSMT7\x00, skip 6 bytes, else skip 4 bytes
    payload = wmf_bytes[idx+6:] if b"\x00" in wmf_bytes[idx:idx+6] else wmf_bytes[idx+4:]
    
    # 1. Try to extract exact TeX string from MathType application translator data (highest fidelity)
    tex_idx = payload.find(b"TeX Input Language")
    if tex_idx >= 0:
        null_after_tex = payload.find(b"\x00", tex_idx)
        if null_after_tex >= 0:
            tex_str_start = null_after_tex + 1
            tex_str_end = payload.find(b"\x00", tex_str_start)
            if tex_str_end >= 0:
                tex_str = payload[tex_str_start:tex_str_end]
                if b"\\" in tex_str or b"_" in tex_str or b"^" in tex_str or b"=" in tex_str:
                    try:
                        clean_tex = tex_str.decode("utf-8", errors="ignore").strip()
                        if clean_tex.startswith("{") and clean_tex.endswith("}"):
                            clean_tex = clean_tex[1:-1].strip()
                        clean_tex = clean_tex.replace("\r", " ").replace("\n", " ").strip()
                        clean_tex = clean_tex.replace(r"\begin{align}", r"\begin{aligned}").replace(r"\end{align}", r"\end{aligned}")
                        if clean_tex.startswith("$") and clean_tex.endswith("$"):
                            return clean_tex
                        return f"${clean_tex}$"
                    except:
                        pass
    # 2. Try to parse binary MTEF tree
    p = -1
    if mtef_version >= 5:
        # MTEF v5 equation content almost always starts with 0x0A (FULL SIZE) followed by 0x01 (LINE) and 0x00 (LINE options)
        pos = payload.find(b"\x0a\x01\x00")
        if pos >= 0: p = pos
    else:
        header_end = payload.find(b"MT Extra\x00")
        pos_line = payload.find(b"\x01\x00\x03\x00")
        if pos_line >= 0: p = pos_line + 12
        elif header_end >= 0: p = header_end + 9

    if p < 0:
        p = 30 # fallback
            
    def map_char(ch_val):
        symbols = {
            0x2B: "+", 0x2D: "-", 0x3D: "=", 0x3C: "<", 0x3E: ">", 0x28: "(", 0x29: ")", 0x2F: "/",
            0x2C: ",", 0x2E: ".", 0x3A: ":", 0x3B: ";", 0x21: "!", 0x3F: "?",
            0x5C: r"\setminus ", # backslash in MathType is setminus
            0x61: r"\alpha ", 0x62: r"\beta ", 0x67: r"\gamma ", 0x64: r"\delta ", 0x65: r"\epsilon ",
            0x70: r"\pi ", 0x71: r"\theta ", 0x73: r"\sigma ", 0x6D: r"\mu ", 0x6C: r"\lambda ",
            0xB3: r"\ge ", 0xA3: r"\le ", 0xB9: r"\ne ", 0xD6: r"\sqrt{}", 0xE5: r"\sum ", 0xF2: r"\int ",
            0xCE: r"\in ", 0xCF: r"\notin ", 0xB1: r"\pm ", 0xB4: r"\times ", 0xB8: r"\div ",
            0x22: r"\forall ", 0x24: r"\exists ",
            0x2200: r"\forall ", 0x2203: r"\exists ", 0x2208: r"\in ", 0x2209: r"\notin ",
            0x2115: r"\mathbb{N} ", 0x2124: r"\mathbb{Z} ", 0x211A: r"\mathbb{Q} ", 0x211D: r"\mathbb{R} ",
            0x22EE: r"\vdots ", 0x224D: r"\vdots ", 0x2223: r"\mid ", 0x222D: "-", 0x2212: "-",
            0x2264: r"\le ", 0x2265: r"\ge ", 0x2260: r"\ne ", 0x221A: r"\sqrt{}",
            0x221E: r"\infty ", 0x2192: r"\rightarrow ", 0x21D2: r"\Rightarrow ", 0x21D4: r"\Leftrightarrow ",
            0x2213: r"\mp ", 0x222B: r"\int ", 0x222C: r"\iint ", 0x2211: r"\sum ", 0x220F: r"\prod ",
            0x2229: r"\cap ", 0x222A: r"\cup ", 0x2282: r"\subset ", 0x2283: r"\supset ", 0x2286: r"\subseteq ", 0x2287: r"\supseteq ",
            0x2205: r"\emptyset ", 0x00B1: r"\pm ", 0x2206: r"\Delta ", 0x0394: r"\Delta ", 0x2248: r"\approx ", 0x2261: r"\equiv ",
            # Unicode Greek lowercase
            0x03B1: r"\alpha ", 0x03B2: r"\beta ", 0x03B3: r"\gamma ", 0x03B4: r"\delta ", 0x03B5: r"\epsilon ", 0x03B6: r"\zeta ",
            0x03B7: r"\eta ", 0x03B8: r"\theta ", 0x03B9: r"\iota ", 0x03BA: r"\kappa ", 0x03BB: r"\lambda ", 0x03BC: r"\mu ",
            0x03BD: r"\nu ", 0x03BE: r"\xi ", 0x03BF: r"o ", 0x03C0: r"\pi ", 0x03C1: r"\rho ", 0x03C2: r"\varsigma ",
            0x03C3: r"\sigma ", 0x03C4: r"\tau ", 0x03C5: r"\upsilon ", 0x03C6: r"\phi ", 0x03C7: r"\chi ", 0x03C8: r"\psi ", 0x03C9: r"\omega ",
            # Unicode Greek uppercase
            0x0391: r"A ", 0x0392: r"B ", 0x0393: r"\Gamma ", 0x0395: r"E ", 0x0396: r"Z ", 0x0397: r"H ", 0x0398: r"\Theta ",
            0x0399: r"I ", 0x039A: r"K ", 0x039B: r"\Lambda ", 0x039C: r"M ", 0x039D: r"N ", 0x039E: r"\Xi ", 0x039F: r"O ",
            0x03A0: r"\Pi ", 0x03A1: r"P ", 0x03A3: r"\Sigma ", 0x03A4: r"T ", 0x03A5: r"\Upsilon ", 0x03A6: r"\Phi ", 0x03A7: r"X ",
            0x03A8: r"\Psi ", 0x03A9: r"\Omega "
        }
        if ch_val in symbols: return symbols[ch_val]
        if 32 <= ch_val <= 126:
            c = chr(ch_val)
            if c in ("{", "}"): return "\\" + c
            return c
        return ""

    def parse_slot():
        nonlocal p
        tokens = []
        while p < len(payload):
            if p >= len(payload): break
            tag = payload[p]
            p += 1
            if tag == 0x00: break
            
            if mtef_version >= 5:
                opts = 0
                if 1 <= tag <= 7:
                    if p >= len(payload): break
                    opts = payload[p]
                    p += 1
                    if opts & 0x08: # Nudge
                        if p < len(payload) and payload[p] == 128: p += 5
                        else: p += 2
                        
                if tag == 1: # LINE
                    tokens.append(parse_slot())
                elif tag == 2: # CHAR
                    tf = payload[p] if p < len(payload) else 0; p += 1
                    ch_val = 0
                    if not (opts & 0x20): # MTCode is present
                        ch_val = payload[p] | (payload[p+1] << 8) if p + 1 < len(payload) else 0
                        p += 2
                    if opts & 0x04: p += 1 # explicit 8-bit glyph
                    elif opts & 0x10: p += 2 # explicit 16-bit glyph
                    tokens.append(map_char(ch_val))
                elif tag == 3: # TMPL
                    t_sel = payload[p] if p < len(payload) else 0; p += 1
                    t_var = payload[p] if p < len(payload) else 0; p += 1
                    
                    # MathType 5 templates always seem to have an extra byte (often 00) before the slot starts
                    # even if mtefOPT_TMPL_SPECIFIC is not set in the options byte.
                    if p < len(payload): p += 1
                    
                    res = ""
                    if t_sel == 0:
                        c = parse_slot()
                        res = rf"\left\langle {c}\right\rangle" if c.strip() else ""
                    elif t_sel == 1:
                        c = parse_slot()
                        res = rf"\left({c}\right)" if c.strip() else ""
                    elif t_sel == 2:
                        c = parse_slot()
                        res = rf"\left\{{{c}\right\}}" if c.strip() else ""
                    elif t_sel == 3:
                        c = parse_slot()
                        res = rf"\left[{c}\right]" if c.strip() else ""
                    elif t_sel == 4:
                        c = parse_slot()
                        res = rf"\left|{c}\right|" if c.strip() else ""
                    elif t_sel in (9, 10):
                        num = parse_slot()
                        den = parse_slot()
                        if num.strip() and den.strip(): res = rf"\frac{{{num}}}{{{den}}}"
                        elif num.strip(): res = num.strip()
                        elif den.strip(): res = den.strip()
                    elif t_sel in (11, 12):
                        if t_sel == 11:
                            rad = parse_slot()
                            res = rf"\sqrt{{{rad}}}"
                        else:
                            deg = parse_slot()
                            rad = parse_slot()
                            res = rf"\sqrt[{deg}]{{{rad}}}"
                    elif t_sel in (13, 28, 0x1C):
                        sup = parse_slot()
                        if not sup.strip(): sup = parse_slot()
                        res = rf"^{{{sup}}}" if sup.strip() else ""
                    elif t_sel in (14, 27, 0x1B):
                        sub = parse_slot()
                        if not sub.strip(): sub = parse_slot()
                        res = rf"_{{{sub}}}" if sub.strip() else ""
                    elif t_sel in (15, 29, 0x1D):
                        sub = parse_slot()
                        sup = parse_slot()
                        res = rf"_{{{sub}}}^{{{sup}}}"
                    else:
                        res = parse_slot()
                    tokens.append(res)
                elif tag in (4, 5): # PILE, MATRIX
                    tokens.append(parse_slot())
                else: # Size and formatting records (0x08, 0x09, 0x0A, 0x11, 0x12)
                    pass 
            else:
                # MTEF v3 legacy parsing
                rec_type = tag & 0x0F
                if rec_type == 0x01:
                    tokens.append(parse_slot())
                elif rec_type == 0x02:
                    if p >= len(payload): break
                    opts = payload[p]; p += 1
                    if opts & 0x01: p += 2
                    tf = 0
                    if opts & 0x04: tf = payload[p]; p += 1
                    if opts & 0x08: p += 1
                    if opts & 0x10: p += 1
                    if opts & 0x02:
                        ch_val = payload[p] | (payload[p+1] << 8) if p + 1 < len(payload) else 0
                        p += 2
                    else:
                        ch_val = payload[p] if p < len(payload) else 0
                        p += 1
                    tokens.append(map_char(ch_val))
                elif rec_type == 0x03:
                    if p >= len(payload): break
                    opts = payload[p]; p += 1
                    if opts & 0x01: p += 2
                    t_sel = payload[p] if p < len(payload) else 0; p += 1
                    t_var = payload[p] if p < len(payload) else 0; p += 1
                    res = ""
                    if t_sel == 0:
                        c = parse_slot()
                        res = rf"\left({c}\right)" if c.strip() else ""
                    elif t_sel == 1:
                        c = parse_slot()
                        res = rf"\left[{c}\right]" if c.strip() else ""
                    elif t_sel == 2:
                        c = parse_slot()
                        res = rf"\left\{{{c}\right\}}" if c.strip() else ""
                    elif t_sel in (9, 10):
                        num = parse_slot()
                        den = parse_slot()
                        if num.strip() and den.strip(): res = rf"\frac{{{num}}}{{{den}}}"
                        elif num.strip(): res = num.strip()
                        elif den.strip(): res = den.strip()
                    elif t_sel in (11, 12):
                        if t_sel == 11:
                            rad = parse_slot()
                            res = rf"\sqrt{{{rad}}}"
                        else:
                            deg = parse_slot()
                            rad = parse_slot()
                            res = rf"\sqrt[{deg}]{{{rad}}}"
                    elif t_sel in (13, 28, 0x1C):
                        sup = parse_slot()
                        if not sup.strip(): sup = parse_slot()
                        res = rf"^{{{sup}}}" if sup.strip() else ""
                    elif t_sel in (14, 27, 0x1B):
                        sub = parse_slot()
                        if not sub.strip(): sub = parse_slot()
                        res = rf"_{{{sub}}}" if sub.strip() else ""
                    elif t_sel in (15, 29, 0x1D):
                        sub = parse_slot()
                        sup = parse_slot()
                        res = rf"_{{{sub}}}^{{{sup}}}"
                    else:
                        res = parse_slot()
                    tokens.append(res)
                elif rec_type in (0x04, 0x05):
                    tokens.append(parse_slot())
                elif rec_type in (0x08, 0x09, 0x0A):
                    if rec_type == 0x08:
                        p += 1
                        while p < len(payload) and payload[p] != 0: p += 1
                        p += 1
                    elif rec_type == 0x09:
                        p += 2
                else:
                    break
        return "".join(tokens)

    tokens = []
    while p < len(payload):
        tok = parse_slot()
        if tok: tokens.append(tok)
        else: break
        
    bin_formula = "".join(tokens).strip()
    
    if bin_formula:
        # Clean up empty literal brackets mistakenly typed by users
        bin_formula = bin_formula.replace(r"\{\}", "").replace("()", "")
    
    # 3. Fallback to raw ASCII string extraction only if bin_formula is empty
    if not bin_formula:
        skip_chars = set("@#$%&_\\|~")
        ascii_tokens = []
        fp = p if p >= 0 else 30
        while fp < len(payload):
            b = payload[fp]
            if b == 0xB1:
                ascii_tokens.append(r" \pm ")
            elif 32 <= b <= 126 and chr(b) not in skip_chars:
                ascii_tokens.append(chr(b))
            fp += 1
        raw_s = "".join(ascii_tokens).strip()
        
        # Clean up some common artifacts
        if "DEEA" in raw_s: raw_s = raw_s.split("DEEA")[-1]
        if "System" in raw_s: raw_s = raw_s.split("System")[0]
        raw_s = raw_s.replace("Equation Native", "").replace("\"", "").strip()
        
        # Radical fix (hack)
        raw_s = re.sub(r"^([0-9a-zA-Z]+)--", r"\\sqrt{\1}", raw_s)
        raw_s = re.sub(r"==([0-9a-zA-Z]+)--", r"= \\sqrt{\1}", raw_s)
        
        bin_formula = raw_s
        
    if not bin_formula:
        return ""
        
    final_f = bin_formula.replace(r"\pm \pm", r"\pm ").replace(r"\pm\pm", r"\pm ")
    if final_f == "p": final_f = r"\pi"
    
    return f"${final_f}$"
        
    return f"${final_f}$" if final_f else ""


# ---------------------------------------------------------------------------
#  Main DOCX parser
# ---------------------------------------------------------------------------

def parse_docx(file_stream_or_path):
    """
    Parse DOCX file.

    Extracts text, OMML math equations (→ LaTeX), MathType equations (→ PNG images / LaTeX),
    images, options, True/False statements, and explanations from body paragraphs and tables.

    Returns:
        list of raw question dicts
    """
    if not HAS_DOCX:
        raise RuntimeError("Thư viện 'python-docx' chưa được cài đặt.")

    # Save to temp file if given a stream (needed for textutil)
    tmp_docx_path = None
    if hasattr(file_stream_or_path, "read"):
        tmp_file = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp_file.write(file_stream_or_path.read())
        tmp_file.close()
        tmp_docx_path = tmp_file.name
        docx_path = tmp_docx_path
        file_stream_or_path.seek(0)  # Reset stream for python-docx
        doc = docx.Document(file_stream_or_path)
    else:
        docx_path = file_stream_or_path
        doc = docx.Document(file_stream_or_path)

    ensure_questions_dir()

    # ------- Phase 1: Extract MathType images via textutil -------
    textutil_images = _extract_mathtype_images_via_textutil(docx_path)
    textutil_img_idx = [0]  # mutable counter for closure

    # ------- Phase 2: Extract standard images from DOCX relationships -------
    rel_id_to_image = {}
    wmf_rel_ids = set()
    stats = {"standard_imgs": 0, "wmf_skipped": 0, "wmf_replaced": 0}

    try:
        for rel_id, rel in doc.part.rels.items():
            if hasattr(rel, "target_part") and ("image" in getattr(rel.target_part, "content_type", "") or "ole" in getattr(rel.target_part, "content_type", "").lower()):
                target_part = rel.target_part
                img_bytes = target_part.blob
                ct = getattr(target_part, "content_type", "").split("/")[-1].lower()

                if ct in ("jpeg", "pjpeg"):
                    ext = "jpg"
                elif ct in ("png",):
                    ext = "png"
                elif ct in ("gif",):
                    ext = "gif"
                elif ct in ("x-wmf", "wmf", "x-emf", "emf", "vnd.openxmlformats-officedocument.oleobject"):
                    # WMF/EMF/OLE: Try MTEF LaTeX extraction first
                    latex_math = extract_latex_from_wmf(img_bytes)
                    if latex_math:
                        rel_id_to_image[rel_id] = latex_math
                        stats["wmf_replaced"] += 1
                        continue

                    # Fallback to textutil images
                    wmf_rel_ids.add(rel_id)
                    if textutil_img_idx[0] < len(textutil_images):
                        rel_id_to_image[rel_id] = textutil_images[textutil_img_idx[0]]
                        textutil_img_idx[0] += 1
                        stats["wmf_replaced"] += 1
                    else:
                        stats["wmf_skipped"] += 1
                    continue
                else:
                    ext = ct if ct in ("bmp", "tiff", "svg+xml") else "png"

                filename = f"img_docx_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(UPLOAD_QUESTIONS_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(img_bytes)
                web_path = f"/static/uploads/questions/{filename}"
                rel_id_to_image[rel_id] = web_path
                stats["standard_imgs"] += 1
    except Exception as e:
        print(f"[docx_parser] Error mapping docx images: {e}")

    print(f"[docx_parser] Image stats: {stats}")

    # Clean up temp file
    if tmp_docx_path and os.path.exists(tmp_docx_path):
        try:
            os.remove(tmp_docx_path)
        except Exception:
            pass

    # ------- Phase 3: Parse question structure from paragraphs -------
    raw_questions = []
    current_q = None
    in_explanation = False

    # Standard question prefixes
    q_num_pattern = re.compile(
        r'^(?:<[^>]+>\s*)*(?:\[|\(|\【)?\s*(?:CÂU|Câu|Question|Bài|Ví dụ|Q|Q\.|Phần|Item)\s*(\d+)\s*[.\:)\-】\]]*\s*(.*)',
        re.IGNORECASE
    )
    alt_num_pattern = re.compile(r'^(?:\[|\()?(\d+)[\.\:\)\-]\s+(.*)')
    
    # Options pattern
    option_pattern = re.compile(r"^(['’'*]?)\s*(?:\[|\()?([A-E])[.:)\-\]\】]\s*(.*)")
    inline_option_pattern = re.compile(r"(?:^|\s+|\t|(?<=[.,;!?:$]))(['’'*]?)\s*(?:\[|\()?([A-E])[.:)\-\]\】]\s*")
    tf_stmt_pattern = re.compile(r'^([a-d])[.:)]\s*(.*)')
    type_pattern = re.compile(r'^(?:TYPE|LOẠI|Loại câu hỏi)[:\s]+(.*)', re.IGNORECASE)
    answer_pattern = re.compile(r'^(?:ANSWER|Đáp án|ĐÁP ÁN|Đáp án đúng|Chọn)[:\s]+(.*)', re.IGNORECASE)
    diff_pattern = re.compile(r'^(?:Mức độ|MỨC ĐỘ|Level)[:\s]+(.*)', re.IGNORECASE)
    exp_pattern = re.compile(r'^(?:Giải thích|GIẢI THÍCH|Lời giải|Lời giải:|Hướng dẫn giải|HDG|Lời giải tham khảo)[:\s]*(.*)', re.IGNORECASE)

    all_paragraphs = list(_iter_all_paragraphs(doc))
    unassigned_text_lines = []

    for p_idx, p in enumerate(all_paragraphs):
        p_text = _extract_paragraph_text(p, rel_id_to_image).strip()
        if not p_text:
            continue

        q_match = q_num_pattern.match(p_text) or alt_num_pattern.match(p_text)
        if q_match:
            if current_q:
                raw_questions.append(current_q)
            in_explanation = False
            q_text = q_match.group(2).strip()
            if not q_text and unassigned_text_lines:
                q_text = "\n".join(unassigned_text_lines)
                unassigned_text_lines = []

            current_q = {
                "question_text": q_text,
                "context": "",
                "question_type": "",
                "difficulty_level": "",
                "explanation": "",
                "options": [],
                "statements": [],
                "raw_correct": "",
                "image_url": "",
                "confidence_scores": {
                    "question": 0.98,
                    "type": 0.95,
                    "image": 1.0,
                    "answer": 0.80,
                },
            }
            continue

        # If options appear before an explicit 'Câu X' header, auto-create question
        inline_matches = list(inline_option_pattern.finditer(p_text))
        if not current_q and inline_matches:
            q_text = "\n".join(unassigned_text_lines).strip() if unassigned_text_lines else f"Câu hỏi {len(raw_questions) + 1}"
            unassigned_text_lines = []
            current_q = {
                "question_text": q_text,
                "context": "",
                "question_type": "",
                "difficulty_level": "",
                "explanation": "",
                "options": [],
                "statements": [],
                "raw_correct": "",
                "image_url": "",
                "confidence_scores": {
                    "question": 0.90,
                    "type": 0.90,
                    "image": 1.0,
                    "answer": 0.80,
                },
            }

        if not current_q:
            unassigned_text_lines.append(p_text)
            continue

        # Type tag
        t_match = type_pattern.match(p_text)
        if t_match:
            current_q["question_type"] = _map_template_type(t_match.group(1).strip())
            continue

        # Explanation / Lời giải heading
        exp_match = exp_pattern.match(p_text)
        if exp_match and not in_explanation:
            in_explanation = True
            first_exp = exp_match.group(1).strip()
            if first_exp:
                current_q["explanation"] = first_exp
            continue

        # Continuation of explanation
        if in_explanation:
            if current_q["explanation"]:
                current_q["explanation"] += "\n" + p_text
            else:
                current_q["explanation"] = p_text
            continue

        # Option A., B., C., D. (supports single quote 'A., 'B., 'C., 'D. and inline options)
        inline_matches = list(inline_option_pattern.finditer(p_text))
        if inline_matches and inline_matches[0].start() <= 3:
            is_bold_or_underlined = False
            for r in p.runs:
                if r.bold or r.underline:
                    is_bold_or_underlined = True
                    break

            for idx_m, m in enumerate(inline_matches):
                prefix = m.group(1)
                letter = m.group(2).upper()
                start_idx = m.end()
                end_idx = inline_matches[idx_m + 1].start() if idx_m + 1 < len(inline_matches) else len(p_text)
                
                opt_text = p_text[start_idx:end_idx].strip()
                is_corr = bool(prefix in ("'", "’", "’", "*")) or bool(
                    re.search(r'[*]|(?:\(đúng\))|(?:\(chính xác\))$', opt_text, re.IGNORECASE)
                )
                if opt_text.endswith("*"):
                    opt_text = opt_text[:-1].strip()

                current_q["options"].append({
                    "letter": letter,
                    "text": opt_text,
                    "is_correct": is_corr,
                    "order_index": len(current_q["options"]),
                })
            continue

        # True/False statement a), b), c), d)
        stmt_match = tf_stmt_pattern.match(p_text)
        if stmt_match and len(current_q["options"]) == 0:
            stmt_id = stmt_match.group(1).lower()
            stmt_text = stmt_match.group(2).strip()
            ans_val = None
            if re.search(r'\b(là đúng|ĐÚNG|\(Đ\)|TRUE)\b', stmt_text, re.IGNORECASE):
                ans_val = True
            elif re.search(r'\b(là sai|SAI|\(S\)|FALSE)\b', stmt_text, re.IGNORECASE):
                ans_val = False

            current_q["statements"].append({
                "id": stmt_id,
                "text": stmt_text,
                "answer": ans_val,
            })
            current_q["question_type"] = "true_false"
            continue

        # Answer key
        ans_match = answer_pattern.match(p_text)
        if ans_match:
            current_q["raw_correct"] = ans_match.group(1).strip()
            continue

        # Difficulty
        diff_match = diff_pattern.match(p_text)
        if diff_match:
            current_q["difficulty_level"] = diff_match.group(1).strip()
            continue

        # Continuation of question text
        if not current_q["options"] and not current_q["statements"] and not current_q["raw_correct"]:
            current_q["question_text"] += "\n" + p_text

    if current_q:
        raw_questions.append(current_q)

    # ------- Phase 4: Post-process -------
    for q in raw_questions:
        raw_corr = q.get("raw_correct", "").upper()
        if raw_corr and q["options"]:
            corr_letters = set(re.findall(r"[A-E]", raw_corr))
            for opt in q["options"]:
                if opt.get("letter") in corr_letters or opt.get("text", "").upper() == raw_corr:
                    opt["is_correct"] = True

    return raw_questions


# ---------------------------------------------------------------------------
#  Paragraph / XML walking helpers
# ---------------------------------------------------------------------------

def _iter_all_paragraphs(doc):
    """Yield all paragraphs in document order, including paragraphs inside tables."""
    body = doc.element.body
    for child in body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "p":
            yield docx.text.paragraph.Paragraph(child, doc)
        elif tag == "tbl":
            table = docx.table.Table(child, doc)
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        yield p


def _extract_paragraph_text(p, rel_id_to_image):
    """
    Extract paragraph text:
    - Convert OMML math to LaTeX $ ... $
    - Embed converted MathType formula images as inline <img> tags
    - Extract normal text runs
    """
    p_xml = p._element
    chunks = []
    _walk_xml_node(p_xml, rel_id_to_image, chunks)
    full_text = "".join(chunks).strip()
    return full_text if full_text else (p.text or "")


def _walk_xml_node(elem, rel_id_to_image, chunks):
    """
    Recursively walk XML nodes in a paragraph element to extract text,
    OMML math (→ LaTeX), and image references (→ <img> tags / LaTeX).
    """
    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

    # 0. Handle object nodes (MathType OLE objects) to avoid duplicate rendering
    if tag == "object":
        for child_elem in elem.iter():
            for attr_key, attr_val in child_elem.attrib.items():
                attr_name = attr_key.split("}")[-1] if "}" in attr_key else attr_key
                if attr_name in ("embed", "id", "href") and attr_val in rel_id_to_image:
                    img_val = rel_id_to_image[attr_val]
                    if img_val.startswith("$") and img_val.endswith("$"):
                        chunks.append(f" {img_val} ")
                    else:
                        chunks.append(
                            f' <img src="{img_val}" class="docx-math-img" '
                            f'style="vertical-align:middle; max-height:45px; margin:0 4px; display:inline-block;" /> '
                        )
                    return
        return

    # 1. OMML Office Math → LaTeX
    if tag in ("oMath", "oMathPara"):
        latex_math = _omml_to_latex(elem)
        if latex_math:
            chunks.append(f" ${latex_math}$ ")
        return

    # 2. Text node <w:t>
    if tag == "t" and elem.text:
        chunks.append(elem.text)
        return

    # 3. Check alt/descr/title attributes for LaTeX text
    found_alt = False
    for attr_key, attr_val in elem.attrib.items():
        attr_name = attr_key.split("}")[-1] if "}" in attr_key else attr_key
        if attr_name in ("alt", "descr", "title") and attr_val:
            val_str = str(attr_val).strip()
            if _is_math_latex_str(val_str):
                clean_str = val_str.strip("$")
                chunks.append(f" ${clean_str}$ ")
                found_alt = True
                break

    if found_alt:
        return

    # 4. Check for image relationship ID (blip r:embed, imagedata r:id, etc.)
    found_img = False
    for attr_key, attr_val in elem.attrib.items():
        attr_name = attr_key.split("}")[-1] if "}" in attr_key else attr_key
        if attr_name in ("embed", "id", "href") and attr_val in rel_id_to_image:
            img_val = rel_id_to_image[attr_val]
            if img_val.startswith("$") and img_val.endswith("$"):
                chunks.append(f" {img_val} ")
            else:
                chunks.append(
                    f' <img src="{img_val}" class="docx-math-img" '
                    f'style="vertical-align:middle; max-height:45px; margin:0 4px; display:inline-block;" /> '
                )
            found_img = True
            break

    if found_img:
        return

    # 5. Recurse into children
    for child in elem:
        _walk_xml_node(child, rel_id_to_image, chunks)


# ---------------------------------------------------------------------------
#  Math detection & OMML→LaTeX converter
# ---------------------------------------------------------------------------

def _is_math_latex_str(s):
    """Check if a string looks like it contains LaTeX math."""
    if not s or len(str(s).strip()) < 2:
        return False
    s_clean = str(s).strip()
    if s_clean.startswith("$") and s_clean.endswith("$"):
        return True
    indicators = [
        "\\frac", "\\sqrt", "\\sum", "\\int", "\\lim",
        "\\alpha", "\\beta", "\\gamma", "\\delta", "\\theta", "\\pi",
        "\\mathbb", "\\mathcal", "\\forall", "\\exists",
        "^{", "_{",
    ]
    return any(ind in s_clean for ind in indicators)


def _omml_to_latex(elem):
    """
    Recursive OMML XML element walker to generate LaTeX math strings.
    Handles fractions, radicals, superscripts, subscripts, delimiters,
    accents, n-ary operators, matrices, etc.
    """
    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

    if tag == "t":
        return elem.text or ""

    if tag in ("oMath", "oMathPara", "e", "sub", "sup", "num", "den", "deg"):
        return "".join([_omml_to_latex(c) for c in elem])

    if tag == "r":
        parts = []
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "t" and c.text:
                parts.append(c.text)
        return "".join(parts)

    if tag == "f":
        num_elem = den_elem = None
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "num":
                num_elem = c
            elif ctag == "den":
                den_elem = c
        num = _omml_to_latex(num_elem) if num_elem is not None else ""
        den = _omml_to_latex(den_elem) if den_elem is not None else ""
        return f"\\frac{{{num}}}{{{den}}}"

    if tag == "rad":
        deg_elem = e_elem = None
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "deg":
                deg_elem = c
            elif ctag == "e":
                e_elem = c
        expr = _omml_to_latex(e_elem) if e_elem is not None else ""
        deg_text = _omml_to_latex(deg_elem).strip() if deg_elem is not None else ""
        if deg_text and deg_text != "2":
            return f"\\sqrt[{deg_text}]{{{expr}}}"
        return f"\\sqrt{{{expr}}}"

    if tag == "sSup":
        e_elem = sup_elem = None
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "e":
                e_elem = c
            elif ctag == "sup":
                sup_elem = c
        base = _omml_to_latex(e_elem) if e_elem is not None else ""
        sup = _omml_to_latex(sup_elem) if sup_elem is not None else ""
        return f"{{{base}}}^{{{sup}}}"

    if tag == "sSub":
        e_elem = sub_elem = None
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "e":
                e_elem = c
            elif ctag == "sub":
                sub_elem = c
        base = _omml_to_latex(e_elem) if e_elem is not None else ""
        sub = _omml_to_latex(sub_elem) if sub_elem is not None else ""
        return f"{{{base}}}_{{{sub}}}"

    if tag == "sSubSup":
        e_elem = sub_elem = sup_elem = None
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "e":
                e_elem = c
            elif ctag == "sub":
                sub_elem = c
            elif ctag == "sup":
                sup_elem = c
        base = _omml_to_latex(e_elem) if e_elem is not None else ""
        sub = _omml_to_latex(sub_elem) if sub_elem is not None else ""
        sup = _omml_to_latex(sup_elem) if sup_elem is not None else ""
        return f"{{{base}}}_{{{sub}}}^{{{sup}}}"

    if tag == "d":
        inner_parts = []
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "e":
                inner_parts.append(_omml_to_latex(c))
        content = ",".join(inner_parts)
        return f"\\left({content}\\right)"

    if tag == "nary":
        sub_elem = sup_elem = e_elem = None
        chr_val = ""
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "naryPr":
                for prop in c:
                    ptag = prop.tag.split("}")[-1] if "}" in prop.tag else prop.tag
                    if ptag == "chr":
                        for ak, av in prop.attrib.items():
                            aname = ak.split("}")[-1] if "}" in ak else ak
                            if aname == "val":
                                chr_val = av
            elif ctag == "sub":
                sub_elem = c
            elif ctag == "sup":
                sup_elem = c
            elif ctag == "e":
                e_elem = c

        op_map = {"∑": "\\sum", "∫": "\\int", "∏": "\\prod", "∐": "\\coprod"}
        op = op_map.get(chr_val, chr_val or "\\sum")
        sub = _omml_to_latex(sub_elem) if sub_elem is not None else ""
        sup = _omml_to_latex(sup_elem) if sup_elem is not None else ""
        expr = _omml_to_latex(e_elem) if e_elem is not None else ""
        result = op
        if sub:
            result += f"_{{{sub}}}"
        if sup:
            result += f"^{{{sup}}}"
        result += f" {expr}"
        return result

    if tag == "limLow":
        e_elem = lim_elem = None
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "e":
                e_elem = c
            elif ctag == "lim":
                lim_elem = c
        base = _omml_to_latex(e_elem) if e_elem is not None else ""
        lim = _omml_to_latex(lim_elem) if lim_elem is not None else ""
        return f"{base}_{{{lim}}}"

    if tag == "bar":
        e_elem = None
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "e":
                e_elem = c
        expr = _omml_to_latex(e_elem) if e_elem is not None else ""
        return f"\\overline{{{expr}}}"

    if tag == "m":
        rows = []
        for c in elem:
            ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
            if ctag == "mr":
                cells = []
                for cell in c:
                    ctag2 = cell.tag.split("}")[-1] if "}" in cell.tag else cell.tag
                    if ctag2 == "e":
                        cells.append(_omml_to_latex(cell))
                rows.append(" & ".join(cells))
        return "\\begin{matrix}" + " \\\\ ".join(rows) + "\\end{matrix}"

    # Default: recurse into all children
    return "".join([_omml_to_latex(c) for c in elem])


def _map_template_type(raw_type):
    t = raw_type.upper()
    if "SINGLE" in t or "TRẮC NGHIỆM" in t:
        return "single"
    if "MULTIPLE" in t or "NHIỀU ĐÁP ÁN" in t:
        return "multiple_choice"
    if "TRUE" in t or "ĐÚNG" in t:
        return "true_false"
    if "SHORT" in t or "NGẮN" in t:
        return "short_answer"
    if "ESSAY" in t or "TỰ LUẬN" in t:
        return "essay"
    return "single"
