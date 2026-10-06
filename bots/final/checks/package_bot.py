"""Package only runtime modules, excluding local tools and fixtures."""

import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

from runtime_files import runtime_files


def package(destination):
    source = Path(__file__).resolve().parents[1]
    modules = runtime_files(source)
    local_modules = {'.'.join(path.relative_to(source).with_suffix('').parts)
                     .removesuffix('.__init__') for path in modules}
    external = sys.stdlib_module_names | {'cambc'}
    for path in modules:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf8'))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                if name not in local_modules and name.split('.')[0] not in external:
                    raise ValueError(f'{path.name}: external runtime import {name}')
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in modules:
            archive.write(path, path.relative_to(source).as_posix())
    hashes = {path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in modules}
    destination.with_suffix('.json').write_text(json.dumps(hashes, indent=2), encoding='utf8')
    return len(modules)


if __name__ == '__main__':
    target = Path(tempfile.mkdtemp(prefix='final_release_')) / 'final.zip'
    count = package(target)
    print(f'{target} ({count} runtime modules)')
