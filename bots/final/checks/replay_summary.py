"""Summarize economy and casualties, distinguishing rotations from new units.

Run from the project root:
    .venv/Scripts/python.exe bots/final/checks/replay_summary.py replay.replay26
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from benchmark import fields

KINDS = dict(enumerate((
    'builder', 'conveyor', 'splitter', 'armoured_conveyor', 'bridge',
    'harvester', 'foundry', 'road', 'barrier', 'marker', 'core', 'gunner',
    'sentinel', 'breach', 'launcher',
), 10))


def position(payload):
    values = dict(fields(payload))
    return values.get(1, 0), values.get(2, 0)


def entity(payload):
    values = dict(fields(payload))
    kind = next((KINDS[key] for key in KINDS if key in values), 'unknown')
    return dict(id=values.get(1, 0), team=values.get(2, 0),
                position=position(values.get(3, b'')), kind=kind)


def summarize(path):
    teams = [dict(placed=Counter(), destroyed=Counter(), rotations=0,
                  first_titanium_delivery=None, timeline=[], core_hp=500,
                  builders={}) for _ in range(2)]
    entities = {}
    seen = set()
    core_ids = {}
    players = [dict(titanium=500, axionite=0, titanium_collected=0,
                    axionite_collected=0) for _ in range(2)]
    turn = 0
    for number, payload in fields(path.read_bytes()):
        if number == 1:
            for map_number, value in fields(payload):
                if map_number == 4:
                    core = dict(fields(value))
                    entity_id, owner = core.get(1, 0), core.get(2, 0)
                    entities[entity_id] = dict(id=entity_id, team=owner,
                                               kind='core', position=position(core[3]))
                    seen.add(entity_id)
                    core_ids[entity_id] = owner
                    teams[owner]['core_position'] = position(core[3])
        elif number == 3:
            turn += 1
            for turn_number, update in fields(payload):
                if turn_number != 1:
                    continue
                for event, value in fields(update):
                    if event == 1:
                        placed = entity(dict(fields(value))[1])
                        entity_id, owner = placed['id'], placed['team']
                        if entity_id not in seen:
                            seen.add(entity_id)
                            teams[owner]['placed'][placed['kind']] += 1
                            if placed['kind'] == 'builder':
                                teams[owner]['builders'][entity_id] = dict(
                                    born=turn, moves=0, position=placed['position'])
                        elif placed['kind'] == 'gunner':
                            teams[owner]['rotations'] += 1
                        entities[entity_id] = placed
                    elif event == 2:
                        moved = dict(fields(value))
                        item = entities.get(moved.get(1, 0))
                        if item is not None:
                            item['position'] = position(moved[2])
                            builder = teams[item['team']]['builders'].get(item['id'])
                            if builder is not None:
                                builder['moves'] += 1
                                builder['position'] = item['position']
                    elif event == 3:
                        removed_id = dict(fields(value)).get(1, 0)
                        item = entities.pop(removed_id, None)
                        if item is not None:
                            teams[item['team']]['destroyed'][item['kind']] += 1
                    elif event == 5:
                        changed = dict(fields(value))
                        entity_id = changed.get(1, 0)
                        if entity_id in core_ids:
                            delta = changed.get(2, 0)
                            if delta >= 1 << 63:
                                delta -= 1 << 64
                            teams[core_ids[entity_id]]['core_hp'] += delta
                    elif event == 6:
                        state = dict(fields(dict(fields(value))[1]))
                        for owner, key in enumerate((1, 2)):
                            if key not in state:
                                continue
                            player = dict(fields(state[key]))
                            players[owner] = dict(titanium=player.get(1, 0),
                                                 axionite=player.get(2, 0),
                                                 titanium_collected=player.get(4, 0),
                                                 axionite_collected=player.get(5, 0))
                            if player.get(4, 0) and teams[owner]['first_titanium_delivery'] is None:
                                teams[owner]['first_titanium_delivery'] = turn
            if turn % 100 == 0:
                for owner in (0, 1):
                    teams[owner]['timeline'].append(dict(round=turn,
                        core_hp=teams[owner]['core_hp'], **players[owner]))
    for owner in (0, 1):
        teams[owner].update(players[owner])
        teams[owner]['alive'] = Counter(item['kind'] for item in entities.values()
                                       if item['team'] == owner)
    return dict(file=str(path), rounds=turn, teams=teams)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('replays', nargs='+', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    for path in args.replays:
        result = summarize(path)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(path.name, result['rounds'])
            for owner, team in enumerate(result['teams']):
                print(f"  {'AB'[owner]}: Ti={team['titanium_collected']} "
                      f"Ax={team['axionite_collected']} HP={team['core_hp']} "
                      f"first Ti={team['first_titanium_delivery']}")
                print('    built:', dict(team['placed']))
                print('    lost:', dict(team['destroyed']))
                print('    gunner rotations:', team['rotations'])


if __name__ == '__main__':
    main()
