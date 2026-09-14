"""
llm.py — Thin wrapper around Groq for RepoPilot.

Jobs:
  1. Answer natural-language questions about retrieved code chunks.
  2. Explain static-analysis findings and suggest fixes.
  3. Generate a repository architecture overview.
  4. Generate a repository health summary.

RepoPilot itself handles parsing, retrieval, and static analysis.
The LLM only explains the information provided by those components.
"""

import os
from typing import List

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------
# Groq configuration
# ---------------------------------------------------------

_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

_MODEL = os.getenv(
    "REPOPILOT_MODEL",
    "openai/gpt-oss-20b"
)

_client = None

if _API_KEY:
    try:
        from openai import OpenAI

        _client = OpenAI(
            api_key=_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )

    except Exception:
        _client = None


# ---------------------------------------------------------
# Availability
# ---------------------------------------------------------

def llm_available() -> bool:
    return _client is not None


# ---------------------------------------------------------
# Common LLM call
# ---------------------------------------------------------

def _chat(system: str, user: str, max_tokens: int = 500) -> str:

    if not _client:
        return (
            "[LLM not configured — set GROQ_API_KEY in .env "
            "to enable natural-language explanations.]"
        )

    try:

        response = _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system
                },
                {
                    "role": "user",
                    "content": user
                }
            ],
            max_tokens=max_tokens,
            temperature=0.2
        )

        if not response.choices:
            return "[LLM returned an empty response.]"

        content = response.choices[0].message.content

        if not content:
            return "[LLM returned an empty response.]"

        return content.strip()

    except Exception as e:

        return (
            f"[LLM call failed: {e}. "
            "Showing raw analysis only.]"
        )


# ---------------------------------------------------------
# Ask questions about repository code
# ---------------------------------------------------------

def answer_question(
    question: str,
    context_chunks: List[dict]
) -> str:

    if not context_chunks:
        return (
            "I couldn't find any code in this repo relevant "
            "to that question."
        )

    context_block = "\n\n".join(
        f"### {c['file_path']} :: "
        f"{c['kind']} {c['name']}\n"
        f"```python\n{c['source']}\n```"
        for c in context_chunks
    )

    system = (
        "You are RepoPilot, a codebase analysis assistant. "
        "Answer the user's question using ONLY the provided "
        "code context. "
        "Cite file paths and function or class names in your "
        "answer whenever possible. "
        "Do not invent code, files, functions, dependencies, "
        "or architecture that is not supported by the context. "
        "If the provided context is insufficient, say so plainly."
    )

    user = (
        f"CODE CONTEXT:\n"
        f"{context_block}\n\n"
        f"QUESTION:\n"
        f"{question}"
    )

    return _chat(
        system,
        user,
        max_tokens=600
    )


# ---------------------------------------------------------
# Explain static-analysis finding
# ---------------------------------------------------------

def explain_finding(finding: dict) -> str:

    system = (
        "You are RepoPilot, a codebase analysis assistant. "
        "You will be given one static-analysis finding. "
        "Explain it in 2-4 sentences. "
        "First explain the risk in simple language. "
        "Then provide a concrete fix suggestion. "
        "Do not invent additional issues."
    )

    user = (
        f"File: {finding['file_path']}, "
        f"line {finding['line']}\n"
        f"Category: {finding['category']}, "
        f"Severity: {finding['severity']}\n"
        f"Raw message: {finding['message']}"
    )

    return _chat(
        system,
        user,
        max_tokens=200
    )


# ---------------------------------------------------------
# Generate architecture overview
# ---------------------------------------------------------

def generate_overview(
    stack: dict,
    file_count: int,
    top_level: List[str]
) -> str:

    lang_summary = ", ".join(
        f"{ext or '(no ext)'}: {count}"
        for ext, count in sorted(
            stack.get("languages", {}).items(),
            key=lambda x: -x[1]
        )
    ) or "no recognized source files"

    frameworks = ", ".join(
        stack.get("framework_hints", [])
    ) or "none detected"

    structure = ", ".join(
        top_level[:15]
    ) or "flat structure"

    system = (
        "You are RepoPilot. "
        "Given file-type counts, detected frameworks, "
        "and top-level directory names for a codebase, "
        "write a short 4-6 sentence architecture overview. "
        "Explain what kind of project it appears to be, "
        "its likely main components, and one or two things "
        "worth checking first. "
        "Only infer from the information provided. "
        "Do not invent specific classes or functions."
    )

    user = (
        f"Files analyzed: {file_count}\n"
        f"Language/file-type breakdown: {lang_summary}\n"
        f"Detected frameworks/manifests: {frameworks}\n"
        f"Top-level structure: {structure}"
    )

    return _chat(
        system,
        user,
        max_tokens=350
    )


# ---------------------------------------------------------
# Repository health summary
# ---------------------------------------------------------

def summarize_repo(
    file_count: int,
    chunk_count: int,
    top_findings: List[dict]
) -> str:

    if not top_findings:

        findings_block = (
            "No high/medium severity issues detected."
        )

    else:

        findings_block = "\n".join(
            f"- [{f['severity']}] "
            f"{f['file_path']}:{f['line']} — "
            f"{f['message']}"
            for f in top_findings[:10]
        )

    system = (
        "You are RepoPilot. "
        "Write a short 4-6 sentence executive summary "
        "of this codebase's health for a developer seeing "
        "the report for the first time. "
        "Be specific and reference the real numbers and "
        "files provided. "
        "Do not invent additional findings."
    )

    user = (
        f"Files analyzed: {file_count}\n"
        f"Functions/classes indexed: {chunk_count}\n"
        f"Top findings:\n{findings_block}"
    )

    return _chat(
        system,
        user,
        max_tokens=300
    )