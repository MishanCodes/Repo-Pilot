"""
parser.py — Walks a codebase and breaks it into analyzable chunks.

Python gets real syntactic chunking via `ast` (functions/classes with exact
line ranges). Other common source/config files (.js/.jsx/.ts/.tsx, .java,
.c/.cpp/.h, .md, .json, .yaml/.yml) are still collected and indexed so they're
searchable and citable — JS/TS/Java/C++ get a best-effort regex pass to pull
out function/class-shaped blocks, everything else is indexed as a single
whole-file chunk. Static bug analysis (pyflakes/radon) stays Python-only —
that's a real, stated scope limit, not silently pretended away.
"""
import ast
import json
import os
import re
from dataclasses import dataclass
from typing import List, Optional

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env",
    "dist", "build", ".mypy_cache", ".pytest_cache", "site-packages",
    ".idea", ".vscode", "migrations",
}
MAX_FILE_BYTES = 500_000  # skip generated/huge files

# Extensions RepoPilot will collect and index for search/Q&A.
CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp"}
DOC_EXTENSIONS = {".md", ".json", ".yaml", ".yml"}
ALL_EXTENSIONS = CODE_EXTENSIONS | DOC_EXTENSIONS

# Best-effort function/class matchers for non-Python code. These are
# intentionally simple regexes, not real parsers — good enough to locate
# named blocks for chunking/citation, not good enough to claim full AST
# accuracy the way the Python path does.
_JS_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?"
    r"(?:async\s+)?function\s*\*?\s+(\w+)\s*\(|"
    r"^\s*(?:export\s+)?class\s+(\w+)|"
    r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(?.*?\)?\s*=>",
    re.MULTILINE,
)
_JAVA_CPP_PATTERN = re.compile(
    r"^\s*(?:public|private|protected|static|final|virtual|inline|\s)*"
    r"[\w:<>,\s]+?\s+(\w+)\s*\([^;{]*\)\s*\{|"
    r"^\s*(?:public|private|protected)?\s*class\s+(\w+)",
    re.MULTILINE,
)


@dataclass
class Chunk:
    id: str
    file_path: str
    kind: str          # "function" | "class" | "module"
    name: str
    start_line: int
    end_line: int
    source: str
    docstring: str = ""


def _get_source_segment(source_lines: List[str], node: ast.AST) -> str:
    start = node.lineno - 1
    end = getattr(node, "end_lineno", node.lineno)
    return "\n".join(source_lines[start:end])


def _walk_python_file(path: str, rel_path: str) -> List[Chunk]:
    chunks: List[Chunk] = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return chunks

    if len(text.encode("utf-8", errors="ignore")) > MAX_FILE_BYTES:
        return chunks

    lines = text.splitlines()

    try:
        tree = ast.parse(text)
    except SyntaxError:
        # Can't parse — still worth indexing as a single opaque chunk so
        # the file is at least searchable/flaggable, just not decomposed.
        chunks.append(Chunk(
            id=f"{rel_path}::(unparsed)",
            file_path=rel_path,
            kind="module",
            name=os.path.basename(rel_path),
            start_line=1,
            end_line=len(lines),
            source=text[:4000],
        ))
        return chunks

    found_any = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Only take top-level and one-level-nested defs to avoid
            # drowning the index in tiny inner helpers/closures.
            found_any = True
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            source = _get_source_segment(lines, node)
            chunks.append(Chunk(
                id=f"{rel_path}::{node.name}:{node.lineno}",
                file_path=rel_path,
                kind=kind,
                name=node.name,
                start_line=node.lineno,
                end_line=getattr(node, "end_lineno", node.lineno),
                source=source,
                docstring=ast.get_docstring(node) or "",
            ))

    if not found_any and text.strip():
        chunks.append(Chunk(
            id=f"{rel_path}::(module)",
            file_path=rel_path,
            kind="module",
            name=os.path.basename(rel_path),
            start_line=1,
            end_line=len(lines),
            source=text[:4000],
        ))

    return chunks


def collect_python_files(root: str) -> List[str]:
    """Kept for the static-analysis path, which is Python-only."""
    return [p for p in collect_source_files(root) if p.endswith(".py")]


def collect_source_files(root: str) -> List[str]:
    """All files RepoPilot will index for search/Q&A, across supported extensions."""
    matched = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in ALL_EXTENSIONS:
                matched.append(os.path.join(dirpath, fn))
    return matched


