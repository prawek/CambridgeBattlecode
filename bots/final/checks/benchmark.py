"""Frozen-source local matches; replays stay outside the submission.

Example (from the project root):
    .venv/Scripts/python.exe bots/final/checks/benchmark.py \
        --opponents qualifier sota --maps arena default_small1 --jobs 2

The Windows engine does not emit CPU measurements. A zero timeout count alone
does not establish that a bot fits the competition's CPU limit.
Game and Python hash seeds are recorded; opponents may use unseeded randomness.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from runtime_files import runtime_files
from runtime_health import merge_log_errors

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAPS = ('arena', 'default_small1', 'default_medium1', 'minimaze', 'bear_of_doom')


def fields(data):
    """Read the small protobuf subset used by engine replay events."""
    offset = 0

    def integer():
        nonlocal offset
        result = 0
        for shift in range(0, 70, 7):
            byte = data[offset]
            offset += 1
            result |= (byte & 127) << shift
            if byte < 128:
                return result
        raise ValueError('invalid replay integer')

    while offset < len(data):
        tag = integer()
        wire = tag & 7
        if wire == 0:
            value = integer()
        elif wire in (1, 2, 5):
            length = integer() if wire == 2 else 8 if wire == 1 else 4
            value = data[offset:offset + length]
            if len(value) != length:
                raise ValueError('truncated replay')
            offset += length
        else:
            raise ValueError(f'unsupported replay field {wire}')
        yield tag >> 3, value


def replay_health(path):
    teams = [dict(errors=0, error_samples=[], timeouts=0, cpu_recorded=False,
                  max_cpu_us=None) for _ in range(2)]
    owners = {}
    for number, payload in fields(path.read_bytes()):
        if number == 1:
            for map_number, value in fields(payload):
                if map_number == 4:
                    core = dict(fields(value))
                    owners[core.get(1, 0)] = core.get(2, 0)
        elif number == 3:
            for turn_number, update in fields(payload):
                if turn_number != 1:
                    continue
                for event, value in fields(update):
                    if event == 1:
                        entity = dict(fields(dict(fields(value))[1]))
                        owners[entity.get(1, 0)] = entity.get(2, 0)
                    elif event == 9:
                        output = dict(fields(value))
                        owner = owners.get(output.get(1, 0))
                        if owner not in (0, 1):
                            continue
                        team = teams[owner]
                        if 3 in output:
                            team['cpu_recorded'] = True
                            team['max_cpu_us'] = max(team['max_cpu_us'] or 0, output[3])
                        team['timeouts'] += bool(output.get(4))
                        text = output.get(2, b'').decode('utf8', errors='replace')
                        if any(token in text for token in (
                            'Traceback (most recent call last)', 'Error:', 'Exception:',
                        )):
                            team['errors'] += 1
                            if len(team['error_samples']) < 3:
                                team['error_samples'].append(text[-1600:])
    return teams


def snapshot(source, output, label, *, candidate=False):
    source = source.resolve()
    if not (source / 'main.py').is_file():
        raise ValueError(f'bot entry point missing: {source / "main.py"}')
    target = output / ('snapshot_' + label)
    target.mkdir()
    hashes = {}
    # Include the complete runtime package, leaving local tooling behind.
    paths = runtime_files(source) if candidate else source.rglob('*.py')
    for path in sorted(paths):
        if '__pycache__' in path.parts:
            continue
        relative = path.relative_to(source)
        copied = target / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, copied)
        hashes[relative.as_posix()] = hashlib.sha256(copied.read_bytes()).hexdigest()
    return dict(source=str(source), snapshot=str(target), sha256=hashes)


def worker(args):
    import cambc
    from cambc.cambc_engine import run_game

    paths = [str(Path(args.candidate) / 'main.py'),
             str(Path(args.opponents[0]) / 'main.py')]
    if args.sides[0]:
        paths.reverse()
    output = Path(args.output)
    started = time.monotonic()
    result = run_game(*paths, str(Path(cambc.__file__).resolve().parent.parent),
                      str(ROOT / 'maps' / (args.maps[0] + '.map26')),
                      str(output.with_suffix('.replay26')), args.seeds[0], args.tle)
    result.update(map=args.maps[0], seed=args.seeds[0], side=args.sides[0],
                  won=result['winner'] == ('B' if args.sides[0] else 'A'),
                  tle_ms=args.tle, python_hash_seed=args.hash_seed,
                  seconds=round(time.monotonic() - started, 2),
                  runtime=replay_health(output.with_suffix('.replay26')))
    output.with_suffix('.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    sys.stdout.flush()
    sys.stderr.flush()
    # The engine uses subinterpreters which Python 3.12 cannot cleanly finalize.
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', default='bots/final')
    parser.add_argument('--opponents', nargs='+', default=['qualifier', 'sota'])
    parser.add_argument('--maps', nargs='+', default=DEFAULT_MAPS)
    parser.add_argument('--seeds', nargs='+', type=int, default=[1])
    parser.add_argument('--sides', nargs='+', type=int, choices=(0, 1), default=[0, 1])
    parser.add_argument('--tle', type=int, default=2)
    parser.add_argument('--hash-seed', type=int, default=0,
                        help='Fix Python enum/set iteration for comparable runs (default: 0)')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--output', help='New output directory (default: a temporary directory)')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    if not 0 <= args.hash_seed <= 4294967295:
        parser.error('--hash-seed must be between 0 and 4294967295')
    output = Path(args.output).resolve() if args.output else Path(tempfile.mkdtemp(prefix='final_matches_'))
    output.mkdir(parents=True, exist_ok=True)
    manifest = dict(tle_ms=args.tle, python_hash_seed=args.hash_seed,
                    candidate=snapshot(ROOT / args.candidate, output, 'final', candidate=True),
                    opponents={})
    for opponent in args.opponents:
        source = Path(opponent)
        if not (source / 'main.py').is_file():
            source = ROOT / 'bots' / opponent
        label = source.name
        if label in manifest['opponents']:
            parser.error(f'duplicate opponent name: {label}')
        manifest['opponents'][label] = snapshot(source, output, label)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    print(f'Artifacts: {output}', flush=True)
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED=str(args.hash_seed))

    def match(opponent, map_name, seed, side):
        name = f'{opponent}_{map_name}_s{seed}_{side}'
        target = output / name
        command = [sys.executable, str(Path(__file__).resolve()), '--worker',
                   '--candidate', manifest['candidate']['snapshot'],
                   '--opponents', manifest['opponents'][opponent]['snapshot'],
                   '--maps', map_name, '--seeds', str(seed), '--sides', str(side),
                   '--tle', str(args.tle), '--hash-seed', str(args.hash_seed),
                   '--output', str(target)]
        with target.with_suffix('.log').open('w', encoding='utf8') as log:
            subprocess.run(command, cwd=ROOT, env=environment, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        result = json.loads(target.with_suffix('.json').read_text(encoding='utf8'))
        result['opponent'] = opponent
        sources = [manifest['candidate']['snapshot'], manifest['opponents'][opponent]['snapshot']]
        if side:
            sources.reverse()
        result['unattributed_runtime_errors'] = merge_log_errors(
            result['runtime'], target.with_suffix('.log'), sources,
        )
        target.with_suffix('.json').write_text(json.dumps(result, indent=2), encoding='utf8')
        return name, result

    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        tasks = [pool.submit(match, opponent, map_name, seed, side)
                 for opponent in manifest['opponents'] for map_name in args.maps
                 for seed in args.seeds for side in args.sides]
        for future in as_completed(tasks):
            name, result = future.result()
            results.append(result)
            results.sort(key=lambda r: (r['opponent'], r['map'], r['seed'], r['side']))
            (output / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf8')
            state = 'WIN' if result['won'] else 'LOSS'
            errors = result['runtime'][result['side']]['errors']
            print(f'{name}: {state} {result["win_condition"]} r{result["turns"]} '
                  f'({result["seconds"]}s, bot errors={errors})', flush=True)
    print(f'Wins: {sum(r["won"] for r in results)}/{len(results)}', flush=True)


if __name__ == '__main__':
    main()
