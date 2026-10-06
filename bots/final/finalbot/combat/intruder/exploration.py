"""Explore new ground and backtrack between unresolved branches."""

from cambc import Controller, Direction, EntityType, Environment, Position
from finalbot.shared.constants import DIRECTIONS, PASSABLE_BUILDINGS
from finalbot.navigation.combat import a_star_to_any
from finalbot.combat.intruder.settings import _RETURN_TO_CORE_A_STAR_MAX_EXPANSIONS


class IntruderExploration:
    """Uses state initialized by IntruderBot."""

    def has_unvisited_exploration_exit(self, current: Position) -> bool:
        """Return whether an unvisited neighbouring tile can still be explored.

        This deliberately ignores transient restrictions such as a builder on
        the tile, an action cooldown, or an unavailable road build.  Those
        make a step impossible *this turn*, but do not prove that the Intruder
        is in a map dead end and therefore must return to its Core.
        """
        for direction in DIRECTIONS:
            candidate = self.tile_cache.neighbor(current, direction)
            if (
                candidate is None
                or candidate in self.visited_tiles
            ):
                continue
            environment = self.known_env.get(candidate)
            # The unscanned half of a newborn Intruder's first vision is not
            # evidence of a wall.  Wait for its next scan rather than turn
            # around before the tile can be classified.
            if environment == Environment.WALL:
                continue
            building = self.known_buildings.get(candidate)
            if building is None:
                return True
            building_type, building_team = building
            if building_type in PASSABLE_BUILDINGS and (
                building_type != EntityType.CORE or building_team == self.team
            ):
                return True
        return False

    def has_unvisited_exploration_wall_exit(
            self,
            current: Position,
            target: Position | None,
            side: str,
    ) -> bool:
        """Check only the cells that the selected wall bypass can actually try.

        This intentionally keeps the same treatment of unknown cells, builders,
        and action cooldown as ``has_unvisited_exploration_exit``: those are
        transient and should cause a retry.  Unlike that broad check, however,
        it cannot keep a right-side bypass alive because of an unrelated cell
        on the left side of the branch point.
        """
        if target is None:
            return False
        desired = current.direction_to(target)
        if desired == Direction.CENTRE:
            return False
        heading = (
            desired.rotate_right().rotate_right()
            if side == "left"
            else desired.rotate_left().rotate_left()
        )
        directions = (
            self.left_wall_directions(heading)
            if side == "left"
            else self.right_wall_directions(heading)
        )
        for direction in directions:
            candidate = self.tile_cache.neighbor(current, direction)
            if candidate is None or candidate in self.visited_tiles:
                continue
            environment = self.known_env.get(candidate)
            if environment == Environment.WALL:
                continue
            building = self.known_buildings.get(candidate)
            if building is None:
                return True
            building_type, building_team = building
            if (
                building_type == EntityType.MARKER
                and building_team == self.team
            ):
                return True
            if building_type in PASSABLE_BUILDINGS and (
                building_type != EntityType.CORE or building_team == self.team
            ):
                return True
        return False

    def advance_towards_unvisited_target(
            self,
            controller: Controller,
            target: Position | None,
    ) -> bool:
        """Explore toward ``target`` through new cells, then return from a dead end."""
        if target is None:
            return False
        current = self.get_cached_position()
        if self.exploration_wall_side is not None:
            # A wall-following mode ends only when direct forward progress is
            # again available, or when its chosen wall side has no unvisited
            # continuation.  Do not restart A*, switch sides, or take a wide
            # fallback while the wall can still be followed.
            if self.move_towards(
                controller,
                target,
                avoid_visited=True,
                forward_sector_only=True,
                require_closer=True,
            ):
                self.stop_exploration_wall_following()
                return True
            if self.continue_exploration_wall_following(
                controller,
                avoid_visited=True,
            ):
                return True
            self.stop_exploration_wall_following()
            return self.finish_unvisited_movement(controller, target, current)

        # Exploration deliberately stays local even after the enemy Core is
        # confirmed.  A Core tile itself is not traversable, so an A* whose
        # sole goal is that tile can never succeed; retrying its bounded
        # failure each turn exhausts the BuilderBot's CPU budget before the
        # wall-following fallback can act.
        # First probe only the forward sector.
        if self.move_towards(
            controller,
            target,
            avoid_visited=True,
            forward_sector_only=True,
            require_closer=True,
        ):
            return True
        # Choose one side of the obstacle.  Once a side can advance, it is
        # retained across turns until forward progress resumes or it ends.
        if self.start_exploration_wall_following(
            controller,
            target,
            side="left",
            avoid_visited=True,
        ):
            return True
        if self.start_exploration_wall_following(
            controller,
            target,
            side="right",
            avoid_visited=True,
        ):
            return True
        return self.finish_unvisited_movement(controller, target, current)

    def finish_unvisited_movement(
            self,
            controller: Controller,
            target: Position,
            current: Position,
    ) -> bool:
        """Use the broad fallback only after no wall-following route remains."""
        if self.move_towards(
            controller,
            target,
            avoid_visited=True,
            remaining_directional_spectrum=True,
        ):
            return True
        if not self.has_unvisited_exploration_exit(current):
            self.begin_return_from_exploration_dead_end(current)
        return False

    def begin_return_to_core(self, current: Position) -> None:
        """Plan a known-terrain A* route back to the friendly Core after a dead end."""
        if self.core_pos is None or current == self.core_pos:
            return
        search_state = self.a_star_state("return_to_core")
        path = a_star_to_any(
            None,
            current,
            {self.core_pos},
            lambda _controller, pos: self.return_path_traversable(pos),
            self.tile_cache.neighbor,
            movement_directions=DIRECTIONS,
            max_expansions=_RETURN_TO_CORE_A_STAR_MAX_EXPANSIONS,
            state=search_state,
        )
        if search_state.pending:
            return
        if not path:
            return
        self.returning_to_core = True
        self.return_path = path
        self.heading = None

    def begin_return_from_exploration_dead_end(self, current: Position) -> None:
        """Return by A* to the newest left-side branch, then eventually to Core.

        A branch whose right side has already failed is complete, so discard it
        before looking for the next parent.  The first remaining left-side
        branch receives the return route; arriving there retries the right
        side.  This is depth-first exploration without allowing ordinary
        forward movement to revisit historical tiles.
        """
        self.return_branch_target = None
        self.resuming_exploration_branch = False
        self.stop_exploration_wall_following()
        while self.exploration_branch_stack:
            branch_pos, attempted_side = self.exploration_branch_stack[-1]
            if attempted_side == "right":
                self.exploration_branch_stack.pop()
                continue
            if current == branch_pos:
                self.resuming_exploration_branch = True
                return
            search_state = self.a_star_state("return_to_branch")
            path = a_star_to_any(
                None,
                current,
                {branch_pos},
                lambda _controller, pos: self.return_path_traversable(pos),
                self.tile_cache.neighbor,
                movement_directions=DIRECTIONS,
                max_expansions=_RETURN_TO_CORE_A_STAR_MAX_EXPANSIONS,
                state=search_state,
            )
            if search_state.pending:
                return
            if path:
                self.return_branch_target = branch_pos
                self.return_path = path
                self.heading = None
                return
            # The branch cannot be reached through the known terrain, so it
            # cannot be used as a backtracking point.  Try its parent instead.
            self.exploration_branch_stack.pop()
        self.begin_return_to_core(current)

    def return_to_exploration_branch(
            self,
            controller: Controller,
            current: Position,
    ) -> None:
        """Follow the saved A* route to a branch point, allowing revisits."""
        target = self.return_branch_target
        if target is None:
            return
        if current == target:
            self.return_branch_target = None
            self.return_path = []
            self.resuming_exploration_branch = True
            self.resume_exploration_branch(controller, current)
            return
        while self.return_path and current == self.return_path[0]:
            self.return_path.pop(0)
        if not self.return_path:
            self.return_branch_target = None
            self.begin_return_from_exploration_dead_end(current)
            return
        next_pos = self.return_path[0]
        direction = current.direction_to(next_pos)
        if current.distance_squared(next_pos) > 2 or direction == Direction.CENTRE:
            self.return_branch_target = None
            self.begin_return_from_exploration_dead_end(current)
            return
        if self.try_move_step(controller, direction, avoid_visited=False):
            self.return_path.pop(0)
            self.heading = direction
            return
        # A moving builder or fresh obstacle can invalidate a cached segment.
        self.return_branch_target = None
        self.begin_return_from_exploration_dead_end(current)

    def resume_exploration_branch(
            self,
            controller: Controller,
            current: Position,
    ) -> bool:
        """At a left-side branch, explore its untried right-side bypass."""
        self.resuming_exploration_branch = False
        if not self.exploration_branch_stack:
            self.begin_return_to_core(current)
            return False
        branch_pos, attempted_side = self.exploration_branch_stack[-1]
        if current != branch_pos:
            self.begin_return_from_exploration_dead_end(current)
            return False
        if attempted_side != "left":
            self.exploration_branch_stack.pop()
            self.begin_return_from_exploration_dead_end(current)
            return False
        if self.start_exploration_wall_following(
                controller,
                self.destination,
                side="right",
                avoid_visited=True,
                record_branch=False,
        ):
            self.exploration_branch_stack[-1] = (branch_pos, "right")
            return True
        if self.has_unvisited_exploration_wall_exit(
                current,
                self.destination,
                "right",
        ):
            # A cell of this exact right-side bypass may be temporarily blocked
            # by a BuilderBot or an action cooldown.  Retain the branch and
            # retry it rather than discarding the untried side.
            self.resuming_exploration_branch = True
            return False
        self.exploration_branch_stack.pop()
        self.begin_return_from_exploration_dead_end(current)
        return False

    def return_path_traversable(self, pos: Position) -> bool:
        """Allow A* to use known walkable ground while retracing a route to Core."""
        if not self.in_bounds(pos):
            return False
        env = self.known_env.get(pos)
        if env in (None, Environment.WALL):
            return False
        building = self.known_buildings.get(pos)
        return building is None or (
            building[0] in PASSABLE_BUILDINGS
            and (building[0] != EntityType.CORE or building[1] == self.team)
        )

    def return_to_core(self, controller: Controller, current: Position) -> None:
        """Follow the A* route to Core, permitting only this deliberate revisit."""
        if self.core_pos is None:
            self.returning_to_core = False
            self.return_path = []
            return
        if current == self.core_pos:
            self.returning_to_core = False
            self.return_path = []
            self.heading = None
            self.previous_position = None
            return
        while self.return_path and current == self.return_path[0]:
            self.return_path.pop(0)
        if not self.return_path:
            self.returning_to_core = False
            self.begin_return_to_core(current)
            return
        next_pos = self.return_path[0]
        direction = current.direction_to(next_pos)
        if current.distance_squared(next_pos) > 2 or direction == Direction.CENTRE:
            self.returning_to_core = False
            self.begin_return_to_core(current)
            return
        if self.try_move_step(controller, direction, avoid_visited=False):
            self.return_path.pop(0)
            self.heading = direction
            return
        # A moving builder or fresh obstacle may invalidate a cached segment.
        self.returning_to_core = False
        self.begin_return_to_core(current)

    def clear_exploration_branch_state(self) -> None:
        """Discard branch state that belongs to an obsolete exploration goal."""
        self.exploration_branch_stack = []
        self.resuming_exploration_branch = False
        if self.return_branch_target is not None:
            self.return_branch_target = None
            self.return_path = []
