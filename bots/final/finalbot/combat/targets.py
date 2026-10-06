"""Target values shared by stationary weapons.

An enemy mine can also be our ammunition source. Preserve an adjacent
titanium harvester even when its ownership has not changed.
"""

from cambc import EntityType


TARGET_PRIORITY = {
    EntityType.GUNNER: 120,
    EntityType.SENTINEL: 120,
    EntityType.BREACH: 120,
    EntityType.BUILDER_BOT: 110,
    EntityType.CORE: 100,
    EntityType.LAUNCHER: 90,
    EntityType.FOUNDRY: 45,
    EntityType.HARVESTER: 25,
    EntityType.BRIDGE: 20,
    EntityType.CONVEYOR: 15,
    EntityType.SPLITTER: 15,
    EntityType.ARMOURED_CONVEYOR: 10,
    EntityType.BARRIER: 5,
    # A road blocks a gunner ray. Clear it when already aimed at it; rotation
    # toward unrelated roads is filtered by the gunner's aiming policy.
    EntityType.ROAD: 1,
}


def is_ammo_source(origin, target, kind):
    return (kind == EntityType.HARVESTER
            and origin is not None
            and abs(origin.x - target.x) + abs(origin.y - target.y) == 1)


def target_priority(controller, entity_id, kind):
    if kind == EntityType.CORE:
        hp = controller.get_hp(entity_id)
        if isinstance(hp, (int, float)) and hp <= 10:
            return 160
    return TARGET_PRIORITY.get(kind, 0)
