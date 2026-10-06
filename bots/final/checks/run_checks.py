"""Run the inherited contracts and final's own checks in separate processes."""

import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    for arguments in (
        [str(Path(__file__).with_name('legacy_tests.py')),
         'tests.nexus.test_cache_and_planning', 'tests.nexus.test_planning_slices', '-v'],
        [str(Path(__file__).with_name('legacy_tests.py')), 'tests.final.test_integration', '-v'],
        ['-m', 'unittest', 'discover', '-s', 'bots/final/checks', '-v'],
    ):
        subprocess.run([sys.executable, *arguments], cwd=root,
                       env=environment, check=True)


if __name__ == '__main__':
    main()
