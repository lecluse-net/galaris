"""Keep literal resource creation calls aligned with the Memory/Document boundary."""

import ast
import os
from pathlib import Path


def test_memory_creation_consumers_do_not_request_retired_document_kinds():
    root = Path(__file__).resolve().parents[1]
    failures = []
    for directory, directories, files in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if not name.startswith('.')
            and name not in {'node_modules', '__pycache__', 'dist', 'artifacts'}]
        for filename in files:
            path = Path(directory) / filename
            if path.suffix != '.py' or path.is_symlink():
                continue
            source = path.read_text()
            if 'MemoryItemCreate' not in source:
                continue
            tree = ast.parse(source)
            aliases = {alias.asname or alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module in {'app.memory', 'app.memory.schemas'}
                for alias in node.names if alias.name == 'MemoryItemCreate'}
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id not in aliases:
                    continue
                retired = any(keyword.arg == 'node_kind' and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value != 'memory' for keyword in node.keywords)
                if not retired:
                    continue
                parent, rejection = node, False
                while parent in parents:
                    parent = parents[parent]
                    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        break
                    if isinstance(parent, (ast.With, ast.AsyncWith)):
                        rejection |= any(isinstance(item.context_expr, ast.Call)
                            and isinstance(item.context_expr.func, ast.Attribute)
                            and item.context_expr.func.attr == 'raises' for item in parent.items)
                if not rejection:
                    failures.append(f'{path.relative_to(root)}:{node.lineno}')
    assert not failures, f'Use Document creation contracts for documents; keep intentional rejection tests explicit: {failures}'
