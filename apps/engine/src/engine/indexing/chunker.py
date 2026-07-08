"""Splits repository files into chunks for the search index.

Small files stay whole. Larger files in a known grammar (Python, JavaScript,
TypeScript, TSX, Java, Kotlin) are split by tree-sitter at their real
boundaries — one chunk per top-level function or class — so a definition is
never cut in half; imports and loose code between definitions fall back to
overlapping line windows. Any
unknown extension, empty parse, or parser error also falls back to line
windows, so the chunker never fails a file. A chunk stays
(path, language, line range, text), so the schema does not change.

Design note: docs/architecture/AST_CHUNKING.md.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tree_sitter import Parser
from tree_sitter_language_pack import get_parser

CHUNK_LINES = 60
OVERLAP_LINES = 10
MAX_DEFINITION_LINES = 200  # a bigger definition is windowed so no chunk is unbounded
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
    ".kts": "kotlin",
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

# Extensions we split by syntax tree → the tree-sitter grammar to use.
AST_GRAMMARS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
}

# Node types that count as a top-level definition worth its own chunk.
_DEFINITION_TYPES: dict[str, set[str]] = {
    "python": {"function_definition", "decorated_definition", "class_definition"},
    "javascript": {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
    },
    "typescript": {
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "abstract_class_declaration",
        "interface_declaration",
        "enum_declaration",
        "type_alias_declaration",
    },
    "java": {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "annotation_type_declaration",
    },
    "kotlin": {
        "class_declaration",  # class, interface, and enum class all parse to this
        "function_declaration",
        "object_declaration",
    },
}
_DEFINITION_TYPES["tsx"] = _DEFINITION_TYPES["typescript"]

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


def iter_source_files(root: Path) -> Iterator[tuple[Path, str, str]]:
    """Every indexable file as (absolute path, POSIX relative path, language).

    Applies the same skip-list, size, and file-count caps the index relies on,
    so the chunker and the incremental indexer always agree on which files count.
    """
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
        yield file, file.relative_to(root).as_posix(), language


def chunk_repository(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for file, rel_path, language in iter_source_files(root):
        chunks.extend(_chunk_file(file, rel_path, language))
    return chunks


def chunk_file(file: Path, rel_path: str, language: str) -> list[Chunk]:
    """Chunks a single already-selected file (used by incremental re-indexing)."""
    return _chunk_file(file, rel_path, language)


def _chunk_file(file: Path, rel_path: str, language: str) -> list[Chunk]:
    text = (
        file.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    )
    lines = text.split("\n")

    # Small files are a single coherent unit — nothing to cut.
    if len(lines) <= CHUNK_LINES:
        return _window(lines, 1, len(lines), rel_path, language)

    grammar = AST_GRAMMARS.get(file.suffix.lower())
    if grammar is not None:
        try:
            ast_chunks = _chunk_by_ast(text, lines, rel_path, language, grammar)
        except Exception:
            ast_chunks = None
        if ast_chunks:
            return ast_chunks

    return _window(lines, 1, len(lines), rel_path, language)


def _chunk_by_ast(
    text: str, lines: list[str], rel_path: str, language: str, grammar: str
) -> list[Chunk]:
    """One chunk per top-level definition; gaps between them become windows."""
    tree = _parser(grammar).parse(text.encode("utf-8"))
    definition_types = _DEFINITION_TYPES.get(grammar, set())

    chunks: list[Chunk] = []
    cursor = 1  # next 1-based line not yet emitted
    for node in tree.root_node.named_children:
        if not _is_definition(node, definition_types):
            continue  # swept into the surrounding gap window below
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        if start_line > cursor:  # imports / loose code before this definition
            chunks.extend(_window(lines, cursor, start_line - 1, rel_path, language))
        if end_line - start_line + 1 > MAX_DEFINITION_LINES:
            chunks.extend(_window(lines, start_line, end_line, rel_path, language))
        else:
            chunks.extend(_one_chunk(lines, start_line, end_line, rel_path, language))
        cursor = end_line + 1
    if cursor <= len(lines):  # trailing loose code (or the whole file if no definitions)
        chunks.extend(_window(lines, cursor, len(lines), rel_path, language))
    return chunks


def _is_definition(node, definition_types: set[str]) -> bool:
    if node.type in definition_types:
        return True
    # `export function foo()` / `export class Bar` wrap the declaration.
    if node.type == "export_statement":
        return any(child.type in definition_types for child in node.named_children)
    return False


def _one_chunk(lines: list[str], first: int, last: int, path: str, language: str) -> list[Chunk]:
    content = "\n".join(lines[first - 1 : last]).strip()
    if not content:
        return []
    return [Chunk(path=path, language=language, start_line=first, end_line=last, content=content)]


def _window(lines: list[str], first: int, last: int, path: str, language: str) -> list[Chunk]:
    """Overlapping line windows over the 1-based inclusive range [first, last]."""
    segment = lines[first - 1 : last]
    chunks: list[Chunk] = []
    step = CHUNK_LINES - OVERLAP_LINES
    index = 0
    while index < len(segment):
        window = segment[index : index + CHUNK_LINES]
        content = "\n".join(window).strip()
        if content:
            chunks.append(
                Chunk(
                    path=path,
                    language=language,
                    start_line=first + index,
                    end_line=first + index + len(window) - 1,
                    content=content,
                )
            )
        if index + CHUNK_LINES >= len(segment):
            break
        index += step
    return chunks


@lru_cache(maxsize=8)
def _parser(grammar: str) -> Parser:
    return get_parser(grammar)  # type: ignore[arg-type]
