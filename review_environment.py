"""Inspect the current interpreter and exact dependency pins without importing ML libraries."""
from pathlib import Path
import importlib.metadata, platform, re, sys

ROOT = Path(__file__).resolve().parent


def pins(path, root=ROOT, seen=None):
    root, path = Path(root).resolve(), Path(path).resolve()
    seen = set() if seen is None else seen
    if not path.is_relative_to(root) or path in seen:
        raise ValueError('Invalid or cyclic requirement include')
    seen.add(path); result = {}
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('-r '):
            values = pins(path.parent / line[3:].strip(), root, seen)
        else:
            match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)', line)
            if not match:
                raise ValueError('Unpinned or unsupported requirement: ' + line)
            values = {re.sub(r'[-_.]+', '-', match[1]).lower(): match[2]}
        for name, version in values.items():
            if name in result and result[name] != version:
                raise ValueError('Conflicting pin: ' + name)
            result[name] = version
    return result


def inspect(root=ROOT, documents=False):
    root = Path(root).resolve()
    expected = pins(root / ('requirements-review-lock.txt' if documents else 'requirements-lock.txt'), root)
    packages, missing, mismatches = {}, [], []
    for name, wanted in expected.items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        packages[name] = {'expected': wanted, 'installed': actual}
        if actual is None:
            missing.append(name)
        elif actual != wanted:
            mismatches.append(name)
    python_supported = sys.version_info[:2] == (3, 12) and platform.python_implementation() == 'CPython'
    verified_platform = platform.system() == 'Windows' and platform.machine().lower() in ('amd64', 'x86_64') and python_supported and platform.python_version() == '3.12.14'
    return {'status': 'passed' if python_supported and not missing and not mismatches else 'blocked',
            'python': platform.python_version(), 'implementation': platform.python_implementation(),
            'system': platform.system(), 'machine': platform.machine(), 'virtual_environment': sys.prefix != sys.base_prefix,
            'python_version_supported': python_supported, 'matches_clean_install_test_platform': verified_platform,
            'requirements_checked': len(expected), 'document_dependencies_included': documents,
            'missing': missing, 'mismatches': mismatches, 'packages': packages,
            'installation_provenance_checked_by_this_command': False,
            'bundled_python_or_wheels': False}


def require(root=ROOT, documents=False):
    result = inspect(root, documents)
    if result['status'] != 'passed':
        raise ValueError('Environment mismatch: use CPython 3.12 and the documented pinned environment; missing=' +
                         ','.join(result['missing']) + '; mismatched=' + ','.join(result['mismatches']))
    return result
