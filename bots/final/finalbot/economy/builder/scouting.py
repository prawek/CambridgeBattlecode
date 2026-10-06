"""Frontier scoring, scouting routes and network patrol targets."""

from cambc import Controller, EntityType, Position
from finalbot.shared.constants import (
    DIRECTIONS,
    NETWORK_PATROL_MAX_EXPANSIONS,
    SCOUT_DISTANCE_WEIGHT,
    SCOUT_CYCLE_ESCAPE_ROUNDS,
    SCOUT_DEAD_END_AVOID_ROUNDS,
    SCOUT_DEAD_END_PENALTY,
    SCOUT_FORWARD_PROGRESS_WEIGHT,
    SCOUT_INWARD_STEP_PENALTY,
    SCOUT_LATERAL_DEVIATION_WEIGHT,
    SCOUT_NEW_VISION_WEIGHT,
    SCOUT_INVASION_START_ROUND,
    SCOUT_ORE_HINT_PROGRESS_WEIGHT,
    SCOUT_PERSISTENT_REVISIT_PENALTY,
    SCOUT_RETURN_TO_BASE_WEIGHT,
    SCOUT_REVISIT_STEP_PENALTY,
    SCOUT_ROUTE_MEMORY_TILES,
    SCOUT_SECTOR_BONUS,
)
from finalbot.economy.exploration import (
    frontier_search_steps,
    choose_information_gain_step,
    target_approach_progress,
)
from finalbot.navigation.economy import sweep_steps
from finalbot.economy.builder.settings import SCOUT_VISION_OFFSETS


