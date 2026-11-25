"""Load frozen, synthetic-benchmark-only algorithm sources for paired measurements."""

import hashlib
import importlib.util
import inspect
from pathlib import Path
import sys


def load_reference(root, clock):
    root.resolve().relative_to(Path('/repo/artifacts/memory-benchmark').resolve())
    modules = {}
    names = ('relevance', 'service', 'retrieval', 'facade')
    if (root / 'question_evidence.py').is_file():
        names = (*names, 'question_evidence')
    if (root / 'identity_attributes.py').is_file():
        names = (*names, 'identity_attributes')
    if (root / 'source_language.py').is_file():
        names = (*names, 'source_language')
    if (root / 'storage_evidence.py').is_file():
        names = (*names, 'storage_evidence')
    if (root / 'context.py').is_file():
        names = (*names, 'context')
    if (root / 'admission.py').is_file():
        names = ('admission', *names)
    if (root / 'access.py').is_file():
        names = ('access', *names)
    if (root / 'catalogue.py').is_file():
        names = ('catalogue', *names)
    for name in names:
        path = root / f'{name}.py'
        package = 'app.file_share' if name == 'catalogue' else 'app.memory'
        qualified = f'{package}._benchmark_previous_{name}'
        spec = importlib.util.spec_from_file_location(qualified, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load benchmark reference {name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified] = module
        spec.loader.exec_module(module)
        modules[name] = module
    modules['service'].relevance = modules['relevance']
    modules['retrieval'].relevance = modules['relevance']
    modules['retrieval'].service = modules['service']
    modules['facade'].recall_items = modules['retrieval'].recall_items
    if 'question_evidence' in modules:
        if 'storage_evidence' in modules:
            for name in ('source_language', 'question_evidence'):
                modules[name].storage_lookup = modules['storage_evidence'].storage_lookup
        if 'source_language' in modules:
            modules['question_evidence'].source_language_query = modules['source_language'].source_language_query
        if 'identity_attributes' in modules:
            modules['question_evidence'].identity_attribute = modules['identity_attributes'].identity_attribute
        for name in ('retrieval', 'context'):
            if name in modules:
                modules[name].parse_question_evidence = modules['question_evidence'].parse_question_evidence
    if 'context' in modules:
        builder = modules['context'].build_memory_brief
        if 'conversational' not in inspect.signature(builder).parameters:
            async def legacy_brief(*args, **kwargs):
                kwargs.pop('conversational', None)
                return await builder(*args, **kwargs)
            modules['context'].build_memory_brief = legacy_brief
    if 'admission' in modules:
        for name in ('service', 'retrieval'):
            modules[name].admit_search_hits = modules['admission'].admit_search_hits
    for name in ('service', 'retrieval', 'admission'):
        if name not in modules:
            continue
        modules[name].datetime = clock
    return modules


def reference_fingerprints(root):
    names = ('relevance', 'service', 'retrieval', 'facade')
    if (root / 'question_evidence.py').is_file():
        names = (*names, 'question_evidence')
    if (root / 'identity_attributes.py').is_file():
        names = (*names, 'identity_attributes')
    if (root / 'source_language.py').is_file():
        names = (*names, 'source_language')
    if (root / 'storage_evidence.py').is_file():
        names = (*names, 'storage_evidence')
    if (root / 'context.py').is_file():
        names = (*names, 'context')
    if (root / 'admission.py').is_file():
        names = ('admission', *names)
    if (root / 'access.py').is_file():
        names = ('access', *names)
    if (root / 'catalogue.py').is_file():
        names = ('catalogue', *names)
    return {f'reference/{name}.py': hashlib.sha256((root / f'{name}.py').read_bytes()).hexdigest()
            for name in names}
