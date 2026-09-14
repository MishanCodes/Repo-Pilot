"""
app.py — RepoPilot web server.

Endpoints:
  GET  /                 UI
  POST /api/analyze      upload a .zip of a repo -> parses, indexes, runs static checks
  POST /api/ask          ask a question about the currently loaded repo
  GET  /api/findings     get the static-analysis findings for the loaded repo
  POST /api/explain      get an LLM explanation for one specific finding
  GET  /api/overview     project-level architecture overview (language mix, framework, structure)
  GET  /api/source_at    'show me where' — fetch the exact chunk covering a file+line

State is kept in-memory per-process (single active repo at a time) — this is
a portfolio demo tool, not a multi-tenant product, so that tradeoff is fine
and worth being upfront about.
"""
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import asdict

from flask import Flask, jsonify, request, render_template

from parser import (
    build_chunks, collect_python_files, collect_source_files,
    detect_stack, find_chunk_at,
)
from retrieval import CodeIndex
from static_checks import analyze_file, Finding
from llm import answer_question, explain_finding, summarize_repo, generate_overview, llm_available

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB upload cap

STATE = {
    "repo_dir": None,
    "chunks": [],
    "index": None,
    "findings": [],
    "file_count": 0,
    "summary": None,
    "overview": None,
    "stack": None,
}

ALLOWED_EXT = {".zip"}


def _severity_rank(sev: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(sev, 3)


@app.route("/")
def home():
    return render_template("index.html", llm_available=llm_available())


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    if "repo_zip" not in request.files:
        return jsonify({"error": "No file uploaded. Attach a .zip of a Python repo."}), 400

    file = request.files["repo_zip"]
    if not file.filename or os.path.splitext(file.filename)[1].lower() not in ALLOWED_EXT:
        return jsonify({"error": "Please upload a .zip file."}), 400

    # Clean up any previous run
    if STATE["repo_dir"] and os.path.isdir(STATE["repo_dir"]):
        shutil.rmtree(STATE["repo_dir"], ignore_errors=True)

    work_dir = tempfile.mkdtemp(prefix=f"repopilot_{uuid.uuid4().hex[:8]}_")
    zip_path = os.path.join(work_dir, "repo.zip")
    file.save(zip_path)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Guard against zip-slip path traversal before extracting anything.
            for member in zf.namelist():
                member_path = os.path.normpath(os.path.join(work_dir, member))
                if not member_path.startswith(os.path.abspath(work_dir)):
                    return jsonify({"error": "Zip contains unsafe paths."}), 400
            zf.extractall(work_dir)
    except zipfile.BadZipFile:
        return jsonify({"error": "That file isn't a valid zip archive."}), 400

    os.remove(zip_path)

    all_source_files = collect_source_files(work_dir)
    py_files = [p for p in all_source_files if p.endswith(".py")]
    if not all_source_files:
        shutil.rmtree(work_dir, ignore_errors=True)
        return jsonify({"error": "No supported source files found in the archive. "
                                  "RepoPilot indexes .py, .js/.jsx/.ts/.tsx, .java, "
                                  ".c/.cpp/.h, .md, .json, and .yaml files, with full "
                                  "static bug analysis available for Python only."}), 400

    chunks = build_chunks(work_dir)
    index = CodeIndex(chunks)

    # Static bug analysis (pyflakes/radon/heuristics) is Python-specific —
    # run it only on .py files, not the whole multi-language file set.
    findings: list[Finding] = []
    for path in py_files:
        rel = os.path.relpath(path, work_dir)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
        except OSError:
            continue
        findings.extend(analyze_file(rel, source))

    findings.sort(key=lambda f: _severity_rank(f.severity))

    stack = detect_stack(work_dir)
    top_level = sorted({
        os.path.relpath(p, work_dir).split(os.sep)[0] for p in all_source_files
    })

    STATE.update({
        "repo_dir": work_dir,
        "chunks": chunks,
        "index": index,
        "findings": findings,
        "file_count": len(all_source_files),
        "stack": stack,
    })

    top_for_summary = [asdict(f) for f in findings if f.severity in ("high", "medium")]
    summary = summarize_repo(len(py_files), len(chunks), top_for_summary)
    overview = generate_overview(stack, len(all_source_files), top_level)
    STATE["summary"] = summary
    STATE["overview"] = overview

    severity_counts = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

    return jsonify({
        "file_count": len(all_source_files),
        "python_file_count": len(py_files),
        "chunk_count": len(chunks),
        "severity_counts": severity_counts,
        "summary": summary,
        "overview": overview,
        "languages": stack["languages"],
        "framework_hints": stack["framework_hints"],
        "llm_available": llm_available(),
    })


@app.route("/api/findings")
def api_findings():
    findings = STATE["findings"]
    return jsonify({
        "findings": [
            {**asdict(f), "id": i} for i, f in enumerate(findings)
        ]
    })


@app.route("/api/explain", methods=["POST"])
def api_explain():
    data = request.get_json(force=True)
    idx = data.get("id")
    findings = STATE["findings"]
    if idx is None or not (0 <= idx < len(findings)):
        return jsonify({"error": "Invalid finding id."}), 400
    f = findings[idx]
    explanation = explain_finding(asdict(f))
    return jsonify({"explanation": explanation})


@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Question is empty."}), 400
    if not STATE["index"]:
        return jsonify({"error": "No repo loaded yet. Upload a zip first."}), 400

    results = STATE["index"].query(question, top_k=10)
    context = [
        {
            "file_path": r.chunk.file_path,
            "name": r.chunk.name,
            "kind": r.chunk.kind,
            "source": r.chunk.source[:4000],
            "start_line": r.chunk.start_line,
            "end_line": r.chunk.end_line,
        }
        for r in results
    ]
    answer = answer_question(question, context)
    # "Show me where": each source carries its exact location + snippet so
    # the UI can render a "View source" toggle without another round trip.
    sources = [
        {
            "file_path": c["file_path"], "name": c["name"], "kind": c["kind"],
            "start_line": c["start_line"], "end_line": c["end_line"],
            "source": c["source"],
        }
        for c in context
    ]
    return jsonify({"answer": answer, "sources": sources})


@app.route("/api/overview")
def api_overview():
    if not STATE["stack"]:
        return jsonify({"error": "No repo loaded yet. Upload a zip first."}), 400
    return jsonify({
        "overview": STATE["overview"],
        "languages": STATE["stack"]["languages"],
        "framework_hints": STATE["stack"]["framework_hints"],
        "manifest_files": STATE["stack"]["manifest_files"],
    })


@app.route("/api/source_at")
def api_source_at():
    """'Show me where' for a static finding: given file_path + line, return
    the exact function/class chunk that contains it."""
    file_path = request.args.get("file_path", "")
    try:
        line = int(request.args.get("line", "0"))
    except ValueError:
        return jsonify({"error": "Invalid line number."}), 400

    chunk = find_chunk_at(STATE["chunks"], file_path, line)
    if not chunk:
        return jsonify({"error": "No source found for that location."}), 404
    return jsonify({
        "file_path": chunk.file_path, "name": chunk.name, "kind": chunk.kind,
        "start_line": chunk.start_line, "end_line": chunk.end_line,
        "source": chunk.source,
    })


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "llm_available": llm_available()})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
