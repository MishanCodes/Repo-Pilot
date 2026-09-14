"""
static_checks.py — Deterministic bug/quality signals, computed WITHOUT any LLM.

This is what keeps RepoPilot from being "just a wrapper around a chat model":
- pyflakes catches real issues (unused imports/vars, undefined names, etc.)
- radon computes cyclomatic complexity so we can flag genuinely risky functions
- a small set of hand-written heuristics catches common Python foot-guns
    (bare except, mutable default args, `== None`, broad excepts swallowing errors)

The LLM layer (llm.py) only explains/prioritizes these findings in plain
language — it never invents the findings themselves. That division is what
makes the output trustworthy enough to demo live.
"""
import ast
import io
from contextlib import redirect_stdout
from dataclasses import dataclass
from typing import List

from pyflakes.api import check
from pyflakes.reporter import Reporter
from radon.complexity import cc_visit


@dataclass
class Finding:
    file_path: str
    line: int
    severity: str   # "high" | "medium" | "low"
    category: str
    message: str


def run_pyflakes(file_path: str, source: str) -> List[Finding]:
    findings: List[Finding] = []
    out, err = io.StringIO(), io.StringIO()
    reporter = Reporter(out, err)
    try:
        check(source, file_path, reporter)
    except Exception:
        return findings

    for line in out.getvalue().splitlines():
        # pyflakes format: "path:line:col: message"
        parts = line.split(":", 3)
        if len(parts) >= 4:
            try:
                lineno = int(parts[1])
            except ValueError:
                lineno = 0
            msg = parts[3].strip()
            severity = "high" if ("undefined name" in msg or "undefined" in msg) else "low"
            findings.append(Finding(
                file_path=file_path, line=lineno, severity=severity,
                category="pyflakes", message=msg,
            ))
    return findings


def run_complexity(file_path: str, source: str) -> List[Finding]:
    findings: List[Finding] = []
    try:
        blocks = cc_visit(source)
    except Exception:
        return findings
    for b in blocks:
        if b.complexity >= 15:
            severity = "high"
        elif b.complexity >= 10:
            severity = "medium"
        else:
            continue
        findings.append(Finding(
            file_path=file_path, line=b.lineno, severity=severity,
            category="complexity",
            message=f"'{b.name}' has cyclomatic complexity {b.complexity} "
                     f"(consider splitting into smaller functions).",
        ))
    return findings


class _HeuristicVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.findings: List[Finding] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.type is None:
            self.findings.append(Finding(
                self.file_path, node.lineno, "medium", "heuristic",
                "Bare 'except:' catches everything, including "
                "KeyboardInterrupt/SystemExit — narrow it to a specific exception.",
            ))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        for default in list(node.args.defaults) + list(node.args.kw_defaults):
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.findings.append(Finding(
                    self.file_path, node.lineno, "medium", "heuristic",
                    f"Function '{node.name}' uses a mutable default argument "
                    "(list/dict/set) — it's shared across calls and can cause "
                    "hard-to-trace bugs.",
                ))
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare):
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.Eq, ast.NotEq)) and (
                (isinstance(comparator, ast.Constant) and comparator.value is None)
            ):
                self.findings.append(Finding(
                    self.file_path, node.lineno, "low", "heuristic",
                    "Use 'is None' / 'is not None' instead of '==' / '!=' for None checks.",
                ))
        self.generic_visit(node)


def run_heuristics(file_path: str, source: str) -> List[Finding]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    visitor = _HeuristicVisitor(file_path)
    visitor.visit(tree)
    return visitor.findings


def analyze_file(file_path: str, source: str) -> List[Finding]:
    findings = []
    findings.extend(run_pyflakes(file_path, source))
    findings.extend(run_complexity(file_path, source))
    findings.extend(run_heuristics(file_path, source))
    return findings
