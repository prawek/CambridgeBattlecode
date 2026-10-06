"""Known-terrain paths, road steps and local wall following."""

from cambc import Controller, Direction, EntityType, Environment, Position
from finalbot.shared.constants import DIRECTIONS, PASSABLE_BUILDINGS
from finalbot.navigation.combat import a_star_to_any
from finalbot.combat.intruder.settings import _SUPPLY_SEARCH_EXPANSIONS


class IntruderMovement:
    """Uses state initialized by IntruderBot."""

    def advance_towards_revisitable_target(
            self,
            controller: Controller,
            target: Position | None,
    ) -> bool:
        """Reach a selected target, allowing known tiles to be used again."""
        if target is None:
            return False
        current = self.get_cached_position()
        search_state = self.a_star_state("revisitable_target")
        path = a_star_to_any(
            None,
            current,
            {target},
            lambda _controller, pos: self.is_roadable_position(pos),
            self.tile_cache.neighbor,
            movement_directions=DIRECTIONS,
            max_expansions=_SUPPLY_SEARCH_EXPANSIONS,
            state=search_state,
        )
        if search_state.pending:
            return False
        if path and self.try_move_step(
                controller,
                current.direction_to(path[0]),
                avoid_visited=False,
        ):
            return True
        # A completed A* failure means the known route is blocked. Repeating
        # a revisitable greedy wall-follow here oscillates forever between
        # the same two cells. Explore fresh ground to reveal another route.
        return self.advance_towards_unvisited_target(controller, target)

    def move_towards(
            self,
            controller: Controller,
            target: Position | None,
            avoid_visited: bool = False,
            forward_sector_only: bool = False,
            remaining_directional_spectrum: bool = False,
            require_closer: bool = False,
    ) -> bool:
        """Advance greedily, optionally avoiding explored cells, or follow a wall."""
        if target is None:
            return False
        current = self.get_cached_position()
        desired = current.direction_to(target)
        if desired == Direction.CENTRE:
            return False
        if forward_sector_only:
            directions = self.forward_sector_directions(desired)
        elif remaining_directional_spectrum:
            directions = self.remaining_exploration_directions(desired)
        else:
            directions = (desired,)
        for direction in directions:
            candidate = self.tile_cache.neighbor(current, direction)
            if candidate is None:
                continue
            if (
                require_closer
                and candidate.distance_squared(target) >= current.distance_squared(target)
            ):
                continue
            if self.try_move_step(controller, direction, avoid_visited=avoid_visited):
                self.heading = direction
                self.wall_following = False
                return True

        # Explicit exploration probes do not spill into a different movement
        # policy.  The caller decides whether to try wall following or the
        # remaining direction spectrum next.
        if (
            forward_sector_only
            or remaining_directional_spectrum
        ):
            return False

        self.wall_following = True
        heading = self.heading or desired
        retreat = (
            None
            if self.previous_position is None
            else current.direction_to(self.previous_position)
        )
        right_hand = self.right_hand_directions(heading)
        attempted = set(right_hand)
        for direction in right_hand:
            if self.try_move_step(controller, direction, avoid_visited=avoid_visited):
                self.heading = direction
                return True

        # A wall follower must exhaust every side exit before it walks back to
        # the tile it just left.  Returning first creates a two-tile loop at
        # a wall corner: on the next turn the exact same priority order brings
        # the bot straight back.  Keep the previous tile as a true last resort.
        for direction in DIRECTIONS:
            if direction in attempted or direction == retreat:
                continue
            if self.try_move_step(controller, direction, avoid_visited=avoid_visited):
                self.heading = direction
                return True
        if (
            retreat is not None
            and retreat != Direction.CENTRE
            and self.try_move_step(controller, retreat, avoid_visited=avoid_visited)
        ):
            self.heading = retreat
            return True
        return False

    def forward_sector_directions(self, desired: Direction) -> tuple[Direction, ...]:
        """Return the direct heading and its two adjacent forward diagonals."""
        return (
            desired,
            desired.rotate_left(),
            desired.rotate_right(),
        )

    def remaining_exploration_directions(
            self,
            desired: Direction,
    ) -> tuple[Direction, ...]:
        """Return the five directions deferred until wall following fails.

        For NORTH the order is EAST, WEST, SOUTHEAST, SOUTHWEST, SOUTH.
        """
        left = desired.rotate_left()
        right = desired.rotate_right()
        return (
            right.rotate_right(),
            left.rotate_left(),
            right.rotate_right().rotate_right(),
            left.rotate_left().rotate_left(),
            desired.opposite(),
        )

    def start_exploration_wall_following(
            self,
            controller: Controller,
            target: Position | None,
            side: str,
            avoid_visited: bool,
            record_branch: bool = True,
    ) -> bool:
        """Choose a wall side and make the first unvisited bypass step."""
        if target is None:
            return False
        current = self.get_cached_position()
        desired = current.direction_to(target)
        if desired == Direction.CENTRE:
            return False
        self.stop_exploration_wall_following()
        self.exploration_wall_side = side
        self.exploration_wall_heading = (
            desired.rotate_right().rotate_right()
            if side == "left"
            else desired.rotate_left().rotate_left()
        )
        self.wall_following = True
        if self.continue_exploration_wall_following(controller, avoid_visited):
            if record_branch:
                self.exploration_branch_stack.append((current, side))
            return True
        self.stop_exploration_wall_following()
        return False

    def continue_exploration_wall_following(
            self,
            controller: Controller,
            avoid_visited: bool,
    ) -> bool:
        """Continue on the selected side; never switch sides implicitly."""
        side = self.exploration_wall_side
        heading = self.exploration_wall_heading
        if side is None or heading is None:
            return False
        directions = (
            self.left_wall_directions(heading)
            if side == "left"
            else self.right_wall_directions(heading)
        )
        for direction in directions:
            if self.try_move_step(controller, direction, avoid_visited=avoid_visited):
                self.exploration_wall_heading = direction
                self.heading = direction
                return True
        return False

    def stop_exploration_wall_following(self) -> None:
        """Forget the selected exploration-wall side and its heading."""
        self.exploration_wall_heading = None
        self.exploration_wall_side = None
        self.wall_following = False

    def left_wall_directions(self, heading: Direction) -> tuple[Direction, ...]:
        """Return the left-hand wall-following choices from a current heading."""
        return (
            heading.rotate_left(),
            heading,
            heading.rotate_right(),
        )

    def right_wall_directions(self, heading: Direction) -> tuple[Direction, ...]:
        """Return the right-hand wall-following choices from a current heading."""
        return (
            heading.rotate_right(),
            heading,
            heading.rotate_left(),
        )

    def right_hand_directions(self, heading: Direction) -> tuple[Direction, ...]:
        """Return the three clockwise forward wall-following choices."""
        candidates = (
            heading.rotate_right(),
            heading,
            heading.rotate_left(),
        )
        return tuple(dict.fromkeys(candidates))

    def try_move_step(
            self,
            controller: Controller,
            direction: Direction,
            avoid_visited: bool = False,
            build_road: bool = True,
    ) -> bool:
        """Optionally lay a road on an empty tile, then take one legal step."""
        if direction == Direction.CENTRE:
            return False
        current = self.get_cached_position()
        target = self.tile_cache.neighbor(current, direction)
        if target is None:
            return False
        if self.in_launcher_zone(target):
            return False
        if avoid_visited and target in self.visited_tiles:
            return False
        env = self.known_env.get(target)
        if env in (None, Environment.WALL):
            return False
        if self.tile_cache.builder_id_at(target) is not None:
            return False
        building = self.known_buildings.get(target)
        if building is None:
            if not build_road:
                return False
            if not controller.can_build_road(target):
                return False
            committed = (getattr(self, 'siege_plan', None) is not None
                         or getattr(self, 'hijack_plan', None) is not None
                         or self.supply_ore is not None)
            if not committed and not self.scouting_funded:
                return False
            road_id = controller.build_road(target)
            self.tile_cache.remember_building(target, road_id, EntityType.ROAD, self.team)
        elif building[0] == EntityType.MARKER and building[1] == self.team:
            # A persistent Core order can block the sole exit from a narrow
            # spawn corridor.  Friendly markers are free to destroy from the
            # adjacent BuilderBot tile; open it now and step through next turn.
            if not controller.can_destroy(target):
                return False
            controller.destroy(target)
            self.tile_cache.forget_building(target)
            return True
        elif building[0] not in PASSABLE_BUILDINGS:
            return False
        elif building[0] == EntityType.CORE and building[1] != self.team:
            return False
        if not self.is_cached_tile_passable(target) or not controller.can_move(direction):
            return False
        controller.move(direction)
        return True

    def construction_approach(self, site: Position) -> Position | None:
        """Pick a roadable tile from which the builder can act on ``site``."""
        current = self.get_cached_position()
        candidates = [
            pos
            for direction in DIRECTIONS
            if (pos := self.tile_cache.neighbor(site, direction)) is not None
            and self.is_roadable_position(pos)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda pos: current.distance_squared(pos))

    def is_roadable_position(self, pos: Position) -> bool:
        """Return whether an empty or walkable cached tile can support an intruder step."""
        env = self.known_env.get(pos)
        if env in (None, Environment.WALL):
            return False
        if self.in_launcher_zone(pos):
            return False
        occupant = self.tile_cache.builder_id_at(pos)
        if occupant is not None and occupant != self.entity_id:
            return False
        building = self.known_buildings.get(pos)
        return building is None or (
            building[0] in PASSABLE_BUILDINGS
            and (building[0] != EntityType.CORE or building[1] == self.team)
        )

    def unvisited_path_traversable(self, pos: Position) -> bool:
        """Restrict exploratory A* to known roadable cells not visited before."""
        return pos not in self.visited_tiles and self.is_roadable_position(pos)
