"""Protect productive mine ports without delaying their connection to the core."""

from cambc import EntityType, GameConstants
from finalbot.shared.constants import ORTHOGONAL_DIRECTIONS


def guard_harvester(bot, controller, current):
    ore = bot.target_ore
    guards = bot.harvester_guard_tiles
    if not bot.target_is_connection or ore is None or not guards:
        return False
    cache = bot.tile_cache
    enemies = [cache.entity_position(entity_id)
               for entity_id in cache.visible_entity_ids
               if cache.entity_team(entity_id) != bot.team
               and cache.entity_type(entity_id) in (
                   EntityType.BUILDER_BOT, EntityType.GUNNER,
                   EntityType.SENTINEL, EntityType.BREACH)
               and cache.entity_position(entity_id).distance_squared(ore) <= 32]
    # A mine without a completed outlet earns nothing. Its construction
    # reserve goes to that outlet before optional port sealing.
    if not enemies and not bot.harvester_is_connected(ore):
        return False
    guns = sum(cache.building_at(p) == (EntityType.GUNNER, bot.team)
                for d in ORTHOGONAL_DIRECTIONS
                if (p := cache.neighbor(ore, d)) is not None)
    reserve = 4 * controller.get_conveyor_cost()[0]
    for guard in sorted(guards, key=lambda p: (current.distance_squared(p), p.x, p.y)):
        if current.distance_squared(guard) > GameConstants.ACTION_RADIUS_SQ:
            continue
        old = cache.building_at(guard)
        if old is not None and old != (EntityType.ROAD, bot.team):
            guards.discard(guard)
            continue
        facing = ore.direction_to(guard) if guard != current and guns < 2 else None
        can_target_enemy = False
        if enemies and facing is not None:
            for enemy in enemies:
                direction = guard.direction_to(enemy)
                # Facing the supplying mine closes the ammunition input.
                if cache.neighbor(guard, direction) == ore:
                    continue
                if controller.can_fire_from(guard, direction, EntityType.GUNNER, enemy):
                    facing = direction
                    can_target_enemy = True
                    break
        # Two adjacent guns can cover the other ports together. A single
        # gun cannot return fire through its supplying mine to the far port.
        reserve_for_mining = 0 if enemies else controller.get_harvester_cost()[0]
        near_core = bot.core_pos is not None and ore.distance_squared(bot.core_pos) <= 64
        use_gunner = (facing is not None
                      and (can_target_enemy or near_core)
                      and controller.get_global_resources()[0]
                      >= reserve + reserve_for_mining + controller.get_gunner_cost()[0]
                      and controller.get_unit_count() < GameConstants.MAX_TEAM_UNITS - 10)
        # Rejecting conveyors are walkable. Barriers can disconnect a known
        # construction route, even when their tile has several neighbours.
        direction = facing if use_gunner else guard.direction_to(ore)
        if not use_gunner and direction not in ORTHOGONAL_DIRECTIONS:
            guards.discard(guard)
            continue
        if old is not None:
            if not controller.can_destroy(guard):
                continue
            controller.destroy(guard)
            cache.forget_building(guard)
        if use_gunner:
            if not controller.can_build_gunner(guard, direction):
                continue
            entity_id = controller.build_gunner(guard, direction)
            kind = EntityType.GUNNER
        else:
            if not controller.can_build_conveyor(guard, direction):
                continue
            entity_id = controller.build_conveyor(guard, direction)
            kind = EntityType.CONVEYOR
            bot.network_blueprint[guard] = (kind, direction, None)
        cache.remember_building(guard, entity_id, kind, bot.team, direction=direction)
        guards.discard(guard)
        bot.last_progress_round = bot.rounds_alive
        return True
    return False
