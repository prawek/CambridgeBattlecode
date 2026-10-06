"""Include engine stderr tracebacks, which need not be saved in a replay."""

from pathlib import Path
import re


def tracebacks(text):
    starts = list(re.finditer(r'^Traceback \(most recent call last\):\s*$', text, re.MULTILINE))
    for index, match in enumerate(starts):
        limit = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        lines = text[match.start():limit].splitlines()
        block = [lines[0]]
        for line in lines[1:]:
            block.append(line)
            if line and not line[0].isspace():
                break
        yield '\n'.join(block)


def merge_log_errors(runtime, log_path, sources):
    """Merge exception records using source directories in engine team order."""
    directories = [str(Path(source).resolve()).replace('\\', '/').lower().rstrip('/') + '/'
                   for source in sources]
    records = [dict(errors=0, error_samples=[]) for _ in sources]
    unknown = dict(errors=0, error_samples=[])
    for block in tracebacks(Path(log_path).read_text(encoding='utf8', errors='replace')):
        normalized = block.replace('\\', '/').lower()
        owner = next((index for index, directory in enumerate(directories)
                      if directory in normalized), None)
        stats = records[owner] if owner is not None else unknown
        stats['errors'] += 1
        if len(stats['error_samples']) < 3:
            stats['error_samples'].append(block[-2000:])
    for team, extra in zip(runtime, records):
        replay_errors = team.get('replay_errors', team['errors'])
        team['replay_errors'] = replay_errors
        team['stderr_errors'] = extra['errors']
        team['errors'] = replay_errors + extra['errors']
        team['error_samples'] = (team.get('error_samples', []) + extra['error_samples'])[:3]
    return unknown
