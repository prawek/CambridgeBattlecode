"""Remember observed firing lanes when pricing and repairing transport."""

from cambc import EntityType


def update_fire_lanes(bot, controller):
    cache = bot.tile_cache
    guns = getattr(bot, 'known_hostile_turrets', {})
    for pos in tuple(guns):
        if pos in cache.visible_tiles:
            building = cache.building_at(pos)
            if building is None or building[1] == bot.team or building[0] not in (
                    EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH):
                del guns[pos]
    for entity_id in cache.visible_entity_ids:
        kind = cache.entity_type(entity_id)
        if cache.entity_team(entity_id) != bot.team and kind in (
                EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH):
            pos = cache.entity_position(entity_id)
            facing = cache.entity_direction(entity_id)
            if pos is not None and facing is not None:
                guns[pos] = kind, facing
    bot.known_hostile_turrets = guns
    signature = frozenset(guns.items())
    if signature == getattr(bot, 'fire_lane_signature', None):
        return
    danger = set()
    for pos, (kind, facing) in guns.items():
        danger.update(cache.canonicalize(p) for p in
                      controller.get_attackable_tiles_from(pos, facing, kind))
    bot.fire_lane_signature = signature
    bot.threatened_transport_tiles = danger
    # A completed route search priced before an enemy arrived is no longer
    # an accurate construction quote. Resume planning with the new lanes.
    bot.search_memory.jobs.clear()


def transport_risk(bot, pos, conveyor_cost):
    return 8 * conveyor_cost if pos in getattr(bot, 'threatened_transport_tiles', ()) else 0
