"""Turn a hostile transport outlet into a supplied forward battery."""

from cambc import EntityType, Environment, ResourceType

from finalbot.shared.constants import DIRECTIONS
from finalbot.combat.siege_planner import firing_facings

TRANSPORT = (EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER)
REPLACEABLE = TRANSPORT + (EntityType.ROAD,)


def remember_flow(bot, controller, now):
    cache = bot.tile_cache
    flow = bot.hijack_flow
    for pos, (entity_id, seen) in tuple(flow.items()):
        if now - seen > 32 or (pos in cache.visible_tiles and cache.building_id_at(pos) != entity_id):
            del flow[pos]
    sources = [entity_id for entity_id in cache.visible_entity_ids
               if cache.entity_team(entity_id) != bot.team
               and cache.entity_type(entity_id) in TRANSPORT]
    sources.sort(key=lambda entity_id: cache.entity_position(entity_id).distance_squared(bot.destination))
    for entity_id in sources[:8]:
        elapsed = controller.get_cpu_time_elapsed()
        if isinstance(elapsed, (int, float)) and elapsed >= 1150:
            break
        if controller.get_stored_resource(entity_id) in (ResourceType.TITANIUM, ResourceType.REFINED_AXIONITE):
            flow[cache.entity_position(entity_id)] = entity_id, now


def choose(bot, controller, current, now):
    cache = bot.tile_cache
    target = bot.destination
    goals = [p for dx in (-1, 0, 1) for dy in (-1, 0, 1)
             if (p := cache.offset(target, dx, dy)) is not None]
    candidates = []
    for source, (entity_id, _) in bot.hijack_flow.items():
        if source not in cache.visible_tiles:
            continue
        if cache.entity_type(entity_id) == EntityType.BRIDGE:
            site = bot.known_bridge_targets.get(source)
        else:
            facing = cache.entity_direction(entity_id)
            site = cache.neighbor(source, facing) if facing is not None else None
        if (site is None or cache.environment_at(site) in (None, Environment.WALL)
                or bot.hijack_rejected.get(site, 0) > now or bot.in_launcher_zone(site)):
            continue
        occupant = cache.builder_id_at(site)
        if occupant is not None and occupant != bot.entity_id:
            continue
        old = cache.building_at(site)
        if old is not None and (old[1] == bot.team or old[0] not in REPLACEABLE):
            continue
        for kind, radius in ((EntityType.GUNNER, 13), (EntityType.SENTINEL, 32)):
            for goal in goals:
                if site.distance_squared(goal) > radius:
                    continue
                dx, dy = abs(site.x - goal.x), abs(site.y - goal.y)
                if kind == EntityType.GUNNER and dx and dy and dx != dy:
                    continue
                for facing in firing_facings(site, goal, kind, source):
                    score = current.distance_squared(site) + (12 if old is not None else 0)
                    score += 12 if kind == EntityType.SENTINEL else 0
                    candidates.append((score, site, source, kind, facing, goal))
    seen = set()
    checks = 0
    for _, site, source, kind, facing, goal in sorted(candidates, key=lambda item: item[0]):
        key = site, source, kind, facing
        if key in seen:
            continue
        seen.add(key)
        elapsed = controller.get_cpu_time_elapsed()
        if isinstance(elapsed, (int, float)) and elapsed >= 1250:
            break
        checks += 1
        if controller.can_fire_from(site, facing, kind, goal):
            return site, source, kind, facing
        if checks >= 8:
            break
    return None


def try_hijack(bot, controller, current):
    if not bot.destination_is_confirmed_core:
        return False
    now = controller.get_current_round()
    if not hasattr(bot, 'hijack_flow'):
        bot.hijack_flow = {}
        bot.hijack_rejected = {}
        bot.hijack_plan = None
    remember_flow(bot, controller, now)
    if bot.hijack_plan is None:
        bot.hijack_plan = choose(bot, controller, current, now)
        bot.hijack_started = now
        bot.hijack_last_hp = None
    plan = bot.hijack_plan
    if plan is None:
        return False
    site, source, kind, facing = plan
    cache = bot.tile_cache
    source_building = cache.building_at(source)
    if (now - bot.hijack_started > 32 or source_building is None
            or source_building[1] == bot.team or source_building[0] not in TRANSPORT):
        bot.hijack_rejected[site] = now + 48
        bot.hijack_plan = None
        return False
    source_id = cache.building_id_at(source)
    if source_building[0] == EntityType.BRIDGE:
        receiving = bot.known_bridge_targets.get(source)
    else:
        source_facing = cache.entity_direction(source_id)
        receiving = cache.neighbor(source, source_facing) if source_facing is not None else None
    if receiving != site:
        bot.hijack_plan = None
        return False
    old = cache.building_at(site)
    if old is not None and old[1] != bot.team:
        if old[0] not in REPLACEABLE:
            bot.hijack_plan = None
            return False
        if current != site:
            bot.advance_towards_revisitable_target(controller, site)
            return True
        entity_id = cache.building_id_at(site)
        hp = controller.get_hp(entity_id)
        if bot.hijack_last_hp is not None and hp >= bot.hijack_last_hp:
            bot.hijack_rejected[site] = now + 64
            bot.hijack_plan = None
            return False
        if controller.can_fire(site):
            controller.fire(site)
            bot.hijack_last_hp = hp
            if hp <= 2:
                cache.forget_building(site)
        return True
    if old is not None and old[0] != EntityType.ROAD:
        bot.hijack_plan = None
        return False
    if current == site:
        bot.vacate_gunner_site(controller, site)
        return True
    if current.distance_squared(site) > 2:
        target = bot.construction_approach(site)
        if target is not None:
            bot.advance_towards_revisitable_target(controller, target)
        return True
    if old is not None:
        if not controller.can_destroy(site):
            return True
        controller.destroy(site)
        cache.forget_building(site)
    if controller.can_build(kind, site, facing):
        entity_id = controller.build(kind, site, facing)
        cache.remember_building(site, entity_id, kind, bot.team, direction=facing)
        bot.hijack_plan = None
    return True
