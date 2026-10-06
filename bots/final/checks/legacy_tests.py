"""Run unchanged repository contracts against final's package layout.

The historical tests open flat module paths and import short module names.
Redirect those references only in this test process; gameplay has no aliases
or import hooks and uses qualified finalbot imports throughout.
"""

import importlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

BOT = Path(__file__).resolve().parents[1]
REPOSITORY = BOT.parents[1]
LAYOUT = json.loads((Path(__file__).with_name('legacy_layout.json')).read_text(encoding='utf8'))
ORIGINAL_SPEC = importlib.util.spec_from_file_location


def source_spec(name, location=None, *args, **kwargs):
    if location is not None:
        path = Path(location).resolve()
        if path.parent == BOT and path.stem in LAYOUT and path.suffix == '.py':
            location = BOT / LAYOUT[path.stem]
    return ORIGINAL_SPEC(name, location, *args, **kwargs)


class LegacyModules(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        relative = LAYOUT.get(fullname)
        if relative is not None:
            return ORIGINAL_SPEC(fullname, BOT / relative)
        return None


def main():
    os.environ['CAMBC_TEST_BOT'] = 'final'
    sys.path[:0] = [str(BOT), str(REPOSITORY)]
    sys.meta_path.insert(0, LegacyModules())
    importlib.util.spec_from_file_location = source_spec
    # The planning contracts inspect this old name after loading BuilderBot.
    importlib.import_module('base')
    unittest.main(module=None, argv=[sys.argv[0], *sys.argv[1:]])


if __name__ == '__main__':
    main()
