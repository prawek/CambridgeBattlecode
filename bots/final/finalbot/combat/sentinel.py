"""Fire immediately at the most valuable enemy in the sentinel's cone."""

from cambc import EntityType, GameConstants
from finalbot.combat.targets import TARGET_PRIORITY, target_priority, is_ammo_source


class SentinelBot:
    def run(self, controller):
        cooldown = controller.get_action_cooldown()
        ammo = controller.get_ammo_amount()
        if (isinstance(cooldown, int) and cooldown > 0) or (isinstance(ammo, int) and ammo == 0):
            return
        team = controller.get_team()
        current = controller.get_position()
        observations = []
        entity_kinds = {}
        for pos in controller.get_attackable_tiles():
            entity_id = controller.get_tile_builder_bot_id(pos)
            if entity_id is None:
                entity_id = controller.get_tile_building_id(pos)
            if entity_id is None:
                continue
            if entity_id not in entity_kinds:
                entity_kinds[entity_id] = (controller.get_entity_type(entity_id)
                                           if controller.get_team(entity_id) != team else None)
            kind = entity_kinds[entity_id]
            if kind is None or kind == EntityType.ROAD or is_ammo_source(current, pos, kind):
                continue
            observations.append((pos, entity_id, kind))
        batteries = [pos for pos, _, kind in observations if kind in (
            EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH, EntityType.LAUNCHER)]
        targets = []
        core_hp = {}
        for pos, entity_id, kind in observations:
            if kind == EntityType.CORE:
                if entity_id not in core_hp:
                    core_hp[entity_id] = controller.get_hp(entity_id)
                hp = core_hp[entity_id]
                priority = (200 if isinstance(hp, (int, float))
                            and hp <= GameConstants.SENTINEL_DAMAGE
                            else TARGET_PRIORITY[EntityType.CORE])
            elif kind == EntityType.BUILDER_BOT:
                # Deny a repairer's next action rather than chase an unrelated
                # scout while the supported enemy weapon keeps firing.
                priority = (150 if any(pos.distance_squared(battery) <= 2 for battery in batteries)
                            else TARGET_PRIORITY[EntityType.BUILDER_BOT])
            else:
                priority = target_priority(controller, entity_id, kind)
            if priority:
                targets.append((priority, pos))
        targets.sort(key=lambda item: item[0], reverse=True)
        for _, pos in targets:
            if controller.can_fire(pos):
                controller.fire(pos)
                return
