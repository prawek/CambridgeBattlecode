"""Local anti-infiltration actions shared by economy builders."""

from cambc import EntityType
from finalbot.shared.constants import DIRECTIONS, ORTHOGONAL_DIRECTIONS
from finalbot.combat.local import defend_with_battery
from finalbot.world.fire_lanes import update_fire_lanes

TURRETS = {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}


def core_defender_demand(bot, controller):
    """Prepare for visible siege and size repairs by sustained incoming damage."""
    hp = controller.get_hp(bot.entity_id)
    damage = 0
    raiders = 0
    receivers = bot.core_receiver_positions()
    for kind, pos, facing in core_threats(bot, controller):
        if pos is None:
            continue
        if kind == EntityType.BUILDER_BOT:
            if pos.distance_squared(bot.core_pos) <= 25:
                raiders += 1
            continue
        if kind not in TURRETS:
            continue
        if facing is None:
            continue
        # Test actual lines of fire: distant and blocked guns do not justify
        # a permanent repair crew. Sentinels deliver 18 HP every three turns.
        if any(controller.can_fire_from(pos, facing, kind, tile) for tile in receivers):
            damage += 10 if kind == EntityType.GUNNER else 6 if kind == EntityType.SENTINEL else 40
    desired = 1 if raiders or hp < 490 else 0
    approach_distance = max(abs(bot.map_width - 1 - 2 * bot.core_pos.x),
                            abs(bot.map_height - 1 - 2 * bot.core_pos.y))
    if controller.get_current_round() >= 7 and approach_distance <= 18:
        desired = max(1, desired)
    if damage:
        desired = max(desired, (damage + 3) // 4 + 1)
    if hp < 250:
        desired = max(desired, 3)
    # Leave two core tiles available for fresh workers and reinforcements.
    return min(7, desired)


def core_threats(bot, controller):
    """Refresh moving threats independently of a crowded terrain scan."""
    now = controller.get_current_round()
    if getattr(bot, 'core_threat_round', None) == now:
        return bot.core_threat_snapshot
    cache = bot.tile_cache
    read_units = getattr(controller, 'get_nearby_units', None)
    threats = []
    if read_units is not None:
        for entity_id in read_units():
            if controller.get_team(entity_id) == bot.team:
                continue
            kind = controller.get_entity_type(entity_id)
            if kind not in TURRETS and kind != EntityType.BUILDER_BOT:
                continue
            threats.append((kind, controller.get_position(entity_id),
                            controller.get_direction(entity_id) if kind in TURRETS else None))
    else:
        for entity_id in cache.visible_entity_ids:
            if cache.entity_team(entity_id) != bot.team:
                threats.append((cache.entity_type(entity_id), cache.entity_position(entity_id),
                                cache.entity_direction(entity_id)))
    bot.core_threat_round = now
    bot.core_threat_snapshot = threats
    return threats


def defend_economy(bot, controller, current):
    cache = bot.tile_cache
    now = controller.get_current_round()
    update_fire_lanes(bot, controller)
    if not hasattr(bot, 'defense_cooldowns'):
        bot.defense_cooldowns = {}
    if defend_with_battery(bot, controller, current):
        return True
    if deny_hostile_supply(bot, controller, current):
        return True
    for entity_id in cache.visible_entity_ids:
        if cache.entity_team(entity_id) != bot.team:
            continue
        kind = cache.entity_type(entity_id)
        if kind in (EntityType.HARVESTER, EntityType.GUNNER, EntityType.SENTINEL):
            pos = cache.entity_position(entity_id)
            # Keeping a captured mine alive also replenishes the hostile gun.
            # Save actions for shielding and counter-battery construction.
            if kind == EntityType.HARVESTER and ore_feeds_enemy(bot, pos):
                continue
            if current.distance_squared(pos) <= 2 and controller.can_heal(pos):
                controller.heal(pos)
                bot.last_progress_round = bot.rounds_alive
                return True
    # The dedicated crew handles sustained repair. Workers must finish the
    # income that funds it; stop construction only for an immediate emergency.
    core = bot.core_pos
    if core is not None and current.distance_squared(core) <= 8:
        core_id = cache.building_id_at(core)
        if core_id is not None and controller.get_hp(core_id) < 200:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    tile = cache.offset(core, dx, dy)
                    if tile is not None and controller.can_heal(tile):
                        controller.heal(tile)
                        bot.last_progress_round = bot.rounds_alive
                        return True
    enemies = [pos for pos, entity_id in cache.visible_builder_ids.items()
               if cache.entity_team(entity_id) != bot.team
               and current.distance_squared(pos) <= 8
               and (pos.distance_squared(bot.core_pos) <= 8 or any(
                   pos.distance_squared(ore) <= 8
                   for ore, building in cache.buildings.items()
                   if building == (EntityType.HARVESTER, bot.team)))]
    if not enemies:
        return False
    if controller.get_global_resources()[0] < controller.get_launcher_cost()[0] + 6 * controller.get_conveyor_cost()[0]:
        return False
    launchers = [cache.entity_position(entity_id) for entity_id in cache.visible_entity_ids
                 if cache.entity_team(entity_id) == bot.team
                 and cache.entity_type(entity_id) == EntityType.LAUNCHER]
    if any(current.distance_squared(pos) <= 16 for pos in launchers):
        return False
    enemies = [pos for pos in enemies if not any(pos.distance_squared(p) <= 2 for p in launchers)]
    for enemy in enemies:
        for direction in DIRECTIONS:
            site = cache.neighbor(current, direction)
            if site is None or site.distance_squared(enemy) > 2:
                continue
            if cache.building_at(site) == (EntityType.ROAD, bot.team) and controller.can_destroy(site):
                controller.destroy(site)
                cache.forget_building(site)
            if controller.can_build_launcher(site):
                entity_id = controller.build_launcher(site)
                cache.remember_building(site, entity_id, EntityType.LAUNCHER, bot.team)
                bot.last_progress_round = bot.rounds_alive
                return True
    return False


def deny_hostile_supply(bot, controller, current):
    """Retire a captured mine when it arms the enemy and has no counter-battery."""
    cache = bot.tile_cache
    core = bot.core_pos
    if core is None or current.distance_squared(core) > 20:
        return False
    core_id = cache.building_id_at(core)
    if core_id is None or controller.get_hp(core_id) >= 250:
        return False
    for ore, building in tuple(cache.buildings.items()):
        if building != (EntityType.HARVESTER, bot.team) or current.distance_squared(ore) > 2:
            continue
        ports = [p for d in ORTHOGONAL_DIRECTIONS if (p := cache.neighbor(ore, d)) is not None]
        enemies = [p for p in ports if cache.building_at(p) is not None
                   and cache.building_at(p)[1] != bot.team
                   and cache.building_at(p)[0] in (EntityType.GUNNER, EntityType.SENTINEL)
                   and cache.entity_direction(cache.building_id_at(p)) != p.direction_to(ore)]
        if not enemies:
            continue
        core_tiles = [p for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                      if (p := cache.offset(core, dx, dy)) is not None]
        if not any(controller.can_fire_from(enemy, cache.entity_direction(cache.building_id_at(enemy)),
                                            cache.building_at(enemy)[0], tile)
                   for enemy in enemies for tile in core_tiles):
            continue
        supported = False
        for site in ports:
            cannon = cache.building_at(site)
            if cannon not in ((EntityType.GUNNER, bot.team), (EntityType.SENTINEL, bot.team)):
                continue
            if any(controller.can_fire_from(site, site.direction_to(enemy), cannon[0], enemy)
                   for enemy in enemies):
                supported = True
                break
        if not supported and controller.can_destroy(ore):
            controller.destroy(ore)
            cache.forget_building(ore)
            if bot.target_ore == ore:
                bot.clear_ore_target()
            bot.last_progress_round = bot.rounds_alive
            return True
    return False


def ore_feeds_enemy(bot, ore):
    for direction in ORTHOGONAL_DIRECTIONS:
        site = bot.tile_cache.neighbor(ore, direction)
        building = bot.tile_cache.building_at(site) if site is not None else None
        if building and building[1] != bot.team and building[0] in TURRETS:
            return True
    return False
