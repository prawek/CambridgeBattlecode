from cambc import Controller, Direction, EntityType, Position

from finalbot.shared.bot import BaseBot
from finalbot.shared.constants import MARKER_KIND_ENEMY
from finalbot.shared.geometry import decode_marker
from finalbot.combat.targets import target_priority, is_ammo_source


class GunnerBot(BaseBot):
    def run(self, controller: Controller) -> None:
        """Fire at an available target or rotate toward a shared enemy marker."""
        # Firing must not wait for terrain scanning or symmetry inference.
        # can_fire checks geometry, not allegiance. Friendly entities in the
        # ray must never be mistaken for targets.
        team = controller.get_team()
        candidates = []
        for tile in controller.get_attackable_tiles():
            entity_id = controller.get_tile_builder_bot_id(tile)
            if entity_id is None:
                entity_id = controller.get_tile_building_id(tile)
            if entity_id is None or controller.get_team(entity_id) == team:
                continue
            kind = controller.get_entity_type(entity_id)
            if kind == EntityType.HARVESTER:
                origin = self.current_position or controller.get_position()
                if is_ammo_source(origin, tile, kind):
                    continue
            priority = target_priority(controller, entity_id, kind)
            if not priority:
                continue
            if controller.can_fire(tile):
                candidates.append((priority, tile))
        if candidates:
            controller.fire(max(candidates, key=lambda item: item[0])[1])
            return
        if self._scan_turn(controller, read_markers=True):
            return

        # A mine-fed gunner may need to turn from its ammo intake toward a
        # raider, counter-battery or the source it is capturing.
        ammo = controller.get_ammo_amount()
        facing = self.tile_cache.entity_direction(self.entity_id)
        if ammo == 0 and facing is not None:
            source = self.tile_cache.neighbor(self.current_position, facing)
            building = self.tile_cache.building_at(source) if source is not None else None
            if building is not None and building[0] == EntityType.HARVESTER:
                # Firing toward a captured mine closes that ammo port. Reopen
                # it after the magazine empties instead of remaining stuck.
                reload_direction = facing.opposite()
                if controller.can_rotate(reload_direction):
                    controller.rotate(reload_direction)
                    self.last_rotation_round = controller.get_current_round()
                    return
        now = controller.get_current_round()
        if isinstance(now, int) and now < getattr(self, 'last_rotation_round', -10) + 2:
            return
        targets = []
        for entity_id in self.tile_cache.visible_entity_ids:
            if self.tile_cache.entity_team(entity_id) == team:
                continue
            kind = self.tile_cache.entity_type(entity_id)
            if kind == EntityType.ROAD:
                continue
            priority = target_priority(controller, entity_id, kind)
            pos = self.tile_cache.entity_position(entity_id)
            if not priority or pos is None or self.current_position.distance_squared(pos) > 13:
                continue
            occupant = self.tile_cache.builder_id_at(pos)
            if occupant is not None and self.tile_cache.entity_team(occupant) == team:
                continue
            if kind == EntityType.HARVESTER and ammo < 4:
                continue
            if is_ammo_source(self.current_position, pos, kind):
                continue
            direction = self.current_position.direction_to(pos)
            if ammo > 0 and controller.can_rotate(direction) and controller.can_fire_from(
                    self.current_position, direction, EntityType.GUNNER, pos):
                targets.append((priority, direction))
        if targets:
            controller.rotate(max(targets, key=lambda v: v[0])[1])
            self.last_rotation_round = now
            return

        # Empty guns must leave the intake open until the next mine output.
        # Otherwise an enemy marker beyond the source turns the barrel back
        # into the mine every other turn, paying Ti without ever reloading.
        if ammo == 0:
            return
        marker_target = self.read_enemy_marker()
        if marker_target is None:
            return
        desired = self.get_cached_position().direction_to(marker_target)
        current_direction = (
            None if self.entity_id is None
            else self.tile_cache.entity_direction(self.entity_id)
        )
        if (desired != Direction.CENTRE and desired != current_direction
                and controller.can_rotate(desired)
                and controller.can_fire_from(self.current_position, desired, EntityType.GUNNER, marker_target)):
            controller.rotate(desired)
            self.last_rotation_round = now

    def read_enemy_marker(self) -> Position | None:
        """Return the first nearby marker that contains an enemy position."""
        for entity_id in self.tile_cache.marker_ids():
            marker_value = self.tile_cache.marker_values.get(entity_id)
            if marker_value is None:
                continue
            try:
                kind, pos, _ = decode_marker(
                    marker_value,
                    self.tile_cache.position_at,
                )
            except Exception:
                continue
            if kind == MARKER_KIND_ENEMY:
                return pos
        return None
