"""Resumable transport routes for the two separate refinery inputs."""

from heapq import heappop, heappush
from itertools import count
from collections import deque

from cambc import EntityType, GameConstants
from finalbot.shared.constants import DIRECTIONS, ORTHOGONAL_DIRECTIONS


BRIDGE_OFFSETS = tuple((dx, dy) for dx in range(-3, 4) for dy in range(-3, 4)
                       if 1 < dx * dx + dy * dy <= 9)


def road_clearance_cost(cache, pos, team):
    """Budget the two attacks needed to reclaim an ordinary hostile road."""
    building = cache.building_at(pos)
    if team is None or building is None or building[0] != EntityType.ROAD or building[1] == team:
        return 0
    attacks = ((GameConstants.ROAD_MAX_HP + GameConstants.BUILDER_BOT_ATTACK_DAMAGE - 1)
               // GameConstants.BUILDER_BOT_ATTACK_DAMAGE)
    return attacks * GameConstants.BUILDER_BOT_ATTACK_COST[0]


def construction_tiles(bot, current):
    """Known terrain on which this worker can actually install a recipe."""
    reached, queue = {current}, deque([current])
    expanded = 0
    while queue:
        tile = queue.popleft()
        expanded += 1
        if expanded % 16 == 0:
            yield
        for direction in DIRECTIONS:
            neighbor = bot.tile_cache.neighbor(tile, direction)
            if neighbor is not None and neighbor not in reached and bot.traversable_for_ore_path(None, neighbor):
                reached.add(neighbor)
                queue.append(neighbor)
    return reached


def input_route(cache, ore, foundry, available, forbidden, team=None):
    """Return downstream-first build steps without using another input lane."""
    if ore.distance_squared(foundry) == 1:
        return []
    serial = count()
    queue, costs, parent = [], {}, {}

    def heuristic(pos):
        return max(0, abs(pos.x - foundry.x) + abs(pos.y - foundry.y) - 1) * 3

    def usable(pos):
        return pos is not None and pos not in forbidden and pos != ore and available(pos)

    for direction in ORTHOGONAL_DIRECTIONS:
        tile = cache.neighbor(ore, direction)
        if usable(tile):
            cost = road_clearance_cost(cache, tile, team)
            costs[tile] = cost
            parent[tile] = None
            heappush(queue, (cost + heuristic(tile), cost, next(serial), tile))
    expanded = 0
    while queue and expanded < 512:
        _, cost, _, tile = heappop(queue)
        if costs.get(tile) != cost:
            continue
        expanded += 1
        if expanded % 8 == 0:
            yield
        distance = tile.distance_squared(foundry)
        if distance <= 9:
            kind = EntityType.CONVEYOR if distance == 1 else EntityType.BRIDGE
            extra = tile.direction_to(foundry) if distance == 1 else foundry
            steps = [(tile, kind, extra)]
            downstream = tile
            while parent[downstream] is not None:
                upstream, kind = parent[downstream]
                extra = upstream.direction_to(downstream) if kind == EntityType.CONVEYOR else downstream
                steps.append((upstream, kind, extra))
                downstream = upstream
            return steps
        edges = [(cache.neighbor(tile, direction), EntityType.CONVEYOR, 3)
                 for direction in ORTHOGONAL_DIRECTIONS]
        edges.extend((cache.offset(tile, dx, dy), EntityType.BRIDGE, 20)
                     for dx, dy in BRIDGE_OFFSETS)
        for target, kind, price in edges:
            if not usable(target):
                continue
            candidate = cost + price + road_clearance_cost(cache, target, team)
            if candidate >= costs.get(target, float('inf')):
                continue
            costs[target] = candidate
            parent[target] = tile, kind
            heappush(queue, (candidate + heuristic(target), candidate, next(serial), target))
    return None
