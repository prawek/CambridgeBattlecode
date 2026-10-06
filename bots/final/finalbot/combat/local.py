"""Immediate, supplied counter-batteries available to economic workers too."""

from cambc import EntityType, Environment

from finalbot.shared.constants import ORTHOGONAL_DIRECTIONS
from finalbot.combat.siege_planner import firing_facings
from finalbot.shared.intel import reported_threats


def defend_with_battery(bot, controller, current):
    cache = bot.tile_cache
    threats = reported_threats(bot)
    enemy_batteries = []
    for entity_id in cache.visible_entity_ids:
        if cache.entity_team(entity_id) == bot.team:
            continue
        kind = cache.entity_type(entity_id)
        if kind not in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH,
                        EntityType.BUILDER_BOT, EntityType.LAUNCHER):
            continue
        pos = cache.entity_position(entity_id)
        threats.append((kind, pos))
        if kind in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH, EntityType.LAUNCHER):
            enemy_batteries.append(pos)
    if not threats:
        return False
    now = controller.get_current_round()
    cooldowns = getattr(bot, 'defense_cooldowns', {})
    choices = []
    for ore in cache.visible_tiles:
        elapsed = controller.get_cpu_time_elapsed()
        if isinstance(elapsed, (int, float)) and elapsed >= 1100:
            break
        if cache.environment_at(ore) != Environment.ORE_TITANIUM:
            continue
        mine = cache.building_at(ore)
        if mine is None or mine[0] != EntityType.HARVESTER:
            continue
        ports = [p for d in ORTHOGONAL_DIRECTIONS
                 if (p := cache.neighbor(ore, d)) is not None]
        gunners = sum(cache.building_at(p) == (EntityType.GUNNER, bot.team) for p in ports)
        sentinels = sum(cache.building_at(p) == (EntityType.SENTINEL, bot.team) for p in ports)
        if gunners + sentinels >= 2:
            continue
        for site in ports:
            if site == current or current.distance_squared(site) > 2 or cooldowns.get(site, 0) > now:
                continue
            old = cache.building_at(site)
            # Inward guard conveyors reject mine output and carry no income.
            guard = (old == (EntityType.CONVEYOR, bot.team)
                     and cache.entity_direction(cache.building_id_at(site)) == site.direction_to(ore))
            if old not in (None, (EntityType.ROAD, bot.team)) and not guard:
                continue
            for enemy_kind, target in threats:
                distance = site.distance_squared(target)
                priority = 0 if enemy_kind == EntityType.BUILDER_BOT else -20
                for kind, radius in ((EntityType.GUNNER, 13), (EntityType.SENTINEL, 32)):
                    # Reserve expensive control for a nearby repairer or
                    # builder supporting a visible siege battery. A scout
                    # alone does not justify buying a sentinel.
                    if (kind == EntityType.SENTINEL and enemy_kind == EntityType.BUILDER_BOT
                            and (distance > 13 or not any(
                                target.distance_squared(battery) <= 2 for battery in enemy_batteries))):
                        continue
                    if distance > radius:
                        continue
                    dx, dy = abs(target.x - site.x), abs(target.y - site.y)
                    if kind == EntityType.GUNNER and dx and dy and dx != dy:
                        continue
                    score = priority + (12 if kind == EntityType.SENTINEL else 0) + distance
                    if (kind == EntityType.SENTINEL and enemy_kind == EntityType.BUILDER_BOT
                            and gunners and not sentinels):
                        # Add control beside an existing damage dealer rather
                        # than buying a second gun the raider can out-repair.
                        score -= 32
                    for facing in firing_facings(site, target, kind, ore):
                        choices.append((score, site, kind, facing, target))
    for _, site, kind, facing, target in sorted(choices, key=lambda item: item[0])[:12]:
        if not controller.can_fire_from(site, facing, kind, target):
            continue
        if cache.building_at(site) is not None:
            if not controller.can_destroy(site):
                continue
            # Check the bank before removing a worker's walkable guard tile.
            cost = controller.get_gunner_cost()[0] if kind == EntityType.GUNNER else controller.get_sentinel_cost()[0]
            if controller.get_global_resources()[0] < cost:
                continue
            controller.destroy(site)
            cache.forget_building(site)
        if controller.can_build(kind, site, facing):
            entity_id = controller.build(kind, site, facing)
            cache.remember_building(site, entity_id, kind, bot.team, direction=facing)
            bot.defense_cooldowns[site] = now + 96
            bot.last_progress_round = bot.rounds_alive
            return True
    return False
