"""Server-side renderer for LaTeX blocks that MathJax cannot render.

Production should set LATEX_RENDERER_URL to a sandboxed renderer service. A
local pdflatex fallback is provided for traditional servers, but is never
required on the end user's device.
"""
import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ASSET_DIR = Path(os.path.dirname(os.path.dirname(__file__))) / "static" / "uploads" / "questions"


def render_latex_block(source):
    """Return a web URL for a rendered SVG, or ``None`` when unavailable."""
    if not source or len(source) > 200_000:
        return None
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    output = ASSET_DIR / f"latex_{digest}.svg"
    if output.exists():
        return f"/static/uploads/questions/{output.name}"

    remote = os.environ.get("LATEX_RENDERER_URL", "").rstrip("/")
    if remote:
        url = _render_remote(remote, source, digest)
        if url:
            return url

    return _render_local(source, digest, output)


def _render_remote(base_url, source, digest):
    try:
        import requests
        headers = {}
        token = os.environ.get("LATEX_RENDERER_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = requests.post(
            f"{base_url}/render",
            json={"source": source, "format": "svg", "cache_key": digest},
            headers=headers,
            timeout=30,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        if data.get("svg_url"):
            return data["svg_url"]
        svg = data.get("svg")
        if not svg or "<svg" not in svg:
            return None
        output = ASSET_DIR / f"latex_{digest}.svg"
        output.write_text(svg, encoding="utf-8")
        return f"/static/uploads/questions/{output.name}"
    except Exception:
        return None


def _render_local(source, digest, output):
    pdflatex = shutil.which("pdflatex") or shutil.which("xelatex")
    pdftocairo = shutil.which("pdftocairo")
    if not pdflatex or not pdftocairo:
        return None

    workdir = Path(tempfile.mkdtemp(prefix="latex_render_"))
    try:
        tex = workdir / "fragment.tex"
        tex.write_text(
            "\\documentclass[preview,border=2pt]{standalone}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage{amsmath,amssymb,graphicx,array,tikz}\n"
            "\\begin{document}\n" + source + "\n\\end{document}\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [pdflatex, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", tex.name],
            cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
        if result.returncode != 0 or not (workdir / "fragment.pdf").exists():
            return None
        svg_base = workdir / "rendered"
        result = subprocess.run(
            [pdftocairo, "-singlefile", "-svg", "fragment.pdf", str(svg_base)],
            cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
        rendered = workdir / "rendered.svg"
        if result.returncode != 0 or not rendered.exists():
            return None
        shutil.copyfile(rendered, output)
        return f"/static/uploads/questions/{output.name}"
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
