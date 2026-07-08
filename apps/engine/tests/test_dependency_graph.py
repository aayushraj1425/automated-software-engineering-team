"""Import-edge extraction: first-party imports become edges, packages don't."""

from engine.indexing.dependency_graph import build_dependency_graph


def test_python_absolute_and_dotted_imports(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text("from pkg.b import thing\nimport pkg.c\n")
    (pkg / "b.py").write_text("thing = 1\n")
    (pkg / "c.py").write_text("value = 2\n")

    edges = {(edge.source, edge.target) for edge in build_dependency_graph(tmp_path)}

    assert ("pkg/a.py", "pkg/b.py") in edges
    assert ("pkg/a.py", "pkg/c.py") in edges


def test_python_relative_import(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "a.py").write_text("from .b import thing\n")
    (pkg / "b.py").write_text("thing = 1\n")

    edges = {(edge.source, edge.target) for edge in build_dependency_graph(tmp_path)}

    assert ("pkg/a.py", "pkg/b.py") in edges


def test_javascript_relative_import_skips_packages(tmp_path):
    (tmp_path / "a.js").write_text("import { x } from './b';\nimport React from 'react';\n")
    (tmp_path / "b.js").write_text("export const x = 1;\n")

    edges = {(edge.source, edge.target) for edge in build_dependency_graph(tmp_path)}

    assert ("a.js", "b.js") in edges
    assert all(target != "react" for _, target in edges)  # bare package is not first-party
