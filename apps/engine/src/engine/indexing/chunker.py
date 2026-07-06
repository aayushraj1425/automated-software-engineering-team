"""Splits repository files into chunks for the search index.

Version 1 is deliberately simple: overlapping line windows over every text
file whose extension we recognize. AST-aware chunking with tree-sitter
(splitting at functions and classes) replaces this later without changing
the table schema — a chunk stays (path, language, line range, text).
"""

from dataclasses import dataclass
from pathlib import Path

CHUNK_LINES = 60
OVERLAP_LINES = 10
MAX_FILE_BYTES = 512_000
MAX_FILES = 2_000

LANGUAGES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".java": "java",
    ".kt": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".md": "markdown",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".sh": "shell",
    ".ps1": "powershell",
    ".txt": "text",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".turbo",
    ".workspaces",
}


@dataclass(frozen=True)
class Chunk:
    path: str  # POSIX-style, relative to the repository root
    language: str
    start_line: int
    end_line: int
    content: str


def chunk_repository(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    files_seen = 0
    for file in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in file.parts):
            continue
        if not file.is_file():
            continue
        language = LANGUAGES.get(file.suffix.lower())
        if language is None or file.stat().st_size > MAX_FILE_BYTES:
            continue
        files_seen += 1
        if files_seen > MAX_FILES:
            break
        chunks.extend(_chunk_file(file, file.relative_to(root).as_posix(), language))
    return chunks


def _chunk_file(file: Path, rel_path: str, language: str) -> list[Chunk]:
    lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
    chunks: list[Chunk] = []
    step = CHUNK_LINES - OVERLAP_LINES
    start = 0
    while start < len(lines):
        window = lines[start : start + CHUNK_LINES]
        content = "\n".join(window).strip()
        if content:
            chunks.append(
                Chunk(
                    path=rel_path,
                    language=language,
                    start_line=start + 1,
                    end_line=start + len(window),
                    content=content,
                )
            )
        if start + CHUNK_LINES >= len(lines):
            break
        start += step
    return chunks
