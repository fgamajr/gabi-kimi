from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from src.backend.repo_index.config import settings

COPYISH_RE = re.compile(r"( copy\b|\.bak$|__pycache__|\.venv|~\$)", re.IGNORECASE)
IMPORT_RE = re.compile(r"^(?:from\s+\S+\s+import|import\s+\S+)", re.IGNORECASE)
CLASS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:class|interface)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
FUNC_RE = re.compile(r"^\s*(?:async\s+def|def|function)\s+([A-Za-z_][A-Za-z0-9_]*)")
TEST_RE = re.compile(
    r"^\s*(?:def|it\(|test\(|describe\(|test)\s+([\"']?[Tt]est[A-Za-z0-9_]*)"
)
DECORATOR_RE = re.compile(r"^\s*@")
CONFIG_RE = re.compile(r"^\s*[A-Z_][A-Z0-9_]*\s*=")
COMMENT_RE = re.compile(r"^\s*(#|//|/\*|\*)")
MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")


@dataclass(frozen=True)
class SourceDescriptor:
    source_type: str
    authority_weight: float


def should_ignore_path(path: Path) -> bool:
    path_str = str(path)
    if COPYISH_RE.search(path_str):
        return True
    if path.name in settings.skip_files:
        return True
    rel = path.relative_to(settings.repo_root)
    parts = rel.parts
    if any(part in settings.skip_dirs for part in parts[:-1]):
        return True
    if path.name in settings.special_text_filenames:
        return False
    return path.suffix.lower() not in settings.text_extensions


def _language_for_path(path: Path) -> tuple[str, str]:
    if path.name in settings.special_text_filenames:
        return "docker", "build"
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python", "code"
    if suffix in {".ts", ".tsx"}:
        return "typescript", "code"
    if suffix in {".js", ".jsx", ".mjs"}:
        return "javascript", "code"
    if suffix == ".md":
        return "markdown", "docs"
    if suffix in {
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".example",
    }:
        return "config", "config"
    if suffix == ".sh":
        return "shell", "script"
    if suffix == ".sql":
        return "sql", "config"
    if suffix in settings.text_extensions:
        return suffix.lstrip("."), "text"
    return "text", "text"


def classify_source(path: Path) -> SourceDescriptor | None:
    if should_ignore_path(path):
        return None
    rel = path.relative_to(settings.repo_root)
    parts = rel.parts
    source_type = "unknown"
    authority = 0.5
    if (
        "tests" in parts
        or path.name.startswith("test_")
        or path.name.endswith(".test.ts")
        or path.name.endswith(".test.tsx")
    ):
        source_type = "tests"
        authority = 0.6
    elif "docs" in parts:
        source_type = "docs"
        authority = 0.85
    elif "ops" in parts:
        source_type = "ops"
        authority = 0.7
    elif "src/backend" in "/".join(parts):
        source_type = "backend"
        authority = 0.9
    elif "src/frontend" in "/".join(parts):
        source_type = "frontend"
        authority = 0.8
    elif parts[0] == ".agents" or parts[0] == ".claude":
        source_type = "agent_config"
        authority = 0.75
    else:
        language, kind = _language_for_path(path)
        if kind == "docs":
            source_type = "docs"
            authority = 0.85
        elif kind == "config":
            source_type = "config"
            authority = 0.6
        elif kind == "script":
            source_type = "ops"
            authority = 0.7
        else:
            source_type = "other"
            authority = 0.5
    if path.name in {"README.md", "AGENTS.md", "CLAUDE.md", "SKILL.md"}:
        authority = 0.95
    if "node_modules" in parts or "dist" in parts or "build" in parts:
        authority = 0.1
    return SourceDescriptor(source_type=source_type, authority_weight=authority)


def canonical_rank(path: Path) -> tuple[int, int, str]:
    ext_rank = (
        0
        if path.suffix.lower() == ".py"
        else (1 if path.suffix.lower() in {".ts", ".tsx", ".md"} else 99)
    )
    penalty = 0
    path_str = str(path).lower()
    if "__pycache__" in path_str:
        penalty += 10
    if ".bak" in path_str:
        penalty += 5
    return (ext_rank, penalty, path_str)


def infer_section_type(text: str, language: str, path: Path) -> str:
    lines = text.splitlines()
    if not lines:
        return "body"
    first_line = lines[0].strip()
    if IMPORT_RE.match(first_line):
        return "imports"
    if DECORATOR_RE.match(first_line):
        return "decorator"
    if CLASS_RE.match(first_line):
        return "class"
    if FUNC_RE.match(first_line):
        if TEST_RE.search(first_line):
            return "test"
        return "function"
    if CONFIG_RE.match(first_line):
        return "config"
    if (
        COMMENT_RE.match(first_line)
        and len(lines) > 1
        and (CLASS_RE.match(lines[1]) or FUNC_RE.match(lines[1]))
    ):
        return "class" if CLASS_RE.match(lines[1]) else "function"
    if language == "markdown":
        if MD_HEADING_RE.match(first_line):
            return "markdown_section"
        return "markdown_body"
    non_empty = [line for line in lines if line.strip()]
    code_like = sum(
        1 for line in non_empty[:20] if FUNC_RE.match(line) or CLASS_RE.match(line)
    )
    if code_like >= 2:
        return "mixed_symbols"
    if len(non_empty) > 0 and all(COMMENT_RE.match(line) for line in non_empty[:5]):
        return "comment_block"
    return "body"
