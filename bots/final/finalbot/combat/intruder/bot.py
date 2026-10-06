"""Coordinates infiltration, siege and ammunition supply turns."""

from cambc import Controller, Direction, Environment, Position
from finalbot.combat.base import CombatBot
from finalbot.economy.policy import exploration_is_funded
from finalbot.shared.spawn_orders import read_spawn_assignment
from finalbot.combat.cycle_escape import escape_cycle
from finalbot.combat.assault import try_siege
from finalbot.combat.hijack import try_hijack
from finalbot.combat.intruder.observation import IntruderObservation
from finalbot.combat.intruder.exploration import IntruderExploration
from finalbot.combat.intruder.movement import IntruderMovement
from finalbot.combat.intruder.launching import IntruderLaunching
from finalbot.combat.intruder.targeting import IntruderTargeting
from finalbot.combat.intruder.supply_planning import IntruderSupplyPlanning
from finalbot.combat.intruder.supply_construction import IntruderSupplyConstruction


class IntruderBot(
    IntruderObservation,
    IntruderExploration,
    IntruderMovement,
    IntruderLaunching,
    IntruderTargeting,
    IntruderSupplyPlanning,
    IntruderSupplyConstruction,
    CombatBot,
):
    """Own raid state and coordinate exploration, siege and supply."""

    def __init__(self, map_width: int, map_height: int) -> None:
        """Initialize infiltration, launcher, and supply-line state."""
        super().__init__(map_width, map_height)
        self.known_env = self.tile_cache.environments
        self.known_buildings = self.tile_cache.buildings
        self.core_pos: Position | None = None
        # One target position throughout the role: first a symmetry guess,
        # then the confirmed opposing Core.  Only its certainty is separate.
        self.destination: Position | None = None
        self.destination_is_confirmed_core = False

        self.mode = "infiltrate"
        self.scouting_funded = True
        self.heading: Direction | None = None
        self.wall_following = False
        self.exploration_wall_heading: Direction | None = None
        self.exploration_wall_side: str | None = None
        self.last_position: Position | None = None
        self.previous_position: Position | None = None
        self.enemy_launcher_positions: set[Position] = set()
        # Exploration never revisits a tile.  The only exception is the
        # explicit A* route back to a wall-bypass branch point, or eventually
        # to the friendly Core after every branch has been exhausted.
        self.visited_tiles: set[Position] = set()
        # Each entry is the point at which a wall bypass began and the side
        # already explored from it.  A dead end on the left returns here to
        # explore the right; a dead end on the right pops the entry.
        self.exploration_branch_stack: list[tuple[Position, str]] = []
        self.return_branch_target: Position | None = None
        self.resuming_exploration_branch = False
        self.returning_to_core = False
        self.return_path: list[Position] = []
        self.waiting_launcher_origin: Position | None = None
        self.waiting_launcher_round: int | None = None
        self.waiting_launch_marker: Position | None = None

        self.gunner_site: Position | None = None
        self.gunner_direction: Direction | None = None
        self.rejected_gunner_sites: set[Position] = set()
        self.gunner_id: int | None = None
        self.gunner_site_candidates: list[tuple[Position, Direction, Position]] = []
        self.gunner_site_candidate_cursor = 0
        self.gunner_search_origin: Position | None = None
        self.gunner_search_destination: Position | None = None

        self.owned_supply_tiles: set[Position] = set()
        self.owned_supply_ores: set[Position] = set()
        self.supply_ore: Position | None = None
        # The only supply route is ordered from the Gunner to the selected
        # ore entry.  The Intruder walks this exact sequence, building each
        # transport tile before it proceeds farther from the Gunner.
        self.supply_path: list[Position] = []
        # A crossing maps its Gunner-side source to its ore-side landing.
        # The physical Bridge is built on the landing and outputs back to the
        # source, so resources still flow from the ore to the Gunner.
        self.supply_bridge_crossings: dict[Position, Position] = {}
        self.pending_supply_bridge: Position | None = None
        self.supply_directions: dict[Position, Direction] = {}
        self.supply_bridge_targets: dict[Position, Position] = {}
        self.supply_index = 0
        # Bridge targets are not exposed by TileCache because only the
        # Intruder's supply planner needs them.  Cache canonical endpoints so
        # an already built bridge can be used as part of a new supply route.
        self.known_bridge_targets: dict[Position, Position] = {}
        self.known_bridge_ids: dict[Position, int] = {}
        self.unavailable_titanium: set[Position] = set()
        self.supply_plan_candidates: list[Position] | None = None
        self.supply_plan_cursor = 0
        self.deferred_supply_candidates: list[Position] = []
        # While the complete Gunner-to-ore route is still outside vision,
        # keep approaching one ore entry.  Re-selecting the nearest entry on
        # every turn can bounce between two adjacent entries around a mine.
        self.supply_exploration_entry: Position | None = None
        self.supply_exploring_back_to_gunner = False
        # Before a Ti deposit is visible, scouting chooses a reachable map
        # frontier.  A bounded A* can prove that a nearby frontier is cut off
        # by known terrain; retain that result so the next turn tries another
        # frontier rather than repeating the same failed search forever.
        self.failed_supply_search_frontiers: set[Position] = set()
        self.supply_search_target: Position | None = None
        # Once a supply route exists, newly scanned deposits are considered
        # incrementally.  This lets the Intruder abandon an early, distant
        # discovery for a genuinely cheaper route without repeating A* for
        # every already-known deposit each turn.
        self.supply_seen_ores: set[Position] = set()
        self.supply_replan_candidates: list[Position] = []
        self.supply_plan_cost: int | None = None

    @staticmethod
    def claims_spawn(controller: Controller) -> bool:
        """Return whether the nearby core marker designates this newborn intruder."""
        return read_spawn_assignment(controller)[0] is True

    def run(self, controller: Controller) -> None:
        """Execute one cached turn of infiltration, gunner construction, or supply."""
        if self._scan_turn(controller):
            return
        self.scouting_funded = exploration_is_funded(controller)
        # Confirming a symmetry schedules the historical terrain backfill and
        # infers the opposite Core.  Do not immediately follow it with Gunner
        # planning, whose engine validation calls can otherwise turn this
        # already expensive transition into a TLE.
        current = self.get_cached_position()
        self.visited_tiles.update((current,))
        self.draw_visited_tile_indicators(controller, current)
        self.remember_position(current)
        if self.core_pos is None:
            self.core_pos = self.find_friendly_core()
        if self.core_pos is None:
            return

        self.update_enemy_knowledge()
        self.refresh_enemy_launchers()
        self.refresh_known_bridge_targets(controller)
        if escape_cycle(self, controller, current):
            return
        if self.clear_cheap_enemy_building(controller, current):
            self.draw_goal_indicator(controller, current)
            return
        if self.wait_for_launcher(controller, current):
            self.draw_goal_indicator(controller, current)
            return
        if try_hijack(self, controller, current):
            return
        if try_siege(self, controller, current):
            self.draw_goal_indicator(controller, current)
            return
        if self.return_branch_target is not None:
            self.mode = "return_to_exploration_branch"
            self.return_to_exploration_branch(controller, current)
            self.draw_goal_indicator(controller, current)
            return
        if self.resuming_exploration_branch:
            self.mode = "resume_exploration_branch"
            self.resume_exploration_branch(controller, current)
            self.draw_goal_indicator(controller, current)
            return
        if self.returning_to_core:
            self.mode = "return_to_core"
            self.return_to_core(controller, current)
            self.draw_goal_indicator(controller, current)
            return
        if self.gunner_id is None:
            self.mode = "infiltrate"
            self.infiltrate(controller, current)
            self.draw_goal_indicator(controller, current)
            return

        self.mode = "supply_gunner"
        self.supply_gunner(controller, current)
        self.draw_goal_indicator(controller, current)

    def infiltrate(self, controller: Controller, current: Position) -> None:
        """Explore toward a Core hypothesis, then establish a forward Gunner."""
        if not self.destination_is_confirmed_core:
            self.advance_towards_unvisited_target(controller, self.destination)
            return
        # A geometrically good gunner with no known ammunition source is a
        # sunk cost. Survey the far side of the core before committing it.
        ores = [p for p, env in self.known_env.items()
                if env == Environment.ORE_TITANIUM
                and p.distance_squared(self.destination) <= 85
                and p not in self.tile_cache.visible_tiles
                and getattr(self, 'deferred_siege_ores', {}).get(p, 0) <= controller.get_current_round()
                and self.is_available_supply_ore(p)]
        if ores:
            ore = min(ores, key=lambda p: current.distance_squared(p))
            self.siege_probe_ore = ore
            approach = self.construction_approach(ore)
            if approach is not None:
                self.advance_towards_revisitable_target(controller, approach)
            else:
                self.advance_towards_unvisited_target(controller, ore)
            return
        probes = [self.tile_cache.offset(self.destination, dx, dy)
                  for dx, dy in ((0, -5), (5, -3), (5, 3), (0, 5), (-5, 3), (-5, -3))]
        probes = [p for p in probes if p is not None and p not in self.visited_tiles
                  and self.known_env.get(p) != Environment.WALL]
        if probes:
            probe = min(probes, key=lambda p: current.distance_squared(p))
            self.advance_towards_revisitable_target(controller, probe)
            return
        # The original bridge-aware supply planner remains available once
        # local direct-feed positions have genuinely been exhausted.
        self.build_forward_gunner(controller, current)

    def draw_goal_indicator(self, controller: Controller, current: Position) -> None:
        """Draw a red replay line from this intruder to its current destination."""
        if self.return_branch_target is not None:
            target = self.return_branch_target
        elif self.returning_to_core:
            target = self.core_pos
        elif self.gunner_id is not None:
            # Until a Ti deposit has entered the cache, ``destination`` still
            # names the enemy Core.  Showing it here made a stationary supply
            # scout look as though it was trying to walk back into the Core.
            target = self.supply_ore or self.supply_search_target or self.gunner_site
        else:
            target = self.destination
        if target is not None:
            controller.draw_indicator_line(current, target, 255, 0, 0)

    def remember_position(self, current: Position) -> None:
        """Keep one previous tile for retreating from a launcher dead end."""
        if self.last_position is not None and current != self.last_position:
            self.previous_position = self.last_position
        self.last_position = current

    def draw_visited_tile_indicators(
            self,
            controller: Controller,
            current: Position,
    ) -> None:
        """Draw only this turn's position without making debug work grow forever.

        Replay indicators are cosmetic, while a BuilderBot has a 2 ms turn
        budget.  Re-emitting one dot for every historical step became more
        expensive every round and was enough to starve the supply planner just
        after it had built a forward Gunner.
        """
        controller.draw_indicator_dot(current, 255, 0, 0)
