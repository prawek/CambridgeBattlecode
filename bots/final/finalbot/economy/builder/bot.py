"""Coordinates worker turns and initializes shared worker state."""

from collections import deque
from cambc import Controller, Direction, EntityType, Environment, GameConstants, Position
from finalbot.shared.bot import BaseBot
from finalbot.navigation.construction import ConstructionAccess
from finalbot.combat.defense import defend_economy
from finalbot.economy.refinery import try_refinery
from finalbot.economy.policy import exploration_is_funded
from finalbot.shared.planning_budget import PlanningBudget, SearchMemory
from finalbot.shared.constants import (
    AXIONITE_PIPELINE_ENABLED,
    AXIONITE_TITANIUM_THRESHOLD,
    CONNECTION_STALL_ROUNDS,
    ORE_TARGET_STALL_ROUNDS,
    ORTHOGONAL_DIRECTIONS,
    RESOURCE_TITANIUM,
    SCOUT_CONFIRMED_STALL_KILL_ROUNDS,
    SCOUT_ESCAPE_FAILURE_KILL_ROUNDS,
    SCOUT_KILL_CYCLES,
    SCOUT_KILL_ROUTE_FAILURES,
    SCOUT_KILL_STUCK_ROUNDS,
    SCOUT_NO_DISCOVERY_KILL_ROUNDS,
    SCOUT_REPLAN_STUCK_ROUNDS,
    TRANSPORT_BUSY_OBSERVATION_TURNS,
)
from finalbot.economy.exploration import (
    should_recycle_exhausted_scout,
    should_recycle_stalled_builder,
)
from finalbot.economy.network.memory import NetworkMemory
from finalbot.economy.builder.observation import BuilderObservation
from finalbot.economy.builder.jobs import BuilderJobs
from finalbot.economy.builder.network import BuilderNetwork
from finalbot.economy.builder.routing import BuilderRouting
from finalbot.economy.builder.construction import BuilderConstruction
from finalbot.economy.builder.scouting import BuilderScouting
from finalbot.economy.builder.movement import BuilderMovement


