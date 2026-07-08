"""Builds a repository's import graph: which file imports which.

tree-sitter finds the real import statements in each Python, JavaScript,
TypeScript, and TSX file (not ones in comments or strings); an import is kept
only when it resolves to another file in the same repository, so the graph is
the repository's own architecture, not its third-party dependencies. Computed
from the clone during indexing and stored in `code_edges`.

Design note: docs/architecture/DEPENDENCY_GRAPH.md.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from engine.indexing.chunker import AST_GRAMMARS, SKIP_DIRS, _parser

# Import statement node types worth inspecting, per grammar.
_IMPORT_TYPES: dict[str, set[str]] = {
    "python": {"import_statement", "import_from_statement"},
    "javascript": {"import_statement", "export_statement"},
    "typescript": {"import_statement", "export_statement"},
    "tsx": {"import_statement", "export_statement"},
}

# `import a.b.c` / `from a.b import x` — capture the module path (with dots).
_PY_FROM = re.compile(r"\bfrom\s+(\.*[\w.]*)\s+import\b")
_PY_IMPORT = re.compile(r"\bimport\s+([\w.]+)")
# The '...' or "..." source of a JS/TS import/re-export.
_JS_SOURCE = re.compile(r"""["']([^"']+)["']""")

_JS_EXTENSIONS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs")
_JS_INDEXES = ("/index.ts", "/index.tsx", "/index.js", "/index.jsx", "/index.mjs")


@dataclass(frozen=True)
class Edge:
    source: str  # POSIX path, relative to the repository root
    target: str
    kind: str = "import"


def build_dependency_graph(root: Path) -> list[Edge]:
    """First-party import edges between the repository's files, de-duplicated."""
    files = _repository_files(root)
    edges: set[Edge] = set()
    for rel_path in files:
        grammar = AST_GRAMMARS.get(Path(rel_path).suffix.lower())
        if grammar is None:
            continue
        text = (root / rel_path).read_text(encoding="utf-8", errors="replace")
        for spec in _import_specs(text, grammar):
            target = _resolve(spec, rel_path, files, grammar)
            if target is not None and target != rel_path:
                edges.add(Edge(source=rel_path, target=target))
    return sorted(edges, key=lambda e: (e.source, e.target))


def _repository_files(root: Path) -> set[str]:
    files: set[str] = set()
    for file in root.rglob("*"):
        if any(part in SKIP_DIRS for part in file.parts) or not file.is_file():
            continue
        files.add(file.relative_to(root).as_posix())
    return files


def _import_specs(text: str, grammar: str) -> list[str]:
    """The raw module/source strings of every import statement in the file."""
    tree = _parser(grammar).parse(text.encode("utf-8"))
    wanted = _IMPORT_TYPES.get(grammar, set())
    specs: list[str] = []
    stack = list(tree.root_node.named_children)
    while stack:
        node = stack.pop()
        if node.type in wanted:
            statement = node.text.decode("utf-8", errors="replace") if node.text else ""
            specs.extend(_specs_from_statement(statement, grammar))
        stack.extend(node.named_children)
    return specs


def _specs_from_statement(statement: str, grammar: str) -> list[str]:
    if grammar == "python":
        from_match = _PY_FROM.search(statement)
        if from_match:
            return [from_match.group(1)]
        return _PY_IMPORT.findall(statement)
    source = _JS_SOURCE.search(statement)
    return [source.group(1)] if source else []


def _resolve(spec: str, importer: str, files: set[str], grammar: str) -> str | None:
    if grammar == "python":
        return _resolve_python(spec, importer, files)
    if spec.startswith("."):
        return _resolve_relative(spec, importer, files)
    return None  # bare specifier → a third-party package, not in the repo


def _resolve_python(module: str, importer: str, files: set[str]) -> str | None:
    if module.startswith("."):
        dots = len(module) - len(module.lstrip("."))
        base = Path(importer).parent
        for _ in range(dots - 1):  # each extra dot climbs one package
            base = base.parent
        rest = module[dots:]
        target_base = base.joinpath(*rest.split(".")) if rest else base
    else:
        target_base = Path(*module.split("."))
    return _first_existing(
        [f"{target_base.as_posix()}.py", (target_base / "__init__.py").as_posix()], files
    )


def _resolve_relative(spec: str, importer: str, files: set[str]) -> str | None:
    joined = os.path.normpath(str(Path(importer).parent / spec)).replace("\\", "/")
    candidates = [f"{joined}{ext}" for ext in _JS_EXTENSIONS]
    candidates += [f"{joined}{index}" for index in _JS_INDEXES]
    return _first_existing(candidates, files)


def _first_existing(candidates: list[str], files: set[str]) -> str | None:
    for candidate in candidates:
        if candidate in files:
            return candidate
    return None
