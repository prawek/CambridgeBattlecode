"""Incremental selection of mine-fed siege and counter-battery positions.

Geometry generation and engine validation have separate bounded slices. The
builder can finish a dense local search across turns without losing its job.
"""
from collections import deque

from cambc import Direction, EntityType, Environment
from finalbot.shared.constants import DIRECTIONS, ORTHOGONAL_DIRECTIONS

TURRETS = (EntityType.GUNNER, EntityType.SENTINEL)


def firing_facings(site, target, kind, source):
    """Keep a mine's input port open even when shooting across the source."""
    direct = site.direction_to(target)
    if direct == Direction.CENTRE:
        return ()
    directions = (direct, direct.rotate_left(), direct.rotate_right()) if kind == EntityType.SENTINEL else (direct,)
    return tuple(direction for direction in directions if site.add(direction) != source)


def buildable(bot, site):
    if site is None or bot.tile_cache.environment_at(site) in (None, Environment.WALL):
        return False
    building = bot.tile_cache.building_at(site)
    return building is None or building == (EntityType.ROAD, bot.team) or (
        building[1] != bot.team and building[0] == EntityType.ROAD)


def candidate_search(bot, current, now):
    cache = bot.tile_cache
    target = bot.destination
    core_tiles = [cache.offset(target, dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
    core_tiles = [p for p in core_tiles if p is not None]
    core_tiles.sort(key=lambda p: current.distance_squared(p))
    gun_positions = {}
    if bot.destination_is_confirmed_core:
        for goal in core_tiles[:4]:
            for facing in DIRECTIONS:
                dx, dy = facing.delta()
                for distance in range(1, 4 if facing in ORTHOGONAL_DIRECTIONS else 3):
                    site = cache.offset(goal, -dx*distance, -dy*distance)
                    if buildable(bot, site) and bot.siege_rejected.get(site, 0) <= now:
                        gun_positions[site, facing] = goal
    candidates = []
    threats = [cache.entity_position(entity_id) for entity_id in cache.visible_entity_ids
               if cache.entity_team(entity_id) != bot.team
               and cache.entity_type(entity_id) in TURRETS + (EntityType.BREACH, EntityType.LAUNCHER)]
    for ore in sorted(cache.visible_tiles, key=lambda p: (p.x, p.y)):
        if cache.environment_at(ore) != Environment.ORE_TITANIUM:
            continue
        if getattr(bot, 'deferred_siege_ores', {}).get(ore, 0) > now:
            continue
        mine = cache.building_at(ore)
        if mine is not None and (mine[0] != EntityType.HARVESTER or
                                (mine[1] == bot.team and ore not in bot.owned_supply_ores)):
            continue
        hostile_mine = mine is not None and mine[1] != bot.team
        if not hostile_mine and (not bot.destination_is_confirmed_core or ore.distance_squared(target) > 85):
            continue
        for direction in ORTHOGONAL_DIRECTIONS:
            yield
            feed = cache.neighbor(ore, direction)
            if feed is None or cache.environment_at(feed) in (None, Environment.WALL) or cache.building_at(feed) not in (None, (EntityType.ROAD, bot.team)):
                continue
            for (site, facing), goal in gun_positions.items():
                if site == feed or feed.distance_squared(site) > 9:
                    continue
                dx, dy = abs(feed.x-site.x), abs(feed.y-site.y)
                if site.direction_to(feed) == facing and (dx == 0 or dy == 0 or dx == dy):
                    continue
                penalty = 0 if cache.building_at(site) in (None, (EntityType.ROAD, bot.team)) else 60
                score = current.distance_squared(site) + current.distance_squared(feed)//2 + 8 + penalty + (12 if mine is None else 0)
                candidates.append((score, site, ore, EntityType.GUNNER, facing, goal, feed))
        for direction in ORTHOGONAL_DIRECTIONS:
            yield
            site = cache.neighbor(ore, direction)
            if not buildable(bot, site) or bot.siege_rejected.get(site, 0) > now:
                continue
            obstruction = cache.building_at(site)
            penalty = (8 if obstruction[0] == EntityType.ROAD else 60) if obstruction is not None and obstruction[1] != bot.team else 0
            # A battery losing its source to counter-fire needs another gun,
            # rather than a builder healing four HP against ten-damage shots.
            # Sentinels can return fire across the mine that blocks a gunner.
            for goal in threats:
                for kind, radius in ((EntityType.GUNNER, 13), (EntityType.SENTINEL, 32)):
                    if site.distance_squared(goal) > radius:
                        continue
                    dx, dy = abs(goal.x-site.x), abs(goal.y-site.y)
                    if kind == EntityType.GUNNER and dx and dy and dx != dy:
                        continue
                    score = (current.distance_squared(site) + penalty - 35
                             + (12 if mine is None else 0)
                             + (12 if kind == EntityType.SENTINEL else 0))
                    for facing in firing_facings(site, goal, kind, ore):
                        candidates.append((score, site, ore, kind, facing, goal, site))
            # Capture a hostile source even when it cannot yet reach the core.
            # The gunner loads facing away, then chooses its own nearby target.
            if mine is not None and mine[1] != bot.team:
                candidates.append((35 + current.distance_squared(site) + penalty,
                                   site, ore, EntityType.GUNNER, direction, None, site))
            if not bot.destination_is_confirmed_core:
                continue
            for kind, radius in ((EntityType.GUNNER, 13), (EntityType.SENTINEL, 32)):
                for goal in core_tiles:
                    if site.distance_squared(goal) > radius:
                        continue
                    dx, dy = abs(goal.x-site.x), abs(goal.y-site.y)
                    if kind == EntityType.GUNNER and dx and dy and dx != dy:
                        continue
                    score = current.distance_squared(site) + penalty + (12 if mine is None else 0) + (28 if kind == EntityType.SENTINEL else 0)
                    for facing in firing_facings(site, goal, kind, ore):
                        candidates.append((score, site, ore, kind, facing, goal, site))
    candidates.sort(key=lambda value: value[0])
    # Core footprint cells and sentinel facings can describe the same
    # physical battery many times. Keep a varied shortlist so a blocked ray
    # cannot crowd every other source out of the validation queue.
    groups = {}
    seen = set()
    for candidate in candidates:
        _, site, ore, kind, facing, goal, feed = candidate
        key = site, ore, kind, facing, feed
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault((ore, kind), deque()).append(candidate)
    # A dense ore cluster can fill every cheap slot with blocked gunner rays.
    # Keep sources and weapon types represented before validating geometry.
    pending = deque(groups.values())
    shortlist = []
    while pending and len(shortlist) < 32:
        group = pending.popleft()
        shortlist.append(group.popleft())
        if group:
            pending.append(group)
    return shortlist


def budget_available(controller):
    elapsed = controller.get_cpu_time_elapsed()
    return not isinstance(elapsed, (int, float)) or elapsed < 1250


def next_plan(bot, controller, current, now):
    """Return (pending, plan), preserving the search between turn slices."""
    key = current, bot.destination, bot.destination_is_confirmed_core
    if getattr(bot, '_siege_search_key', None) != key:
        bot._siege_search_key = key
        bot._siege_search = candidate_search(bot, current, now)
        bot._siege_candidates = None
        bot._siege_validation_index = 0
        bot._siege_retry_round = 0
    if now < bot._siege_retry_round:
        return False, None
    if bot._siege_search is not None:
        for _ in range(32):
            if not budget_available(controller):
                return True, None
            try:
                next(bot._siege_search)
            except StopIteration as complete:
                bot._siege_search = None
                bot._siege_candidates = complete.value
                break
        if bot._siege_search is not None:
            return True, None
    candidates = bot._siege_candidates
    for _ in range(5):
        if bot._siege_validation_index >= len(candidates):
            bot._siege_search_key = None
            return False, None
        if not budget_available(controller):
            return True, None
        _, site, ore, kind, facing, goal, feed = candidates[bot._siege_validation_index]
        bot._siege_validation_index += 1
        if bot.siege_rejected.get(site, 0) > now or not buildable(bot, site):
            continue
        if goal is None or controller.can_fire_from(site, facing, kind, goal):
            bot._siege_search_key = None
            return False, (site, ore, kind, facing, feed)
    return True, None
