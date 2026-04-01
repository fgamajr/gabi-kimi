from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INDEX_DIR = REPO_ROOT / ".ai"
DB_PATH = INDEX_DIR / "repo_index.db"
MANIFESTS_ROOT = INDEX_DIR / "manifests"
LEDGER_ROOT = INDEX_DIR / "ledger"

_SKIP_DIRS = frozenset(
    {
        ".ai",
        ".git",
        "worktrees",
        ".idea",
        ".next",
        ".playwright-cli",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".venv-mac",
        ".vite",
        ".vscode",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "ops/data/raw_export",
    }
)
_SKIP_FILES = frozenset(
    {
        ".DS_Store",
        "bun.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
    }
)
_SPECIAL_TEXT_FILENAMES = frozenset(
    {".dockerignore", ".gitignore", "Dockerfile", "Makefile"}
)
_TEXT_EXTENSIONS = frozenset(
    {
        ".c",
        ".cfg",
        ".conf",
        ".cpp",
        ".css",
        ".csv",
        ".env",
        ".example",
        ".go",
        ".h",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mjs",
        ".py",
        ".rb",
        ".rs",
        ".sh",
        ".sql",
        ".svg",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
MAX_FILE_BYTES = 512_000
CHUNK_TARGET_CHARS = 4_000
WINDOW_LINES = 80
WINDOW_OVERLAP = 12
MAX_CHUNKS_PER_FILE = 64


@dataclass
class Settings:
    repo_root: Path = REPO_ROOT
    index_dir: Path = INDEX_DIR
    db_path: Path = DB_PATH
    manifests_root: Path = MANIFESTS_ROOT
    ledger_root: Path = LEDGER_ROOT
    skip_dirs: set[str] = field(default_factory=lambda: set(_SKIP_DIRS))
    skip_files: set[str] = field(default_factory=lambda: set(_SKIP_FILES))
    special_text_filenames: set[str] = field(
        default_factory=lambda: set(_SPECIAL_TEXT_FILENAMES)
    )
    text_extensions: set[str] = field(default_factory=lambda: set(_TEXT_EXTENSIONS))
    max_file_bytes: int = MAX_FILE_BYTES
    chunk_target_chars: int = CHUNK_TARGET_CHARS
    window_lines: int = WINDOW_LINES
    window_overlap: int = WINDOW_OVERLAP
    max_chunks_per_file: int = MAX_CHUNKS_PER_FILE
    embedding_provider: str = "openai-compatible"
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int | None = None
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_timeout_sec: float = 30.0
    embedding_batch_size: int = 16
    embedding_api_key: str = ""
    embedding_verify_tls: bool = True
    pipeline_fingerprint: str = "v1"
    query_logs_path: Path = LEDGER_ROOT / "queries.jsonl"
    scoring_profiles_path: Path = LEDGER_ROOT / "scoring_profiles.json"
    scoring_feedback_path: Path = LEDGER_ROOT / "scoring_feedback.jsonl"


settings = Settings()
