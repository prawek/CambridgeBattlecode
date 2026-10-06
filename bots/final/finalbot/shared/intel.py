"""Share stationary threats between the core and its shorter-sighted workers."""

from cambc import EntityType

from finalbot.shared.constants import MARKER_KIND_THREAT
from finalbot.shared.geometry import decode_marker_coordinates, encode_marker

THREAT_CODES = {EntityType.GUNNER: 1, EntityType.SENTINEL: 2, EntityType.BREACH: 3}
CODE_THREATS = {code: kind for kind, code in THREAT_CODES.items()}


def reported_threats(bot):
    cache = bot.tile_cache
    result = []
    for value in cache.marker_values.values():
        kind, x, y, code = decode_marker_coordinates(value)
        if kind != MARKER_KIND_THREAT or code not in CODE_THREATS:
            continue
        pos = cache.position_at(x, y)
        if pos is not None:
            result.append((CODE_THREATS[code], pos))
    return result


def broadcast_threat(bot, controller, threats):
    candidates = [(kind, pos) for kind, pos, _ in threats if kind in THREAT_CODES]
    pad = getattr(bot, 'threat_report_pad', None)
    active = {bot.defender_order_pad}
    if bot.intruder_order_active:
        active.add(bot.intruder_order_pad)
    if bot.spawn_order_active:
        active.add(bot.spawn_order_pad)
    if pad is not None and pad in active:
        return
    if not candidates:
        if pad is not None:
            entity_id = controller.get_tile_building_id(pad)
            if (entity_id is not None and controller.get_entity_type(entity_id) == EntityType.MARKER
                    and controller.get_marker_value(entity_id) == bot.threat_report_value):
                bot.retire_role_marker(controller, pad)
            bot.threat_report_pad = None
            bot.threat_report_value = None
        return
    kind, pos = min(candidates, key=lambda item: item[1].distance_squared(bot.core_pos))
    value = encode_marker(MARKER_KIND_THREAT, pos, THREAT_CODES[kind])
    if pad is not None:
        entity_id = controller.get_tile_building_id(pad)
        if entity_id is None or controller.get_entity_type(entity_id) != EntityType.MARKER:
            pad = None
    if (pad is not None and getattr(bot, 'threat_report_value', None) == value
            and controller.get_marker_value(entity_id) == value):
        return
    if pad is None:
        pad = bot.find_defender_order_pad(controller)
    if pad is not None and controller.can_place_marker(pad):
        controller.place_marker(pad, value)
        bot.threat_report_pad = pad
        bot.threat_report_value = value
