"""Minimal sandboxed LaTeX block renderer for production deployment."""
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)
MAX_SOURCE_SIZE = 200_000


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/")
def index():
    return jsonify({
        "service": "question-latex-renderer",
        "status": "ok",
        "endpoints": {
            "health": "/health",
            "render": "POST /render",
        },
    })


@app.post("/render")
def render():
    expected_token = os.environ.get("LATEX_RENDERER_TOKEN", "")
    if expected_token:
        supplied = request.headers.get("Authorization", "")
        if supplied != f"Bearer {expected_token}":
            return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    source = payload.get("source", "")
    if not isinstance(source, str) or not source.strip():
        return jsonify({"error": "source is required"}), 400
    if len(source.encode("utf-8")) > MAX_SOURCE_SIZE:
        return jsonify({"error": "source is too large"}), 413

    pdflatex = shutil.which("pdflatex")
    pdftocairo = shutil.which("pdftocairo")
    if not pdflatex or not pdftocairo:
        return jsonify({"error": "renderer dependencies are unavailable"}), 503

    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    workdir = Path(tempfile.mkdtemp(prefix="latex_block_"))
    try:
        tex_path = workdir / "block.tex"
        tex_path.write_text(
            "\\documentclass[preview,border=2pt]{standalone}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage[T5]{fontenc}\n"
            "\\usepackage{amsmath,amssymb,graphicx,array,booktabs,tikz}\n"
            "\\usetikzlibrary{calc,angles,quotes,patterns,positioning}\n"
            "\\pagestyle{empty}\n\\begin{document}\n"
            + source + "\n\\end{document}\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [pdflatex, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", tex_path.name],
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return jsonify({"error": "LaTeX compilation failed", "cache_key": digest}), 422

        svg_base = workdir / "block"
        result = subprocess.run(
            [pdftocairo, "-singlefile", "-svg", "block.pdf", str(svg_base)],
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        svg_path = workdir / "block.svg"
        if result.returncode != 0 or not svg_path.exists():
            return jsonify({"error": "SVG conversion failed", "cache_key": digest}), 422
        return jsonify({"svg": svg_path.read_text(encoding="utf-8"), "cache_key": digest})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "LaTeX compilation timed out", "cache_key": digest}), 408
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
