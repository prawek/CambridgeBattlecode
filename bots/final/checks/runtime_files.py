"""The gameplay files shared by packaging and frozen-source benchmarks."""

from pathlib import Path


def runtime_files(source):
    source = Path(source)
    files = [source / 'main.py']
    package = source / 'finalbot'
    if package.is_dir():
        files.extend(package.rglob('*.py'))
        files.extend((source / 'florent').rglob('*.py'))
    else:
        # Older snapshots remain usable for before/after comparisons.
        files.extend(path for path in source.glob('*.py') if path.name != 'main.py')
    return sorted(path for path in files if '__pycache__' not in path.parts)