class BuilderScouting:
    """Uses state initialized by BuilderBot."""

    def work_direction_progress(self, pos: Position) -> int:
        """Measure signed progress from the core along this builder's sector direction."""
        if self.core_pos is None or self.work_direction is None:
            return 0
        forward = self.tile_cache.neighbor(self.core_pos, self.work_direction)
        if forward is None:
            return 0
        return (
            (pos.x - self.core_pos.x) * (forward.x - self.core_pos.x)
            + (pos.y - self.core_pos.y) * (forward.y - self.core_pos.y)
        )

    def invasion_scouting_active(self) -> bool:
        """Return whether idle scouts should push beyond their home sectors."""
        return (
            self.current_round >= SCOUT_INVASION_START_ROUND
            and self.core_pos is not None
            and self.enemy_estimate is not None
        )

    def scout_directional_progress(self, pos: Position) -> int:
        """Use the local sector early and the opposing Core after expansion."""
        if self.invasion_scouting_active():
            return target_approach_progress(
                self.core_pos,
                self.enemy_estimate,
                pos,
            )
        return self.work_direction_progress(pos)

    def work_direction_priority(self, pos: Position) -> int:
        """Prefer positions ahead of the core over positions outside the sector."""
        if self.core_pos is None or self.work_direction is None:
            return 0
        return 0 if self.work_direction_progress(pos) > 0 else 1

    def core_distance(self, pos: Position) -> int:
        """Return the Chebyshev distance from the core to ``pos``."""
        if self.core_pos is None:
            return 0
        return max(abs(pos.x - self.core_pos.x), abs(pos.y - self.core_pos.y))

    def work_direction_lateral_offset(self, pos: Position) -> int:
        """Return the perpendicular distance from this builder's sector axis."""
        if self.core_pos is None or self.work_direction is None:
            return 0
        forward = self.tile_cache.neighbor(self.core_pos, self.work_direction)
        if forward is None:
            return 0
        return abs(
            (pos.x - self.core_pos.x) * (forward.y - self.core_pos.y)
            - (pos.y - self.core_pos.y) * (forward.x - self.core_pos.x)
        )

    def remember_route_position(self, pos: Position) -> None:
        """Maintain a bounded recent-route history used to penalize revisits."""
        if self.recent_route and self.recent_route[-1] == pos:
            return
        self.scout_total_visits[pos] = self.scout_total_visits.get(pos, 0) + 1
        if pos in self.recent_route and self.scout_total_visits[pos] >= 3:
            route = list(self.recent_route)
            cycle_start = len(route) - 1 - route[::-1].index(pos)
            cycle = route[cycle_start:]
            # A repeated A-B-A-B oscillation is the most common local failure,
            # so a two-position cycle is already sufficient evidence here.
            if len(cycle) >= 2:
                avoid_until = self.current_round + SCOUT_DEAD_END_AVOID_ROUNDS
                for cycle_pos in cycle:
                    self.scout_avoid_until[cycle_pos] = max(
                        avoid_until,
                        self.scout_avoid_until.get(cycle_pos, 0),
                    )
                if self.target_ore is None:
                    self.scout_cycle_replan = True
                    self.scout_cycle_count += 1
        self.recent_route.append(pos)
        self.recent_route_visits[pos] = self.recent_route_visits.get(pos, 0) + 1
        if len(self.recent_route) <= SCOUT_ROUTE_MEMORY_TILES:
            return
        old_pos = self.recent_route.popleft()
        old_count = self.recent_route_visits[old_pos] - 1
        if old_count == 0:
            del self.recent_route_visits[old_pos]
        else:
            self.recent_route_visits[old_pos] = old_count

    def scout_path_step_cost(self, origin: Position, pos: Position) -> int:
        """Penalize loops while still allowing a real dead-end retreat."""
        cost = self.recent_route_visits.get(pos, 0) * SCOUT_REVISIT_STEP_PENALTY
        cost += min(self.scout_total_visits.get(pos, 0), 6) * SCOUT_PERSISTENT_REVISIT_PENALTY
        if self.scout_avoid_until.get(pos, 0) > self.current_round:
            cost += SCOUT_DEAD_END_PENALTY
        inward_steps = max(0, self.core_distance(origin) - self.core_distance(pos))
        return cost + inward_steps * SCOUT_INWARD_STEP_PENALTY

    def newly_visible_tiles(self, centre: Position) -> int:
        """Count unknown tiles that would enter vision from ``centre``."""
        visible = 0
        for dx, dy in SCOUT_VISION_OFFSETS:
            pos = self.tile_cache.offset(centre, dx, dy)
            if pos is not None and pos not in self.observed_tiles:
                visible += 1
        return visible

    def ore_hint_progress(self, current: Position, candidate: Position) -> int:
        """Measure how much a candidate step approaches an inferred or reported ore hint."""
        if not self.inferred_ores and not self.reported_ores:
            return 0
        current_distance = 10**9
        candidate_distance = 10**9
        for hints in (self.inferred_ores, self.reported_ores):
            for hint in hints:
                current_distance = min(
                    current_distance,
                    max(abs(current.x - hint.x), abs(current.y - hint.y)),
                )
                candidate_distance = min(
                    candidate_distance,
                    max(abs(candidate.x - hint.x), abs(candidate.y - hint.y)),
                )
        return max(0, current_distance - candidate_distance)

    def scout_frontier_pre_score(self, current: Position, candidate: Position) -> tuple[int, int]:
        """Score a frontier cheaply before calculating expensive visibility details."""
        forward_progress = self.scout_directional_progress(candidate)
        in_sector = int(self.work_direction is None or forward_progress > 0)
        returning = 0 if self.invasion_scouting_active() else max(
            0,
            self.core_distance(current) - self.core_distance(candidate),
        )
        distance = max(abs(candidate.x - current.x), abs(candidate.y - current.y))
        return 0, (
            in_sector * SCOUT_SECTOR_BONUS
            + forward_progress * SCOUT_FORWARD_PROGRESS_WEIGHT
            - returning * SCOUT_RETURN_TO_BASE_WEIGHT
            - distance * SCOUT_DISTANCE_WEIGHT
            + self.ore_hint_progress(current, candidate) * SCOUT_ORE_HINT_PROGRESS_WEIGHT
        )

    def scout_frontier_score(self, current: Position, candidate: Position) -> tuple[int, int]:
        """Score a frontier by sector progress, new vision, routing, and ore hints."""
        forward_progress = self.scout_directional_progress(candidate)
        in_sector = int(self.work_direction is None or forward_progress > 0)
        returning = 0 if self.invasion_scouting_active() else max(
            0,
            self.core_distance(current) - self.core_distance(candidate),
        )
        distance = max(abs(candidate.x - current.x), abs(candidate.y - current.y))
        score = (
            in_sector * SCOUT_SECTOR_BONUS
            + forward_progress * SCOUT_FORWARD_PROGRESS_WEIGHT
            + self.newly_visible_tiles(candidate) * SCOUT_NEW_VISION_WEIGHT
            - returning * SCOUT_RETURN_TO_BASE_WEIGHT
            - distance * SCOUT_DISTANCE_WEIGHT
            - (
                0
                if self.invasion_scouting_active()
                else self.work_direction_lateral_offset(candidate)
                * SCOUT_LATERAL_DEVIATION_WEIGHT
            )
            + self.ore_hint_progress(current, candidate) * SCOUT_ORE_HINT_PROGRESS_WEIGHT
            + self.snake_sweep_bias(current, candidate)
        )
        return 0, score

    def scout_frontier_has_known_entry(self, frontier: Position) -> bool:
        """Return whether a frontier touches a known tile the builder can occupy."""
        for direction in DIRECTIONS:
            entry = self.tile_cache.neighbor(frontier, direction)
            if entry is None:
                continue
            if entry in self.known_env and self.traversable_for_planning(None, entry):
                return True
        return False

    def choose_network_patrol_plan(
            self,
            controller: Controller,
            current: Position,
    ) -> tuple[Position, list[Position]] | None:
        """Sweep the known reachable region while watching the transport tree.

        Limiting patrol targets to locally remembered conveyors stranded a
        scout that knew only a short branch: once exploration was complete it
        alternated between the same two tiles.  Known passable terrain gives
        the idle builder long observation loops, while repair jobs still take
        priority in ``select_new_target``.
        """
        path = self.route_search_memory.run(
            ('patrol', current),
            lambda: sweep_steps(
                current, lambda pos: self.traversable_for_ore_path(None, pos),
                self.tile_cache.neighbor, self.scout_total_visits,
                movement_directions=DIRECTIONS,
                max_expansions=NETWORK_PATROL_MAX_EXPANSIONS,
            ),
            version=self.current_round,
        )
        if not path:
            return None
        return path[-1], path

    def choose_network_repair_plan(
            self,
            controller: Controller,
            current: Position,
    ) -> tuple[Position, list[Position]] | None:
        """Route the owning builder back to a rebuildable visible break."""
        repairable = [
            pos
            for pos in self.damaged_network_tiles
            if (
                pos in self.tile_cache.visible_tiles
                and pos not in getattr(self, 'threatened_transport_tiles', ())
                and (
                    self.known_buildings.get(pos) is None
                    or self.known_buildings[pos] == (EntityType.ROAD, self.team)
                )
            )
        ]
        repairable.sort(key=lambda pos: (current.distance_squared(pos), pos.x, pos.y))
        for damaged in repairable:
            approaches = {
                approach
                for direction in DIRECTIONS
                if (approach := self.tile_cache.neighbor(damaged, direction)) is not None
                if (
                    approach != damaged
                    and self.traversable_for_ore_path(None, approach)
                )
            }
            if current in approaches:
                return current, []
            if not approaches:
                continue
            path = self.ore_walk(current, approaches)
            if path:
                return path[-1], path
        return None

    def choose_abandoned_cleanup_plan(
            self,
            controller: Controller,
            current: Position,
    ) -> tuple[Position, list[Position]] | None:
        """Route the owning builder back to an obsolete partial branch."""
        candidates = self.network_memory.actionable_abandoned_tiles(
            self.known_connected_network(),
            self.conveyor_path_tiles,
        )
        for obsolete in sorted(
            candidates,
            key=lambda pos: (current.distance_squared(pos), pos.x, pos.y),
        ):
            approaches = {
                approach
                for direction in DIRECTIONS
                if (approach := self.tile_cache.neighbor(obsolete, direction)) is not None
                if self.traversable_for_ore_path(None, approach)
            }
            if current in approaches:
                return current, []
            if not approaches:
                continue
            path = self.ore_walk(current, approaches)
            if path:
                return path[-1], path
        return None

    def snake_sweep_bias(self, current: Position, candidate: Position) -> int:
        """Bias exploration toward the current lateral leg of the snake sweep."""
        if self.scout_sweep_direction is None:
            return 0
        dx, dy = self.scout_sweep_direction.delta()
        lateral_step = (candidate.x - current.x) * dx + (candidate.y - current.y) * dy
        if lateral_step > 0:
            return 3
        if lateral_step < 0:
            return -3
        return 0

    def scout_step_is_viable(self, pos: Position) -> bool:
        """Return whether a one-step right-hand scouting move may use ``pos``."""
        return (
            self.traversable_for_planning(None, pos)
            and self.tile_cache.builder_id_at(pos) is None
        )

    def scout_a_star_traversable(self, pos: Position, targets: set[Position]) -> bool:
        """Use known terrain and enter unknown space only at a frontier goal."""
        if not self.traversable_for_planning(None, pos):
            return False
        return pos in targets or pos in self.known_env or self.is_core_receiver_tile(pos)

    def choose_right_hand_scout_step(
            self,
            current: Position,
            require_new_vision: bool = False,
    ) -> Position | None:
        """Choose the least-visited useful escape, including a reverse step."""
        if self.work_direction is None:
            return None
        selected = choose_information_gain_step(
            current=current,
            directions=DIRECTIONS,
            neighbor=self.tile_cache.neighbor,
            viable=self.scout_step_is_viable,
            vision_gain=self.newly_visible_tiles,
            total_visits=self.scout_total_visits,
            recent_visits=self.recent_route_visits,
            avoided=lambda pos: self.scout_avoid_until.get(pos, 0) > self.current_round,
            forward_progress=self.scout_directional_progress,
            sweep_bias=self.snake_sweep_bias,
            heading=self.scout_heading,
            require_new_vision=require_new_vision,
        )
        if selected is None:
            return None
        direction, candidate = selected
        self.scout_heading = direction
        return candidate

    def choose_scout_plan(self, controller: Controller) -> tuple[Position, list[Position]] | None:
        """Take a useful local step, then resume a search to the nearest frontier."""
        if not self.scout_frontier and self.known_env and not self.scout_frontier_initialized:
            self.rebuild_scout_frontier()
        current = self.get_cached_position()
        # While new territory is one move away, global A* is wasted work.  A
        # sector-biased least-visited step gives broad snake-like coverage and
        # keeps ordinary scouting comfortably under the 2 ms turn limit.
        local_step = self.choose_right_hand_scout_step(
            current,
            require_new_vision=True,
        )
        if local_step is not None:
            return local_step, [local_step]
        # Repeating a bounded, synchronous A* before the resumable fallback
        # consumed its CPU allowance on every turn. Search all reachable
        # frontiers once; local information-gain steps still choose the sector.
        all_targets = {
            pos for pos in self.scout_frontier
            if pos not in self.observed_tiles and self.traversable_for_planning(None, pos)
        }
        if not all_targets:
            return None
        path = self.frontier_search_memory.run(
            (current, frozenset(all_targets)),
            lambda: frontier_search_steps(
                current, all_targets, self.tile_cache.neighbor,
                lambda pos: self.scout_a_star_traversable(pos, all_targets), DIRECTIONS,
            ),
        )
        return (path[-1], path) if path else None

    def cancel_scout_route(self) -> None:
        """Drop a stalled or cyclic route so target selection runs immediately."""
        if self.scout_cycle_replan:
            self.scout_cycle_escape_until = max(
                self.scout_cycle_escape_until,
                self.current_round + SCOUT_CYCLE_ESCAPE_ROUNDS,
            )
            # The cycle has now been handled by an explicit escape phase.  A
            # later independent loop will be detected again; retaining the
            # lifetime total caused healthy patrollers to be recycled after a
            # dozen already-resolved dead ends.
            self.scout_cycle_count = 0
            self.scout_route_failures = 0
        self.scout_target = None
        self.scout_target_direct = False
        self.path = []
        self.path_index = 0
        self.scout_cycle_replan = False
        self.mode = "scout"
        self.next_select_round = self.current_round

    def reject_scout_target(self, target: Position | None) -> None:
        """Forget an unreachable frontier target and clear its obsolete path."""
        if target is not None:
            self.unreachable_scout_targets.add(target)
            self.scout_frontier.discard(target)
        self.scout_target = None
        self.scout_target_direct = False
        self.path = []
        self.path_index = 0
        self.conveyor_path_tiles = set()
