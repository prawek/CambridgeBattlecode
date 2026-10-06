"""Selection and lifecycle of mining and connection jobs."""

from cambc import Controller, EntityType, Environment, GameConstants, Position
from finalbot.economy.mine_security import guard_harvester
from finalbot.shared.constants import (
    CONNECTION_DEFER_NEW_TILES,
    CONNECTION_DEFER_MAX_ROUNDS,
    ORE_TYPES,
    ORTHOGONAL_DIRECTIONS,
    RESOURCE_AXIONITE,
    RESOURCE_TITANIUM,
    HARVESTER_GUARD_LATEST_ROUND,
    IDLE_TARGET_RETRY_ROUNDS,
    SCOUT_PATROL_START_NO_DISCOVERY_ROUNDS,
)


class BuilderJobs:
    """Uses state initialized by BuilderBot."""

    def maybe_select_new_target(self, controller: Controller) -> None:
        """Choose a fresh job when the current non-connection job is complete or absent."""
        if self.target_is_connection:
            return
        current_round = controller.get_current_round()
        need_target = (
            self.harvester_built
            or self.target_ore is not None and self.is_harvester_on_tile(self.target_ore)
            or self.target_ore is None and self.scout_target is None and current_round >= self.next_select_round
            or self.target_ore is None and self.scout_target is not None and self.mineable_ores()
        )
        if not need_target:
            return
        self.select_new_target(controller)
        if self.target_ore is None and self.scout_target is None:
            self.next_select_round = current_round + (
                1 if self.scout_retry_pending else IDLE_TARGET_RETRY_ROUNDS
            )

    def is_ore_eligible(self, ore: Position) -> bool:
        """Return whether this ore type is currently allowed to be mined."""
        resource = self.resource_at(ore)
        return resource == Environment.ORE_TITANIUM or (
            resource == Environment.ORE_AXIONITE and self.titanium_unlocked
        )

    def mineable_ores(self) -> list[Position]:
        """Return eligible, unharvested, non-deferred local and assigned ores."""
        known = self.known_titanium_ores()
        if self.titanium_unlocked:
            known += self.known_axionite_ores()
        known += [ore for ore in self.assigned_ores if ore not in self.known_env]
        return [
            ore
            for ore in known
            if (
                self.is_ore_eligible(ore)
                and not self.is_harvester_on_tile(ore)
                and not self.ore_is_deferred(ore)
                and (self.known_buildings.get(ore) is None
                     or self.known_buildings[ore][0] == EntityType.ROAD)
            )
        ]

    def observed_ores(self) -> list[Position]:
        """Return eligible ore deposits that this builder has directly seen."""
        return [
            pos
            for pos, env in self.known_env.items()
            if pos in self.observed_tiles and env in ORE_TYPES and self.is_ore_eligible(pos)
        ]

    def is_harvester_on_tile(self, pos: Position) -> bool:
        """Report whether the last observation shows a harvester at ``pos``."""
        building = self.known_buildings.get(pos)
        return building is not None and building[0] == EntityType.HARVESTER

    def try_build_nearby_harvester(self, controller: Controller, current: Position) -> bool:
        """Preflight and build a harvester on the best reachable adjacent ore."""
        candidates = [
            ore
            for ore in self.observed_ores()
            if (
                not self.is_harvester_on_tile(ore)
                and current.distance_squared(ore) <= GameConstants.ACTION_RADIUS_SQ
            )
        ]
        candidates.sort(
            key=lambda ore: (
                0 if ore == self.target_ore and not self.target_is_connection else 1,
                self.work_direction_priority(ore),
                current.distance_squared(ore),
            )
        )
        for ore in candidates:
            if self.ore_is_deferred(ore):
                continue
            if not controller.can_build_harvester(ore):
                continue
            # A harvester is useful only with an already planned connection to
            # the core-connected tree.  Planning first also prevents a bot
            # from switching back to exploration immediately after the build.
            if not self.assign_connection_target(controller, current, ore):
                self.defer_ore_for_survey(ore)
                if ore == self.target_ore:
                    self.clear_ore_target()
                continue
            if self.harvester_is_connected(ore):
                harvester_id = controller.build_harvester(ore)
                self.record_harvester_built(ore, harvester_id)
            return True
        return False

    def record_harvester_built(self, ore: Position, harvester_id: int) -> None:
        """Update local state after successfully placing a harvester on ``ore``."""
        self.tile_cache.remember_building(ore, harvester_id, EntityType.HARVESTER, self.team)
        self.harvester_built = True
        self.last_progress_round = self.rounds_alive
        self.harvester_fail_count = 0
        self.skipped_ores.discard(ore)
        self.assigned_ores.pop(ore, None)
        self.reported_ores.pop(ore, None)
        self.deferred_ores_until.pop(ore, None)
        self.pending_network_ores.add(ore)
        if self.connection_starts_new_line:
            self.active_line_tiles.clear()
        self.harvesters_built_count += 1
        self.owned_harvester_tiles.add(ore)
        if self.current_round <= HARVESTER_GUARD_LATEST_ROUND:
            branch_receivers = {
                receiver
                for direction in ORTHOGONAL_DIRECTIONS
                if (receiver := self.tile_cache.neighbor(ore, direction)) is not None
                and receiver in self.conveyor_path_tiles
            }
            self.harvester_guard_tiles = {
                guard
                for direction in ORTHOGONAL_DIRECTIONS
                if (guard := self.tile_cache.neighbor(ore, direction)) is not None
                if (
                    guard not in branch_receivers
                    and self.traversable_for_connection(guard)
                )
            }

    def try_build_harvester_guard(self, controller: Controller, current: Position) -> bool:
        """Protect spare mine ports after its productive branch is connected."""
        return guard_harvester(self, controller, current)

    def defer_ore_for_survey(self, ore: Position) -> None:
        """Temporarily resume exploration until a fully known branch exists."""
        self.deferred_ores_until[ore] = self.current_round + CONNECTION_DEFER_MAX_ROUNDS

    def defer_connection_for_survey(self, ore: Position) -> None:
        """Suspend an impossible branch until exploration reveals a new route."""
        self.pending_network_ores.add(ore)
        self.deferred_connections_observed_count[ore] = max(
            self.deferred_connections_observed_count.get(ore, 0),
            len(self.observed_tiles) + CONNECTION_DEFER_NEW_TILES,
        )
        self.deferred_connections_until_round[ore] = max(
            self.deferred_connections_until_round.get(ore, 0),
            self.current_round + CONNECTION_DEFER_MAX_ROUNDS,
        )

    def connection_is_deferred(self, ore: Position) -> bool:
        """Return whether retrying this disconnected harvester would repeat known work."""
        required_observations = self.deferred_connections_observed_count.get(ore)
        if required_observations is None:
            return False
        if (
            len(self.observed_tiles) >= required_observations
            or self.current_round >= self.deferred_connections_until_round.get(ore, 0)
        ):
            self.deferred_connections_observed_count.pop(ore, None)
            self.deferred_connections_until_round.pop(ore, None)
            return False
        return True

    def ore_is_deferred(self, ore: Position) -> bool:
        """Return whether ore processing is temporarily postponed for scouting."""
        return self.deferred_ores_until.get(ore, -1) >= self.current_round

    def clear_ore_target(self) -> None:
        """Reset the current ore job and its associated path and branch state."""
        if self.target_is_connection and self.unfinished_branch_tiles:
            self.network_memory.abandon_owned_branch(self.known_connected_network())
        self.target_ore = None
        self.target_is_connection = False
        self.path = []
        self.path_index = 0
        self.conveyor_path_tiles = set()
        self.conveyor_directions = {}
        self.bridge_targets = {}
        self.deferred_bridge_sources = set()
        self.bridge_activation_path_index = 0
        self.harvester_guard_tiles.clear()
        self.connection_anchor = None
        self.mode = "scout"

    def assign_ore_target(
            self,
            controller: Controller,
            current: Position,
            ore: Position,
            connecting: bool,
    ) -> bool:
        """Plan movement to an ore deposit or its preflighted conveyor branch."""
        if connecting:
            return self.assign_connection_target(controller, current, ore)

        approaches = self.ore_action_approaches(ore)
        if not approaches:
            return False
        path = self.ore_walk(current, set(approaches))
        if not path and current not in approaches:
            return False
        self.target_ore = ore
        self.target_resource = (
            RESOURCE_TITANIUM
            if self.resource_at(ore) == Environment.ORE_TITANIUM
            else RESOURCE_AXIONITE
        )
        self.target_is_connection = False
        self.scout_target = None
        self.path = path
        self.path_index = 0
        self.conveyor_path_tiles = set()
        self.conveyor_directions = {}
        self.bridge_targets = {}
        self.deferred_bridge_sources = set()
        self.bridge_activation_path_index = 0
        self.connection_anchor = None
        self.mode = "ore"
        return True

    def start_ore_connection(self, controller: Controller, current: Position, ore: Position) -> None:
        """Start or retain responsibility for connecting a harvested ore to the tree."""
        self.pending_network_ores.add(ore)
        if not self.assign_connection_target(controller, current, ore):
            # Keeping an unrouteable connection as the active target traps a
            # builder in a survey loop.  Preserve the pending harvester, but
            # resume ordinary exploration until the local map has changed.
            self.defer_connection_for_survey(ore)
            self.clear_ore_target()

    def replan_active_ore_target(self, controller: Controller) -> bool:
        """Recompute the path for the active ore job after a route becomes invalid."""
        if self.target_ore is None:
            return False
        if self.release_connected_ore_target():
            return False
        ore = self.target_ore
        connecting = self.target_is_connection
        if self.assign_ore_target(controller, self.get_cached_position(), ore, connecting):
            return True
        if connecting:
            self.defer_connection_for_survey(ore)
            self.clear_ore_target()
            return False
        self.defer_ore_for_survey(ore)
        self.clear_ore_target()
        return False

    def release_connected_ore_target(self) -> bool:
        """Clear a connection job that another builder has already completed."""
        if (
            not self.target_is_connection
            or self.target_ore is None
            or not self.is_harvester_on_tile(self.target_ore)
            or not self.harvester_is_connected(self.target_ore)
            or self.ore_needs_capacity_relief(self.target_ore)
        ):
            return False
        self.pending_network_ores.discard(self.target_ore)
        self.deferred_connections_observed_count.pop(self.target_ore, None)
        self.deferred_connections_until_round.pop(self.target_ore, None)
        if self.connection_anchor is not None and self.is_core_receiver_tile(self.connection_anchor):
            self.dedicated_line_committed = True
        self.network_memory.complete_owned_branch()
        self.clear_ore_target()
        return True

    def connection_candidates(self) -> set[Position]:
        """Return harvested ores that still need to join the conveyor tree."""
        candidates = set(self.pending_network_ores)
        network = self.known_connected_network()
        loads = self.known_network_loads(network)
        for ore in self.observed_ores():
            if self.is_harvester_on_tile(ore) and (
                not self.harvester_is_connected(ore)
                or self.ore_needs_capacity_relief(ore, network, loads)
            ):
                candidates.add(ore)
        return {
            ore
            for ore in candidates
            if (
                self.is_harvester_on_tile(ore)
                and self.ore_network_needs_work(ore)
                and not self.connection_is_deferred(ore)
            )
        }

    def select_new_target(self, controller: Controller) -> None:
        """Choose work in priority order: connections, mineable ore, then scouting."""
        self.harvester_built = False
        self.harvester_fail_count = 0
        self.clear_ore_target()
        self.scout_target = None
        self.scout_target_direct = False
        self.scout_retry_pending = False
        current = self.get_cached_position()
        ore_sort_key = lambda pos: (
            0 if pos in self.assigned_ores else 1,
            self.work_direction_priority(pos),
            current.distance_squared(pos),
        )

        repair_plan = self.choose_network_repair_plan(controller, current)
        if repair_plan is not None:
            self.scout_target, self.path = repair_plan
            self.scout_target_direct = False
            self.path_index = 0
            self.mode = "repair"
            return

        for ore in sorted(self.connection_candidates(), key=ore_sort_key):
            if not self.assign_ore_target(controller, current, ore, connecting=True):
                self.defer_connection_for_survey(ore)
                continue
            return

        if len(self.observed_tiles) >= self.ore_retry_observed_count:
            self.ore_retry_observed_count = 0
            for ore in sorted(set(self.mineable_ores()), key=ore_sort_key):
                if self.is_harvester_on_tile(ore) or ore in self.skipped_ores:
                    continue
                if not self.assign_ore_target(controller, current, ore, connecting=False):
                    # The known map does not yet contain a route.  Require
                    # actual new observations before cycling through known ore
                    # targets again; a short round-based delay did not stop
                    # loops on maps with many isolated deposits.
                    self.defer_ore_for_survey(ore)
                    continue
                return

        cleanup_plan = self.choose_abandoned_cleanup_plan(controller, current)
        if cleanup_plan is not None:
            self.scout_target, self.path = cleanup_plan
            self.scout_target_direct = False
            self.path_index = 0
            self.mode = "cleanup"
            return

        scout_plan = self.choose_scout_plan(controller)
        if scout_plan is not None:
            self.scout_route_failures = 0
            self.scout_target, self.path = scout_plan
            self.scout_target_direct = False
            self.path_index = 0
            self.mode = "scout"
            return

        self.scout_route_failures += 1

        patrol_plan = None
        if (
            self.scout_rounds_without_discovery >= SCOUT_PATROL_START_NO_DISCOVERY_ROUNDS
            and self.current_round >= self.scout_cycle_escape_until
        ):
            patrol_plan = self.choose_network_patrol_plan(controller, current)
        if patrol_plan is not None:
            self.scout_route_failures = 0
            self.scout_target, self.path = patrol_plan
            self.scout_target_direct = False
            self.path_index = 0
            self.mode = "patrol"
            return

        # No usable frontier was found, so take one local right-hand step and
        # let the next turn select a fresh frontier from the newly seen tiles.
        step = self.choose_right_hand_scout_step(current)
        if step is not None:
            self.scout_route_failures = 0
            self.scout_target = step
            self.scout_target_direct = False
            self.path = [step]
            self.path_index = 0
            self.mode = "scout"
            return
        self.scout_retry_pending = True
