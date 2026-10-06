"""Select, validate and construct the forward gunner position."""

from cambc import Controller, Direction, EntityType, Environment, GameConstants, Position
from finalbot.shared.constants import DIRECTIONS, ORTHOGONAL_DIRECTIONS
from finalbot.combat.intruder.settings import (
    _CLEARABLE_WALKABLE_BUILDINGS,
    _GUNNER_SITE_VALIDATIONS_PER_TURN,
)


class IntruderTargeting:
    """Uses state initialized by IntruderBot."""

    def build_forward_gunner(self, controller: Controller, current: Position) -> None:
        """Choose a viable Core shot, then reach and build the Gunner."""
        if self.gunner_site is None:
            site_data = self.choose_gunner_site(controller, current)
            if site_data is None:
                if self.gunner_site_search_pending():
                    # The engine-check budget was spent before this ordered
                    # search reached a conclusion.  Keep the Intruder still
                    # so the next turn checks the same remaining candidates.
                    return
                # Only after every locally known Core-edge shot has been
                # checked across one or more turns may ordinary exploration
                # look for more terrain and a different firing position.
                self.advance_towards_unvisited_target(controller, self.destination)
                return
            self.gunner_site, self.gunner_direction = site_data

        site = self.gunner_site
        building = self.known_buildings.get(site)
        if self.is_protected_transport(site):
            self.rejected_gunner_sites.add(site)
            self.gunner_site = None
            self.gunner_direction = None
            return
        if building is not None:
            if building[0] not in _CLEARABLE_WALKABLE_BUILDINGS:
                self.rejected_gunner_sites.update((site,))
                self.gunner_site = None
                self.gunner_direction = None
                return
            if current != site:
                self.advance_towards_revisitable_target(controller, site)
                return
            self.clear_walkable_tile(controller, site, allow_enemy_road=True)
            return

        if current == site:
            self.vacate_gunner_site(controller, site)
            return
        if current.distance_squared(site) > GameConstants.ACTION_RADIUS_SQ:
            approach = self.construction_approach(site)
            self.advance_towards_revisitable_target(
                controller,
                approach or site,
            )
            return
        if self.gunner_direction is None:
            self.rejected_gunner_sites.update((site,))
            self.gunner_site = None
            self.gunner_direction = None
            return
        if not controller.can_build_gunner(site, self.gunner_direction):
            # A road was just removed or the bot has just moved here.  In
            # both cases its action cooldown may still be one for this turn;
            # retain the geometrically validated site and retry next round.
            return
        self.gunner_id = controller.build_gunner(site, self.gunner_direction)
        self.tile_cache.remember_building(
            site,
            self.gunner_id,
            EntityType.GUNNER,
            self.team,
            direction=self.gunner_direction,
        )
        self.reset_supply_plan()

    def vacate_gunner_site(self, controller: Controller, site: Position) -> bool:
        """Move off an empty Gunner site so the stationary unit can be built there.

        A BuilderBot may clear a road while standing on it, but cannot create
        a non-passable Gunner on the tile it occupies.  It may build a short
        escape road and move in the same turn; the following turn builds the
        Gunner from the adjacent action-radius tile.
        """
        current = self.get_cached_position()
        for direction in DIRECTIONS:
            target = self.tile_cache.neighbor(current, direction)
            if target is None:
                continue
            if target == site or not self.is_roadable_position(target):
                continue
            if self.try_move_step(controller, direction):
                return True
        return False

    def choose_gunner_site(
            self,
            controller: Controller,
            current: Position,
    ) -> tuple[Position, Direction] | None:
        """Immediately select the first viable Core shot near this Intruder.

        The first three Core-edge targets are the closest to ``current``.
        For each one, firing directions nearest the direct Intruder-to-target
        line are tried first.  Only if those three targets have no valid shot
        does the search fan out to Core edges farther from that direct line.
        """
        if not self.destination_is_confirmed_core or self.destination is None:
            self.clear_gunner_site_search()
            return None

        if (
            self.gunner_search_origin != current
            or self.gunner_search_destination != self.destination
        ):
            self.start_gunner_site_search(current)

        validations = 0
        while (
            self.gunner_site_candidate_cursor < len(self.gunner_site_candidates)
            and validations < _GUNNER_SITE_VALIDATIONS_PER_TURN
        ):
            site, facing, target = self.gunner_site_candidates[
                self.gunner_site_candidate_cursor
            ]
            self.gunner_site_candidate_cursor += 1
            if not self.is_gunner_site_locally_viable(site):
                continue
            validations += 1
            if controller.can_fire_from(
                site,
                facing,
                EntityType.GUNNER,
                target,
            ):
                self.clear_gunner_site_search()
                return site, facing

        if self.gunner_site_candidate_cursor >= len(self.gunner_site_candidates):
            self.clear_gunner_site_search()
        return None

    def start_gunner_site_search(self, current: Position) -> None:
        """Create one ordered, resumable queue of Core-shot candidates."""
        self.clear_gunner_site_search()
        self.gunner_search_origin = current
        self.gunner_search_destination = self.destination
        closest, fallback = self.gunner_target_groups(current)
        for targets in (closest, fallback):
            for target in targets:
                for facing in self.gunner_facing_directions(current, target):
                    max_distance = 3 if facing in ORTHOGONAL_DIRECTIONS else 2
                    for distance in range(max_distance, 0, -1):
                        site = target
                        for _ in range(distance):
                            site = self.tile_cache.neighbor(site, facing.opposite())
                            if site is None:
                                break
                        if site is not None:
                            self.gunner_site_candidates.append((site, facing, target))

    def gunner_site_search_pending(self) -> bool:
        """Return whether the current Core-shot queue still has untried entries."""
        return self.gunner_site_candidate_cursor < len(self.gunner_site_candidates)

    def clear_gunner_site_search(self) -> None:
        """Discard a completed or obsolete Gunner-site candidate queue."""
        self.gunner_site_candidates = []
        self.gunner_site_candidate_cursor = 0
        self.gunner_search_origin = None
        self.gunner_search_destination = None

    def ordered_gunner_targets(self, current: Position) -> tuple[Position, ...]:
        """Prioritise the three Core edges nearest the Intruder.

        Once those direct targets fail, try the remaining edge cells from the
        greatest perpendicular offset from the Core-to-Intruder segment.  The
        fallback therefore deliberately fans out from the direct approach.
        """
        closest, fallback = self.gunner_target_groups(current)
        return closest + fallback

    def gunner_target_groups(
            self,
            current: Position,
    ) -> tuple[tuple[Position, ...], tuple[Position, ...]]:
        """Return nearest Core edges and their lateral fallback separately."""
        enemy_core = self.destination
        if enemy_core is None:
            return (), ()
        targets = self.enemy_core_edge_tiles()
        closest = sorted(
            targets,
            key=lambda pos: (
                pos.distance_squared(current),
                self.distance_squared_to_core_segment(pos, enemy_core, current),
                pos.y,
                pos.x,
            ),
        )[:3]
        closest_set = set(closest)
        fallback = sorted(
            (pos for pos in targets if pos not in closest_set),
            key=lambda pos: (
                self.distance_squared_to_core_segment(pos, enemy_core, current),
                pos.distance_squared(current),
                pos.y,
                pos.x,
            ),
            reverse=True,
        )
        return tuple(closest), tuple(fallback)

    @staticmethod
    def distance_squared_to_core_segment(
            pos: Position,
            core: Position,
            intruder: Position,
    ) -> int:
        """Return a common-scale squared distance from ``pos`` to Core--Intruder."""
        dx = intruder.x - core.x
        dy = intruder.y - core.y
        length_squared = dx * dx + dy * dy
        if length_squared == 0:
            return pos.distance_squared(core)
        offset_x = pos.x - core.x
        offset_y = pos.y - core.y
        projection = offset_x * dx + offset_y * dy
        if projection <= 0:
            return pos.distance_squared(core) * length_squared
        if projection >= length_squared:
            return pos.distance_squared(intruder) * length_squared
        cross_product = offset_x * dy - offset_y * dx
        return cross_product * cross_product

    @staticmethod
    def gunner_facing_directions(
            current: Position,
            target: Position,
    ) -> tuple[Direction, ...]:
        """List Gunner facings from the direct Intruder-to-target ray outward."""
        direct = current.direction_to(target)
        if direct == Direction.CENTRE:
            return tuple(DIRECTIONS)
        directions = [direct]
        left = direct
        right = direct
        for _ in range(3):
            left = left.rotate_left()
            right = right.rotate_right()
            directions.extend((left, right))
        directions.append(direct.opposite())
        return tuple(dict.fromkeys(directions))

    def is_gunner_site_locally_viable(self, site: Position) -> bool:
        """Reject unscanned terrain, walls, solid buildings, and rejected sites."""
        if site in self.rejected_gunner_sites or self.is_protected_transport(site):
            return False
        if self.known_env.get(site) in {
            None,
            Environment.WALL,
        }:
            return False
        building = self.known_buildings.get(site)
        return (
            building is None
            or building[0] in _CLEARABLE_WALKABLE_BUILDINGS
        )

    def enemy_core_edge_tiles(self) -> tuple[Position, ...]:
        """Return all in-bounds perimeter cells of the known 3x3 enemy Core."""
        enemy_core = self.destination
        if not self.destination_is_confirmed_core or enemy_core is None:
            return ()
        return tuple(
            pos
            for dx in range(-1, 2)
            for dy in range(-1, 2)
            if (
                (dx != 0 or dy != 0)
                and (pos := self.tile_cache.offset(enemy_core, dx, dy)) is not None
            )
        )