class BuilderBot(
    BuilderObservation,
    BuilderJobs,
    BuilderNetwork,
    BuilderRouting,
    BuilderConstruction,
    BuilderScouting,
    BuilderMovement,
    BaseBot,
):
    """Own worker state and coordinate observation, jobs and construction."""

    def __init__(self, map_width: int, map_height: int) -> None:
        """Initialize exploration memory, mining state, and conveyor planning state."""
        super().__init__(map_width, map_height)
        self.core_pos: Position | None = None
        self.enemy_estimate: Position | None = None
        self.work_direction: Direction | None = None
        self.spawn_direction: Direction | None = None

        # These aliases are indexes maintained by BaseBot.tile_cache, never
        # separate map copies.  All planning below is therefore a dictionary
        # lookup instead of another Controller tile query.
        self.known_env = self.tile_cache.environments
        self.known_buildings = self.tile_cache.buildings
        self.known_conveyor_directions = self.tile_cache.conveyor_directions
        self.known_bridge_targets: dict[Position, Position] = {}
        self.known_bridge_ids: dict[Position, int] = {}
        self.connected_network_cache: set[Position] | None = None
        self.construction_access = ConstructionAccess()
        self.planning_budget = PlanningBudget()
        self.search_memory = SearchMemory(self.planning_budget)
        self.frontier_search_memory = SearchMemory(self.planning_budget)
        self.walk_search_memory = SearchMemory(self.planning_budget)
        self.route_search_memory = SearchMemory(self.planning_budget)
        self.search_network = None
        self._core_tiles_key = None
        self._core_tiles = set()
        self.network_flow_cache_network: set[Position] | None = None
        self.network_flow_cache_harvesters: frozenset[Position] = frozenset()
        self.network_flow_cache_value = 0
        self.network_flow_cache_loads: dict[Position, int] = {}
        self.network_flow_cache_served_harvesters: set[Position] = set()
        self.observed_network_state: dict[
            Position,
            tuple[EntityType, Direction | None, Position | None] | None,
        ] = {}
        self.network_memory = NetworkMemory(TRANSPORT_BUSY_OBSERVATION_TURNS)
        # Compatibility aliases keep the routing code terse while the memory,
        # damage detection, and saturation history live in their own module.
        self.transport_busy_history = self.network_memory.busy_history
        self.network_blueprint = self.network_memory.blueprint
        self.damaged_network_tiles = self.network_memory.damaged_tiles
        # Ownership is the distributed capacity contract.  Bots cannot share
        # Python counters, so a builder may merge only into transport it laid
        # itself; other allied lanes are crossed, never silently overloaded.
        self.owned_network_tiles: set[Position] = set()
        self.active_line_tiles: set[Position] = set()
        self.harvesters_built_count = 0
        self.owned_harvester_tiles: set[Position] = set()
        self.connection_starts_new_line = False
        self.last_plan_starts_new_line = False
        self.observed_tiles = self.tile_cache.observed_tiles
        self.inferred_ores: dict[Position, Environment] = {}
        self.reported_ores: dict[Position, Environment] = {}
        self.assigned_ores: dict[Position, Environment] = {}
        self.scout_frontier: set[Position] = set()
        self.scout_frontier_initialized = False
        self.unreachable_scout_targets: set[Position] = set()
        self.scout_retry_pending = False
        self.permanently_blocked: set[Position] = set()
        self.yield_blocked_until: dict[Position, int] = {}
        self.current_round = 0

        self.target_ore: Position | None = None
        self.target_resource = RESOURCE_TITANIUM
        self.target_is_connection = False
        self.scout_target: Position | None = None
        self.scout_target_direct = False
        self.path: list[Position] = []
        self.path_index = 0
        self.conveyor_path_tiles: set[Position] = set()
        self.conveyor_directions: dict[Position, Direction] = {}
        self.bridge_targets: dict[Position, Position] = {}
        self.deferred_bridge_sources: set[Position] = set()
        self.bridge_activation_path_index = 0
        self.connection_anchor: Position | None = None
        self.dedicated_line_committed = False
        # Tiles laid by this builder for its current, not-yet-connected mine.
        # NetworkMemory keeps their lifecycle across replans: reused tiles
        # remain active while dropped tiles enter an ownership-safe cleanup
        # queue.  Conveyors made by another builder remain immutable.
        self.unfinished_branch_tiles = self.network_memory.unfinished_owned_tiles
        self.abandoned_branch_tiles = self.network_memory.abandoned_owned_tiles
        self.pending_network_ores: set[Position] = set()
        self.harvester_built = False
        self.harvester_fail_count = 0
        self.skipped_ores: set[Position] = set()
        self.deferred_ores_until: dict[Position, int] = {}
        self.deferred_connections_observed_count: dict[Position, int] = {}
        self.deferred_connections_until_round: dict[Position, int] = {}
        self.harvester_guard_tiles: set[Position] = set()
        self.ore_retry_observed_count = 0
        self.next_select_round = 0
        self.replan_after_yield = False
        self.mode = "scout"
        self.titanium_unlocked = False
        self.scouting_funded = True
        self.scout_heading: Direction | None = None
        self.scout_sweep_direction: Direction | None = None

        self.last_pos: Position | None = None
        self.stuck_rounds = 0
        self.rounds_alive = 0
        self.last_progress_round = 0
        self.recent_route: deque[Position] = deque()
        self.recent_route_visits: dict[Position, int] = {}
        self.scout_total_visits: dict[Position, int] = {}
        self.scout_avoid_until: dict[Position, int] = {}
        self.scout_cycle_replan = False
        self.scout_cycle_count = 0
        self.scout_cycle_escape_until = 0
        self.scout_route_failures = 0
        self.scout_rounds_without_discovery = 0
        self.idle_escape_failures = 0

    def run(self, controller: Controller) -> None:
        self.planning_budget.begin_turn(controller)
        try:
            self.run_turn(controller)
        except Exception as error:
            # The game validator permits only built-in exception handlers.
            # Do not hide unrelated errors as a normal planning suspension.
            if not self.planning_budget.pending or str(error) != 'planning slice complete':
                raise
            # Planning is progress, but it is not a movement or build action.
            # Keep the resumable searches; the normal stall limit remains.
            return

    def run_turn(self, controller: Controller) -> None:
        """Execute one turn of scouting, mining, or conveyor construction."""
        if self._scan_turn(controller, read_markers=True):
            return
        self.scouting_funded = exploration_is_funded(controller)
        self.rounds_alive += 1
        self.current_round = controller.get_current_round()
        current = self.get_cached_position()
        if self.last_pos is not None and current == self.last_pos:
            self.stuck_rounds += 1
            if self.target_ore is None and self.scout_target is None:
                # Controller.can_move() can accept a command which loses a
                # simultaneous collision.  Count confirmed positions on the
                # following turn instead of treating the issued command as
                # progress.
                self.idle_escape_failures += 1
            else:
                self.idle_escape_failures = 0
        else:
            self.stuck_rounds = 0
            self.idle_escape_failures = 0
            self.last_progress_round = self.rounds_alive
            self.remember_route_position(current)
        self.last_pos = current

        if self.tile_cache.newly_observed_tiles:
            self.scout_rounds_without_discovery = 0
            self.scout_cycle_count = 0
            self.scout_route_failures = 0
        else:
            self.scout_rounds_without_discovery += 1

        # ``can_move`` describes whether a command may be submitted, not
        # whether it survives simultaneous movement resolution.  Use the
        # position observed on the following turn, together with the last
        # successful build/repair/attack, to recycle a genuinely wedged bot.
        if should_recycle_stalled_builder(
            self.stuck_rounds,
            self.rounds_alive - self.last_progress_round,
            SCOUT_CONFIRMED_STALL_KILL_ROUNDS,
        ):
            controller.self_destruct()
            return

        # A temporary collision or a newly revealed wall should trigger a
        # cheap replan, not kill a useful builder.  Cyclic movement is detected
        # separately because it resets the ordinary "same position" counter.
        if (
            self.target_ore is None
            and self.scout_target is not None
            and (
                (self.scout_cycle_replan and len(self.path) <= 1)
                or self.stuck_rounds >= SCOUT_REPLAN_STUCK_ROUNDS
            )
        ):
            self.cancel_scout_route()

        # Never recycle a builder merely because it failed to retain a target.
        # A TLE also looks like inactivity, and the old 32-round rule therefore
        # created an endless spawn/TLE/self-destruct loop on game 4's map.
        # Genuine exhaustion still has the much longer guarded condition below.
        if self.target_ore is None and self.mode == "scout" and should_recycle_exhausted_scout(
            self.scout_rounds_without_discovery,
            self.stuck_rounds,
            self.scout_route_failures,
            self.scout_cycle_count,
            SCOUT_NO_DISCOVERY_KILL_ROUNDS,
            SCOUT_KILL_STUCK_ROUNDS,
            SCOUT_KILL_ROUTE_FAILURES,
            SCOUT_KILL_CYCLES,
            bool(self.damaged_network_tiles),
        ):
            controller.self_destruct()
            return

        self.observe_tiles(controller)
        if self.core_pos is None:
            self.core_pos = self.find_home_core()
        if self.core_pos is None:
            return
        cached_enemy_core = self.tile_cache.enemy_core_position(self.team)
        if cached_enemy_core is not None:
            self.enemy_estimate = cached_enemy_core
        elif self.enemy_estimate is None:
            self.enemy_estimate = self.tile_cache.position_at(
                self.map_width - 1 - self.core_pos.x,
                self.map_height - 1 - self.core_pos.y,
            )
        if self.work_direction is None:
            self.spawn_direction = self.core_pos.direction_to(current)
        self.read_ore_markers()
        if self.work_direction is None:
            self.work_direction = self.spawn_direction
            if self.work_direction not in ORTHOGONAL_DIRECTIONS:
                self.work_direction = Direction.NORTH
        if self.scout_heading is None:
            self.scout_heading = self.work_direction
            self.scout_sweep_direction = self.work_direction.rotate_right().rotate_right()

        self.titanium_unlocked = (
            AXIONITE_PIPELINE_ENABLED
            and controller.get_global_resources()[0] > AXIONITE_TITANIUM_THRESHOLD
        )
        self.cleanup_abandoned_network(controller, current)
        if defend_economy(self, controller, current):
            return
        if try_refinery(self, controller, current):
            return
        if self.try_repair_nearby_network(controller, current):
            return
        if self.clear_ore_road(controller, current):
            return
        if (
            self.target_is_connection
            and self.target_ore is not None
            and self.rounds_alive - self.last_progress_round >= CONNECTION_STALL_ROUNDS
        ):
            ore = self.target_ore
            self.defer_connection_for_survey(ore)
            self.clear_ore_target()
            self.replan_after_yield = False
        elif (
            self.target_ore is not None
            and not self.target_is_connection
            and self.rounds_alive - self.last_progress_round >= ORE_TARGET_STALL_ROUNDS
        ):
            ore = self.target_ore
            self.defer_ore_for_survey(ore)
            self.clear_ore_target()
            self.replan_after_yield = False
        if not self.target_is_connection and self.try_build_nearby_harvester(controller, current):
            return
        if self.replan_after_yield:
            self.replan_after_yield = False
            if not self.replan_active_ore_target(controller):
                self.select_new_target(controller)
        else:
            self.maybe_select_new_target(controller)
        if self.target_ore is None and self.scout_target is None:
            emergency_step = self.choose_right_hand_scout_step(current)
            if emergency_step is not None:
                self.try_move_scout_step(
                    controller,
                    current,
                    current.direction_to(emergency_step),
                )
            if self.idle_escape_failures >= SCOUT_ESCAPE_FAILURE_KILL_ROUNDS:
                controller.self_destruct()
            return

        if (
            self.target_ore is not None
            and not self.target_is_connection
            and current.distance_squared(self.target_ore) <= GameConstants.ACTION_RADIUS_SQ
        ):
            if self.is_harvester_on_tile(self.target_ore):
                if self.ore_network_needs_work(self.target_ore):
                    self.start_ore_connection(controller, current, self.target_ore)
                else:
                    self.clear_ore_target()
                    self.select_new_target(controller)
                return
            if controller.can_build_harvester(self.target_ore):
                # Do not leave an isolated harvester behind.  Reserve a valid
                # branch to the core-connected conveyor tree *before* placing
                # the harvester, while the ore approach is still known to be
                # reachable.  The next turns build this exact branch.
                if not self.assign_connection_target(controller, current, self.target_ore):
                    self.defer_ore_for_survey(self.target_ore)
                    self.clear_ore_target()
                    self.select_new_target(controller)
                    return
                # Activate the source only once its outlet reaches the core.
                # An idle mine can otherwise supply a hostile battery while
                # this worker is still installing the downstream branch.
                if self.harvester_is_connected(self.target_ore):
                    harvester_id = controller.build_harvester(self.target_ore)
                    self.record_harvester_built(self.target_ore, harvester_id)
                return

            self.harvester_fail_count += 1
            if self.harvester_fail_count >= 5:
                self.skipped_ores.add(self.target_ore)
                self.clear_ore_target()
                self.harvester_fail_count = 0
                self.select_new_target(controller)
                return

        if self.try_build_harvester_guard(controller, current):
            return
        self.follow_path_and_build(controller)
