"""Role-local search bounds and precomputed geometric offsets."""

from cambc import GameConstants

_VISION_RADIUS = int(GameConstants.BUILDER_BOT_VISION_RADIUS_SQ ** 0.5)

SCOUT_VISION_OFFSETS = tuple(
    (dx, dy)
    for dx in range(-_VISION_RADIUS, _VISION_RADIUS + 1)
    for dy in range(-_VISION_RADIUS, _VISION_RADIUS + 1)
    if dx * dx + dy * dy <= GameConstants.BUILDER_BOT_VISION_RADIUS_SQ
)

TRANSPORT_BRIDGE_OFFSETS = tuple(
    (dx, dy) for dx in range(-3, 4) for dy in range(-3, 4)
    if 1 < dx * dx + dy * dy <= GameConstants.BRIDGE_TARGET_RADIUS_SQ
)