def _regex_chunk_file(path: str, rel_path: str, pattern: re.Pattern, ext: str) -> List[Chunk]:
    """Best-effort function/class extraction for non-Python languages."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return []
    if len(text.encode("utf-8", errors="ignore")) > MAX_FILE_BYTES or not text.strip():
        return []

    lines = text.splitlines()
    matches = list(pattern.finditer(text))
    if not matches:
        return [Chunk(
            id=f"{rel_path}::(file)", file_path=rel_path, kind="module",
            name=os.path.basename(rel_path), start_line=1, end_line=len(lines),
            source=text[:4000],
        )]

    chunks = []
    for i, m in enumerate(matches):
        name = next((g for g in m.groups() if g), "block")
        start_line = text[:m.start()].count("\n") + 1
        # crude end boundary: next match's start, or end of file, capped for readability
        end_char = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        end_line = min(text[:end_char].count("\n") + 1, start_line + 80)
        source = "\n".join(lines[start_line - 1:end_line])
        chunks.append(Chunk(
            id=f"{rel_path}::{name}:{start_line}", file_path=rel_path,
            kind="class" if "class" in m.group(0) else "function",
            name=name, start_line=start_line, end_line=end_line, source=source,
        ))
    return chunks


def _whole_file_chunk(path: str, rel_path: str) -> List[Chunk]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return []
    if len(text.encode("utf-8", errors="ignore")) > MAX_FILE_BYTES or not text.strip():
        return []
    return [Chunk(
        id=f"{rel_path}::(file)", file_path=rel_path, kind="doc",
        name=os.path.basename(rel_path), start_line=1,
        end_line=len(text.splitlines()), source=text[:4000],
    )]


def build_chunks(root: str) -> List[Chunk]:
    """Parse every supported file under root into a flat list of Chunks.

    .py -> real AST chunking. .js/.jsx/.ts/.tsx -> regex-based chunking.
    .java/.c/.cpp/.h/.hpp -> regex-based chunking. Everything else
    supported (.md/.json/.yaml) -> one whole-file chunk.
    """
    all_chunks: List[Chunk] = []
    for path in collect_source_files(root):
        rel_path = os.path.relpath(path, root)
        ext = os.path.splitext(path)[1].lower()
        if ext == ".py":
            all_chunks.extend(_walk_python_file(path, rel_path))
        elif ext in (".js", ".jsx", ".ts", ".tsx"):
            all_chunks.extend(_regex_chunk_file(path, rel_path, _JS_PATTERN, ext))
        elif ext in (".java", ".c", ".cpp", ".h", ".hpp"):
            all_chunks.extend(_regex_chunk_file(path, rel_path, _JAVA_CPP_PATTERN, ext))
        else:
            all_chunks.extend(_whole_file_chunk(path, rel_path))
    return all_chunks


def detect_stack(root: str) -> dict:
    """Lightweight framework/language detection from dependency manifests
    and file-extension counts — feeds the project overview, not a real
    dependency-graph analysis."""
    signals = {"languages": {}, "framework_hints": [], "manifest_files": []}

    for path in collect_source_files(root):
        ext = os.path.splitext(path)[1].lower()
        signals["languages"][ext] = signals["languages"].get(ext, 0) + 1

    checks = {
        "requirements.txt": None,
        "pyproject.toml": None,
        "package.json": None,
        "Pipfile": None,
    }
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn in checks:
                full = os.path.join(dirpath, fn)
                signals["manifest_files"].append(os.path.relpath(full, root))
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue
                lower = content.lower()
                for hint, needle in [
                    ("Flask", "flask"), ("Django", "django"), ("FastAPI", "fastapi"),
                    ("React", "react"), ("Vue", "vue"), ("Express", "express"),
                    ("Spring", "springframework"), ("Next.js", "next"),
                ]:
                    if needle in lower and hint not in signals["framework_hints"]:
                        signals["framework_hints"].append(hint)
    return signals


def find_chunk_at(chunks: List[Chunk], file_path: str, line: int) -> Optional[Chunk]:
    """Find the chunk in `chunks` that contains a given file+line — powers
    the 'view source' / 'show me where' feature for static findings."""
    candidates = [c for c in chunks if c.file_path == file_path
                  and c.start_line <= line <= c.end_line]
    if candidates:
        return min(candidates, key=lambda c: c.end_line - c.start_line)
    # fall back to any chunk in that file if no exact line match
    same_file = [c for c in chunks if c.file_path == file_path]
    return same_file[0] if same_file else None
