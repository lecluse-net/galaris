import ast
import json
from collections import defaultdict
from pathlib import Path

root = Path('/repo')
ignored = {'.git', '.venv', '.local', 'node_modules', '__pycache__', 'generated'}
extensions = {'.py', '.ts', '.vue', '.mjs', '.sh'}
totals = defaultdict(lambda: dict(files=0, lines=0, test_files=0, test_lines=0))
large_files = []
large_functions = []
for area in ('back', 'front', 'harness_manager', 'browser-executor', 'ssh-executor', 'bin', 'e2e'):
    for file in sorted((root / area).rglob('*')):
        if not file.is_file() or file.suffix not in extensions or ignored.intersection(file.parts):
            continue
        rel = file.relative_to(root)
        if '_audit_review_probes' in file.name:
            continue
        parts = rel.parts
        group = '/'.join(parts[:3]) if len(parts) >= 4 and area in {'back', 'front'} else area
        source = file.read_text(errors='replace')
        lines = len(source.splitlines())
        is_test = ('tests' in parts or 'e2e' in parts or '.test.' in file.name or file.name.startswith('test_'))
        totals[group]['test_files' if is_test else 'files'] += 1
        totals[group]['test_lines' if is_test else 'lines'] += lines
        if is_test:
            continue
        large_files.append((lines, str(rel)))
        if file.suffix == '.py':
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    large_functions.append((node.end_lineno-node.lineno+1, str(rel), node.lineno, node.name))
print(json.dumps({'groups':dict(sorted(totals.items())), 'largest_files':sorted(large_files, reverse=True)[:25],
    'largest_functions':sorted(large_functions, reverse=True)[:25]}, indent=2))
