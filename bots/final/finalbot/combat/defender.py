"""Keep the core alive while the forward batteries are being established."""

from typing import NamedTuple

from cambc import Direction, EntityType, GameConstants, GameError, Position, Team
from finalbot.shared.constants import DIRECTIONS
from finalbot.world.tile_cache import TileCache


class UnitObservation(NamedTuple):
    entity_id: int
    kind: EntityType
    team: Team
    position: Position
    facing: Direction | None


class DefenderBot:
    def __init__(self, width, height):
        self.core = None
        self.cache = TileCache(width, height)
        self.visits = {}
        self.launcher_attempts = {}
        self.nearby_units = []

    def run(self, controller):
        if self.core is None:
            for entity_id in controller.get_nearby_buildings():
                if controller.get_entity_type(entity_id) == EntityType.CORE and controller.get_team(entity_id) == controller.get_team():
                    self.core = controller.get_position(entity_id)
                    break
        current = controller.get_position()
        if self.core is None:
            return
        # Movement changes vision immediately. Capture the properties while
        # each ID is visible, then use observations rather than old IDs.
        self.nearby_units = self.observe_units(controller)
        if self.take_covering_position(controller, current):
            current = self.cache.canonicalize(controller.get_position())
        at_core = max(abs(current.x - self.core.x), abs(current.y - self.core.y)) <= 1
        if self.shield_core(controller, current):
            return
        # A heal on our occupied core tile repairs both entities. Repeatedly
        # healing a different corner loses the defender and its spawn cost.
        if at_core and controller.get_hp() < GameConstants.BUILDER_BOT_MAX_HP:
            if controller.can_heal(current):
                controller.heal(current)
                return
        if self.intercept_raider(controller, current):
            return
        if at_core and controller.can_heal(current):
            controller.heal(current)
            return
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                tile = self.cache.offset(self.core, dx, dy)
                if tile is not None and current.distance_squared(tile) <= 2 and controller.can_heal(tile):
                    controller.heal(tile)
                    return
        if at_core:
            return
        # A hostile launcher does not change our assignment. Walk back to a
        # repair position; repeated visits keep a wall detour from cycling.
        self.visits[current] = self.visits.get(current, 0) + 1
        steps = []
        for direction in DIRECTIONS:
            tile = self.cache.neighbor(current, direction)
            if tile is not None:
                steps.append((tile.distance_squared(self.core) + 8*self.visits.get(tile, 0), direction, tile))
        for _, direction, tile in sorted(steps, key=lambda v: v[0]):
            if controller.can_move(direction):
                controller.move(direction)
                return
            if controller.can_build_road(tile):
                controller.build_road(tile)
                if controller.can_move(direction):
                    controller.move(direction)
                return

    def observe_units(self, controller):
        team = controller.get_team()
        observed = []
        for entity_id in controller.get_nearby_units():
            try:
                owner = controller.get_team(entity_id)
                kind = controller.get_entity_type(entity_id)
                if owner == team:
                    if kind != EntityType.LAUNCHER:
                        continue
                elif kind not in (EntityType.BUILDER_BOT, EntityType.GUNNER):
                    continue
                position = self.cache.canonicalize(controller.get_position(entity_id))
                facing = controller.get_direction(entity_id) if kind == EntityType.GUNNER else None
            except GameError as error:
                # Some batched IDs may already have left vision. Do not
                # convert unrelated engine failures into missing enemies.
                if str(error) not in ("Position out of vision range", "Unknown id"):
                    raise
                continue
            observed.append(UnitObservation(entity_id, kind, owner, position, facing))
        return observed

    def take_covering_position(self, controller, current):
        """Reach the core edge so barriers can be placed outside its footprint."""
        team = controller.get_team()
        guns = [unit.position for unit in self.nearby_units
                if unit.team != team and unit.kind == EntityType.GUNNER]
        if not guns or max(abs(current.x - self.core.x), abs(current.y - self.core.y)) > 1:
            return False
        target = min(guns, key=lambda p: current.distance_squared(p))
        distance = current.distance_squared(target)
        choices = []
        for direction in DIRECTIONS:
            pos = self.cache.neighbor(current, direction)
            if pos is None or max(abs(pos.x - self.core.x), abs(pos.y - self.core.y)) > 1:
                continue
            if pos.distance_squared(target) < distance:
                choices.append((pos.distance_squared(target), direction))
        for _, direction in sorted(choices, key=lambda item: item[0]):
            if controller.can_move(direction):
                controller.move(direction)
                return True
        return False

    def intercept_raider(self, controller, current):
        """Displace a siege builder before it installs or repairs a battery."""
        team = controller.get_team()
        raiders = []
        launchers = []
        for unit in self.nearby_units:
            if unit.kind == EntityType.BUILDER_BOT and unit.team != team:
                pos = unit.position
                if pos.distance_squared(self.core) <= 25 and pos.distance_squared(current) <= 8:
                    raiders.append(pos)
            elif unit.kind == EntityType.LAUNCHER and unit.team == team:
                launchers.append(unit.position)
        if not raiders:
            return False
        if len(launchers) >= 2:
            return False
        if controller.get_global_resources()[0] < controller.get_launcher_cost()[0]:
            return False
        now = controller.get_current_round()
        for enemy in raiders:
            if any(enemy.distance_squared(site) <= 2 for site in launchers):
                continue
            for direction in DIRECTIONS:
                site = self.cache.neighbor(current, direction)
                if site is None or site.distance_squared(enemy) > 2:
                    continue
                if self.launcher_attempts.get(site, 0) > now:
                    continue
                old = controller.get_tile_building_id(site)
                if old is not None:
                    if controller.get_team(old) != team or controller.get_entity_type(old) != EntityType.ROAD:
                        continue
                    if not controller.can_destroy(site):
                        continue
                    controller.destroy(site)
                if controller.can_build_launcher(site):
                    controller.build_launcher(site)
                    self.launcher_attempts[site] = now + 128
                    return True
        return False

    def shield_core(self, controller, current):
        """Put a replaceable barrier in a gunner ray before it reaches core."""
        team = controller.get_team()
        for unit in self.nearby_units:
            if unit.team == team or unit.kind != EntityType.GUNNER:
                continue
            origin = unit.position
            facing = unit.facing
            pos = origin
            ray = []
            for _ in range(3):
                pos = self.cache.neighbor(pos, facing)
                if pos is None or origin.distance_squared(pos) > 13:
                    break
                if max(abs(pos.x-self.core.x), abs(pos.y-self.core.y)) <= 1:
                    for shield in reversed(ray):
                        if shield == current or current.distance_squared(shield) > 2:
                            continue
                        old = controller.get_tile_building_id(shield)
                        if old is not None:
                            if controller.get_team(old) != team:
                                continue
                            kind = controller.get_entity_type(old)
                            if kind == EntityType.BARRIER:
                                # A 30-HP shield absorbs three titanium shots.
                                # Replacing it costs less than healing away
                                # ten damage four HP at a time. Repair core
                                # while the existing shield holds the ray.
                                continue
                            if kind != EntityType.ROAD or not controller.can_destroy(shield):
                                continue
                            titanium, axionite = controller.get_global_resources()
                            barrier_titanium, barrier_axionite = controller.get_barrier_cost()
                            if titanium < barrier_titanium or axionite < barrier_axionite:
                                continue
                            controller.destroy(shield)
                        if controller.can_build_barrier(shield):
                            controller.build_barrier(shield)
                            return True
                    break
                ray.append(pos)
        return False
