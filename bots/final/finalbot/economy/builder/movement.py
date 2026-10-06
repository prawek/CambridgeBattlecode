"""Walking, road preparation and yielding at worker collisions."""

from cambc import Controller, Direction, EntityType, Environment, Position
from finalbot.shared.constants import (
    DIRECTIONS,
    PASSABLE_BUILDINGS,
    YIELD_ROUTE_AVOID_ROUNDS,
)
from finalbot.economy.exploration import is_static_step_obstacle
from finalbot.navigation.economy import a_star_steps


class BuilderMovement:
    """Uses state initialized by BuilderBot."""

    def ore_walk(self, current: Position, targets: set[Position]) -> list[Position]:
        """Finish a known-terrain route over as many turns as it needs."""
        if current in targets:
            return []
        blocked = frozenset(
            pos for pos, building in self.known_buildings.items()
            if building is not None and (
                building[0] not in PASSABLE_BUILDINGS
                or (building[0] == EntityType.CORE and building[1] != self.team)
            )
        )
        version = (len(self.known_env), blocked, frozenset(self.permanently_blocked),
                   frozenset(self.active_yield_blocked_tiles()))
        key = ('ore', current, frozenset(targets))
        path = self.route_search_memory.run(
            key,
            lambda: a_star_steps(
                None, current, targets, self.traversable_for_ore_path,
                self.tile_cache.neighbor, movement_directions=DIRECTIONS,
            ),
            version=version,
        )
        # Buildings can change while the search is suspended. Reject a stale
        # route before assigning it; transient builder occupancy is handled
        # by the movement/yield logic instead of splitting this terrain graph.
        if any(not self.traversable_for_ore_path(None, pos) for pos in path):
            self.route_search_memory.jobs.pop(key, None)
            return []
        return path

    def traversable_for_planning(self, _controller: Controller | None, pos: Position) -> bool:
        """Return whether a builder may move through ``pos`` while planning a path."""
        if (
            not self.in_bounds(pos)
            or pos in self.permanently_blocked
            or self.is_yield_blocked(pos)
        ):
            return False
        env = self.known_env.get(pos)
        if env == Environment.WALL:
            return False
        building = self.known_buildings.get(pos)
        return building is None or (
            building[0] in PASSABLE_BUILDINGS
            and (building[0] != EntityType.CORE or building[1] == self.team)
        )

    def traversable_for_ore_path(self, controller: Controller | None, pos: Position) -> bool:
        """Allow ore-route A* to use only already observed passable cells.

        A deposit may appear on the edge of vision.  Its approach and every
        intermediate route tile must nevertheless be known: otherwise A*
        treats an unknown cell as empty and expands into unexplored terrain.
        Scouting keeps using ``traversable_for_planning`` so it can still take
        its deliberate one-step move into a new frontier cell.
        """
        return pos in self.known_env and self.traversable_for_planning(controller, pos)

    def follow_direct_scout_target(self, controller: Controller, current: Position) -> None:
        """Advance straight to a frontier and use the right-hand rule around a block."""
        target = self.scout_target
        if target is None:
            self.scout_target_direct = False
            return
        if current == target:
            self.scout_target = None
            self.scout_target_direct = False
            return

        direct_direction = current.direction_to(target)
        if self.try_move_scout_step(controller, current, direct_direction):
            return

        # The direct line is no longer usable.  Keep the same target, but
        # inspect the immediate clockwise detour before giving it up.
        self.scout_heading = direct_direction
        detour = self.choose_right_hand_scout_step(current)
        if detour is None:
            self.reject_scout_target(target)
            self.scout_retry_pending = True
            return
        detour_direction = current.direction_to(detour)
        if not self.try_move_scout_step(controller, current, detour_direction):
            self.scout_retry_pending = True

    def try_move_scout_step(
            self,
            controller: Controller,
            current: Position,
            direction: Direction,
    ) -> bool:
        """Prepare and take one legal scouting step in ``direction`` if possible."""
        if direction == Direction.CENTRE:
            return False
        next_pos = self.tile_cache.neighbor(current, direction)
        if next_pos is None:
            return False
        if not self.is_cached_tile_passable(next_pos):
            self.try_prepare_tile(controller, next_pos)
        if not controller.can_move(direction):
            return False
        controller.move(direction)
        self.scout_heading = direction
        return True

    def try_prepare_tile(self, controller: Controller, target: Position) -> None:
        """Prepare a blocked next tile by building a road or branch conveyor."""
        if (
            self.target_is_connection
            and target in self.conveyor_path_tiles
            and not self.bridge_build_is_deferred(target)
        ):
            self.ensure_tree_conveyor(controller, target)
            return
        if self.tile_cache.builder_id_at(target) is not None:
            return
        if controller.can_build_road(target):
            committed = (self.target_ore is not None or self.mode == 'repair'
                         or getattr(self, 'refinery_project', None) is not None)
            if not committed and not self.scouting_funded:
                return
            road_id = controller.build_road(target)
            self.tile_cache.remember_building(target, road_id, EntityType.ROAD, self.team)
            self.last_progress_round = self.rounds_alive
            return
        # can_build_road is also false while resources/actions are temporarily
        # unavailable.  Only immutable terrain or a durable incompatible
        # building belongs in the permanent obstacle set.
        env = self.known_env.get(target)
        building = self.known_buildings.get(target)
        if (
            env == Environment.WALL
            or (
                building is not None
                and building[0] not in PASSABLE_BUILDINGS
                and building[0] != EntityType.BUILDER_BOT
            )
        ):
            self.mark_staticly_blocked(target)

    def replan_after_blocked_step(self, controller: Controller, target: Position) -> None:
        """Yield or recompute the active job when the next path tile is blocked."""
        # is_tile_passable() is also false while another builder occupies an
        # otherwise usable road.  For allied builders, entity IDs reflect spawn
        # order: the later builder yields, while the earlier one keeps priority.
        blocking_id = self.tile_cache.builder_id_at(target)
        if blocking_id is not None:
            if self.tile_cache.entity_team(blocking_id) == self.team:
                if self.entity_id is not None and blocking_id < self.entity_id:
                    self.yield_to_higher_priority_builder(controller, target)
                return
            self.schedule_replan_after_yield()
            return
        env = self.known_env.get(target)
        building = self.known_buildings.get(target)
        cached_passable_building = (
            building is not None
            and building[0] in PASSABLE_BUILDINGS
            and (building[0] != EntityType.CORE or building[1] == self.team)
        )
        if not is_static_step_obstacle(
            env == Environment.WALL,
            building is not None,
            cached_passable_building,
        ):
            # The step can be temporarily unaffordable or the action may have
            # been consumed; a friendly transport can also be momentarily
            # occupied between this bot's scan and action.  Preserve both as
            # traversable and let the ordinary stall logic replan.
            return
        self.mark_staticly_blocked(target)
        if self.replan_active_ore_target(controller):
            return
        if self.target_is_connection:
            self.replan_after_yield = True
            return
        if self.scout_target is not None:
            self.reject_scout_target(self.scout_target)
        else:
            self.path = []
            self.path_index = 0
        self.select_new_target(controller)

    def yield_to_higher_priority_builder(self, controller: Controller, blocking_pos: Position) -> None:
        """Move aside for an earlier allied builder and schedule a fresh route."""
        current = self.get_cached_position()
        self.yield_blocked_until[blocking_pos] = self.current_round + YIELD_ROUTE_AVOID_ROUNDS
        retreat_positions: list[Position] = []
        seen: set[Position] = set()
        for pos in reversed(self.recent_route):
            if pos == current or pos == blocking_pos or pos in seen:
                continue
            seen.add(pos)
            if current.distance_squared(pos) <= 2:
                retreat_positions.append(pos)

        # A newly spawned bot may not have route history yet.  In that case use
        # any free neighbouring road, preferring a step away from the blocker.
        route_history = set(self.recent_route)
        fallback_positions = [
            candidate
            for direction in DIRECTIONS
            if (candidate := self.tile_cache.neighbor(current, direction)) is not None
            if (
                candidate != blocking_pos
                and candidate not in route_history
            )
        ]
        fallback_positions.sort(
            key=lambda pos: pos.distance_squared(blocking_pos),
            reverse=True,
        )

        for retreat_pos in fallback_positions + retreat_positions:
            direction = current.direction_to(retreat_pos)
            if direction == Direction.CENTRE or not controller.can_move(direction):
                continue
            controller.move(direction)
            self.schedule_replan_after_yield()
            return

        # Even when there is no immediately passable retreat tile, discard the
        # stale route so the next turn can attempt a different route or goal.
        self.schedule_replan_after_yield()

    def schedule_replan_after_yield(self) -> None:
        """Discard the current route so the next turn can plan around a conflict."""
        if self.target_ore is not None:
            self.path = []
            self.path_index = 0
            self.conveyor_path_tiles = set()
            self.conveyor_directions = {}
            self.bridge_targets = {}
            self.deferred_bridge_sources = set()
            self.bridge_activation_path_index = 0
            self.connection_anchor = None
            self.replan_after_yield = True
            return
        self.scout_target = None
        self.path = []
        self.path_index = 0
        self.conveyor_path_tiles = set()
        self.conveyor_directions = {}
        self.bridge_targets = {}
        self.deferred_bridge_sources = set()
        self.bridge_activation_path_index = 0
        self.connection_anchor = None
        self.replan_after_yield = True

    def active_yield_blocked_tiles(self) -> set[Position]:
        """Return tiles still temporarily avoided after yielding to an ally."""
        return {
            pos
            for pos, expires_on_round in self.yield_blocked_until.items()
            if self.current_round <= expires_on_round
        }

    def is_yield_blocked(self, pos: Position) -> bool:
        """Return whether ``pos`` remains temporarily excluded after yielding."""
        return self.yield_blocked_until.get(pos, -1) >= self.current_round

    def mark_staticly_blocked(self, target: Position) -> None:
        """Remember a tile as permanently unusable when its obstacle is static."""
        env = self.known_env.get(target)
        building = self.known_buildings.get(target)
        if env != Environment.WALL:
            if building is None or building[0] in PASSABLE_BUILDINGS:
                return
        self.permanently_blocked.add(target)
