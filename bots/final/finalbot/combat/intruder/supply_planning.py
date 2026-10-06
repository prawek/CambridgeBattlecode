"""Choose an ammunition source and preserve its resumable route plan."""

from cambc import Controller, Direction, EntityType, Environment, Position
from finalbot.shared.constants import DIRECTIONS, ORTHOGONAL_DIRECTIONS
from finalbot.navigation.combat import a_star_from_any_with_bridges, a_star_to_any
from finalbot.combat.intruder.settings import (
    _CLEARABLE_WALKABLE_BUILDINGS,
    _SUPPLY_BRIDGE_SEARCH_EXPANSIONS,
    _SUPPLY_BRIDGE_STEP_COST,
    _SUPPLY_CONVEYOR_STEP_COST,
    _SUPPLY_ROUTE_PLANS_PER_TURN,
    _SUPPLY_SEARCH_EXPANSIONS,
)


class IntruderSupplyPlanning:
    """Uses state initialized by IntruderBot."""

    def is_protected_transport(self, pos: Position) -> bool:
        """Only repurpose this intruder's own allied transport, never a mine lane."""
        building = self.known_buildings.get(pos)
        return (
            building is not None
            and building[1] == self.team
            and building[0] in {
                EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR,
                EntityType.SPLITTER, EntityType.BRIDGE,
            }
            and pos not in self.owned_supply_tiles
        )

    def is_available_supply_ore(self, pos: Position) -> bool:
        building = self.known_buildings.get(pos)
        return (
            building is None
            or building[1] != self.team
            or pos in self.owned_supply_ores
        )

    def select_supply_plan(self) -> bool:
        """Select the closest usable Ti deposit without unbounded route work."""
        if self.gunner_site is None or self.gunner_direction is None:
            return False
        if self.supply_plan_candidates is None:
            self.supply_plan_candidates = sorted(
                (
                    pos
                    for pos, env in self.known_env.items()
                    if env == Environment.ORE_TITANIUM and self.is_available_supply_ore(pos)
                    and pos not in self.unavailable_titanium
                ),
                key=lambda pos: (pos.distance_squared(self.gunner_site), pos.y, pos.x),
            )
            self.supply_seen_ores.update(self.supply_plan_candidates)
            self.supply_plan_cursor = 0
            self.deferred_supply_candidates = []

        attempts = 0
        while (
            self.supply_plan_cursor < len(self.supply_plan_candidates)
            and attempts < _SUPPLY_ROUTE_PLANS_PER_TURN
        ):
            ore = self.supply_plan_candidates[self.supply_plan_cursor]
            self.supply_plan_cursor += 1
            attempts += 1
            plan = self.plan_supply_route(ore)
            if plan is not None:
                self.store_supply_plan(ore, plan)
                return True
            if self.a_star_state("supply_route").pending:
                # Keep this candidate at the head of the queue so the next
                # turn continues its retained A* frontier.
                self.supply_plan_cursor -= 1
                return False
            self.deferred_supply_candidates.append(ore)

        if self.supply_plan_cursor < len(self.supply_plan_candidates):
            return False
        if self.deferred_supply_candidates:
            # Terrain which has not entered the cache cannot yet have a valid
            # A* route.  Keep the nearest deposit as a temporary exploration
            # target after the bounded attempts have all failed.
            ore = self.deferred_supply_candidates[0]
            self.supply_ore = ore
            self.supply_path = []
            self.supply_bridge_crossings = {}
            self.pending_supply_bridge = None
            self.supply_directions = {}
            self.supply_bridge_targets = {}
            self.supply_index = 0
            self.supply_exploration_entry = None
            self.supply_exploring_back_to_gunner = False
            self.supply_plan_candidates = None
            self.supply_plan_cursor = 0
            self.deferred_supply_candidates = []
            return True
        self.supply_plan_candidates = None
        return False

    def reconsider_supply_plan(self) -> bool:
        """Replace an active route when a newly seen Ti deposit is cheaper.

        The first visible deposit is often only a provisional choice.  A
        supply branch can encounter a much closer deposit while travelling
        toward it, so compare each *new* usable deposit with the saved A*
        cost.  The candidate queue and one-search limit keep this from
        turning map exploration into an unbounded per-turn route search.
        """
        if self.gunner_site is None or self.supply_ore is None:
            return False

        known_ores = {
            pos
            for pos, env in self.known_env.items()
            if env == Environment.ORE_TITANIUM and self.is_available_supply_ore(pos)
            and pos not in self.unavailable_titanium
        }
        new_ores = known_ores - self.supply_seen_ores
        if new_ores:
            self.supply_seen_ores.update(new_ores)
            self.supply_replan_candidates.extend(sorted(
                new_ores,
                key=lambda pos: (pos.distance_squared(self.gunner_site), pos.y, pos.x),
            ))

        if not self.supply_replan_candidates:
            return False

        # A bridge-aware search can be expensive.  One bounded attempt per
        # turn is enough to react immediately to a single newly seen deposit
        # while retaining the same timing guarantee as initial planning.
        ore = self.supply_replan_candidates.pop(0)
        plan = self.plan_supply_route(ore)
        if plan is None:
            if self.a_star_state("supply_route").pending:
                self.supply_replan_candidates.insert(0, ore)
            return False
        if self.supply_plan_cost is not None and plan[3] >= self.supply_plan_cost:
            return False

        self.store_supply_plan(ore, plan)
        return True

    def store_supply_plan(
            self,
            ore: Position,
            plan: tuple[
                list[Position],
                dict[Position, Direction],
                dict[Position, Position],
                int,
            ],
    ) -> None:
        """Persist one Gunner-to-ore A* route and reset its build cursor."""
        path, directions, bridge_targets, cost = plan
        self.supply_ore = ore
        self.supply_seen_ores.update((ore,))
        self.supply_plan_cost = cost
        self.supply_path = path
        self.supply_bridge_crossings = {
            source: target for target, source in bridge_targets.items()
        }
        self.pending_supply_bridge = None
        self.supply_directions = directions
        self.supply_bridge_targets = bridge_targets
        self.supply_index = 0
        self.supply_plan_candidates = None
        self.supply_plan_cursor = 0
        self.deferred_supply_candidates = []
        self.supply_exploration_entry = None
        self.supply_exploring_back_to_gunner = False
        self.supply_search_target = None

    def explore_supply_route(self, controller: Controller, current: Position) -> None:
        """Extend known supply terrain toward an ore entry without wall loops.

        A visible deposit is useful evidence even when the complete
        Gunner-to-ore A* route has not entered the cache yet.  The previous
        fallback walked back toward the Gunner and delegated its movement to
        generic wall following.  At a wall this can produce an endless loop
        while the deposit is already beside the Intruder.  Instead, approach
        a known usable neighbour of the deposit, or the closest known supply
        frontier leading to it.  A subsequent turn retries the full planner
        and then lays the real conveyors.
        """
        target = self.supply_exploration_entry
        if target is None or not self.is_supply_tile(target):
            target = (
                self.supply_route_frontier(current)
                if self.supply_exploring_back_to_gunner
                else self.supply_exploration_target(current)
            )
            self.supply_exploration_entry = target
        if target is None:
            return
        if current == target:
            # Reaching an ore entry does not mean that the Gunner-to-ore path
            # is known.  Continue revealing terrain back toward the Gunner;
            # otherwise a failed A* plan selects this same entry every turn
            # and leaves the Intruder stationary beside the deposit.
            self.supply_exploring_back_to_gunner = True
            target = self.supply_route_frontier(current)
            self.supply_exploration_entry = target
            if target is None:
                return

        search_state = self.a_star_state("supply_exploration")
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
            return
        if path:
            self.try_move_step(
                controller,
                current.direction_to(path[0]),
                build_road=True,
            )
            return

        # A partial cache may not yet contain a complete route.  Probe only
        # steps which move closer to the ore-side target; unlike
        # ``move_towards`` this never activates wall following or retreats to
        # the Gunner.
        self.move_towards(
            controller,
            target,
            forward_sector_only=True,
            require_closer=True,
        )

    def supply_route_frontier(self, current: Position) -> Position | None:
        """Pick an unseen-map frontier which tends back toward the Gunner."""
        if self.gunner_site is None:
            return None
        frontiers = [
            pos
            for pos in self.known_env
            if pos != current
            and pos not in self.visited_tiles
            and self.is_roadable_position(pos)
            and any(
                neighbor is not None and neighbor not in self.known_env
                for direction in DIRECTIONS
                if (neighbor := self.tile_cache.neighbor(pos, direction)) is not None
            )
        ]
        if not frontiers:
            return None
        gunner_side = [
            pos
            for pos in frontiers
            if pos.distance_squared(self.gunner_site)
            < current.distance_squared(self.gunner_site)
        ]
        candidates = gunner_side or frontiers
        return min(
            candidates,
            key=lambda pos: (
                current.distance_squared(pos),
                pos.distance_squared(self.gunner_site),
                pos.y,
                pos.x,
            ),
        )

    def supply_exploration_target(self, current: Position) -> Position | None:
        """Choose the nearest known supply entry or frontier for ``supply_ore``."""
        ore = self.supply_ore
        if ore is None:
            return None

        entries = [
            entry
            for direction in ORTHOGONAL_DIRECTIONS
            if (entry := self.tile_cache.neighbor(ore, direction)) is not None
            and self.is_supply_tile(entry)
        ]
        if entries:
            return min(
                entries,
                key=lambda pos: (current.distance_squared(pos), pos.y, pos.x),
            )

        frontiers = [
            pos
            for pos in self.known_env
            if self.is_supply_tile(pos)
            and any(
                neighbor is not None and self.known_env.get(neighbor) is None
                for direction in ORTHOGONAL_DIRECTIONS
                if (neighbor := self.tile_cache.neighbor(pos, direction)) is not None
            )
        ]
        if not frontiers:
            return None
        return min(
            frontiers,
            key=lambda pos: (
                pos.distance_squared(ore),
                current.distance_squared(pos),
                pos.y,
                pos.x,
            ),
        )

    def plan_supply_route(
            self,
            ore: Position,
    ) -> tuple[
        list[Position],
        dict[Position, Direction],
        dict[Position, Position],
        int,
    ] | None:
        """Build a bridge-aware A* route from a Gunner input to an ore neighbour."""
        if self.gunner_site is None or self.gunner_direction is None:
            self.clear_a_star_state("supply_route")
            return None
        ore_entries = {
            entry
            for direction in ORTHOGONAL_DIRECTIONS
            if (entry := self.tile_cache.neighbor(ore, direction)) is not None
            and self.is_supply_tile(entry)
        }
        gunner_entries = {
            entry
            for direction in ORTHOGONAL_DIRECTIONS
            if direction != self.gunner_direction
            and (entry := self.tile_cache.neighbor(self.gunner_site, direction)) is not None
            and self.is_supply_tile(entry)
        }
        if not ore_entries or not gunner_entries:
            self.clear_a_star_state("supply_route")
            return None

        search_state = self.a_star_state("supply_route")
        travel_plan = a_star_from_any_with_bridges(
            None,
            gunner_entries,
            ore_entries,
            lambda _controller, pos: pos != ore and pos != self.gunner_site and self.is_supply_tile(pos),
            normal_step_cost=_SUPPLY_CONVEYOR_STEP_COST,
            bridge_step_cost=_SUPPLY_BRIDGE_STEP_COST,
            neighbor_fn=self.tile_cache.neighbor,
            max_expansions=_SUPPLY_BRIDGE_SEARCH_EXPANSIONS,
            bridge_landing_fn=lambda _controller, pos: pos != ore and pos != self.gunner_site and self.is_supply_bridge_landing(pos),
            existing_bridge_crossings=self.known_supply_bridge_crossings(),
            state=search_state,
        )
        if travel_plan is None:
            return None
        path, new_bridge_crossings, cost = travel_plan
        bridge_targets = {
            target: source for source, target in new_bridge_crossings.items()
        }
        known_crossings = self.known_supply_bridge_crossings()
        for source, target in zip(path, path[1:]):
            if known_crossings.get(source) == target:
                bridge_targets[target] = source
        directions = {
            tile: tile.direction_to(
                self.gunner_site if index == 0 else path[index - 1]
            )
            for index, tile in enumerate(path)
            if tile not in bridge_targets
        }
        return path, directions, bridge_targets, cost

    def is_supply_tile(self, pos: Position) -> bool:
        """Allow a known route tile, including replaceable enemy logistics.

        A known Bridge remains a route tile only when its cached endpoint can
        be used as a supply crossing.  Roads and conveyors are deliberately
        admitted independent of owner: while standing on a foreign transport
        tile the Intruder can destroy it and replace it with its own conveyor.
        """
        env = self.known_env.get(pos)
        if env in (None, Environment.WALL):
            return False
        if self.is_protected_transport(pos):
            return False
        building = self.known_buildings.get(pos)
        return (
            building is None
            or building[0] in _CLEARABLE_WALKABLE_BUILDINGS
            or (
                building[0] == EntityType.BRIDGE
                and pos in self.known_bridge_targets
            )
        )

    def is_supply_bridge_landing(self, pos: Position) -> bool:
        """Return whether a new supply Bridge may be installed on ``pos``."""
        env = self.known_env.get(pos)
        if env in (None, Environment.WALL):
            return False
        building = self.known_buildings.get(pos)
        return not self.is_protected_transport(pos) and (
            building is None or building[0] in _CLEARABLE_WALKABLE_BUILDINGS
        )

    def known_supply_bridge_crossings(self) -> dict[Position, Position]:
        """Map each existing Bridge's Gunner-side endpoint to its landing tile."""
        return {
            target: bridge
            for bridge, target in self.known_bridge_targets.items()
            if self.known_buildings.get(bridge) is not None
            and self.known_buildings[bridge][0] == EntityType.BRIDGE
            and not self.is_protected_transport(bridge)
        }

    def refresh_known_bridge_targets(self, controller: Controller) -> None:
        """Cache endpoints for visible Bridges so supply planning can reuse them."""
        for pos in self.tile_cache.visible_tiles:
            building = self.known_buildings.get(pos)
            if building is None or building[0] != EntityType.BRIDGE:
                self.known_bridge_targets.pop(pos, None)
                self.known_bridge_ids.pop(pos, None)
                continue
            building_id = self.tile_cache.building_id_at(pos)
            if building_id is None or self.known_bridge_ids.get(pos) == building_id:
                continue
            self.known_bridge_targets[pos] = self.tile_cache.canonicalize(
                controller.get_bridge_target(building_id)
            )
            self.known_bridge_ids[pos] = building_id

    def reset_supply_plan(self) -> None:
        """Forget an invalid route so the next turn can choose another Ti source."""
        for name in (
                "supply_route",
                "supply_exploration",
                "supply_rejoin",
                "pending_supply_bridge",
                "titanium_search",
        ):
            self.clear_a_star_state(name)
        self.supply_ore = None
        self.supply_path = []
        self.supply_bridge_crossings = {}
        self.pending_supply_bridge = None
        self.supply_directions = {}
        self.supply_bridge_targets = {}
        self.supply_index = 0
        self.supply_plan_candidates = None
        self.supply_plan_cursor = 0
        self.deferred_supply_candidates = []
        self.supply_exploration_entry = None
        self.supply_exploring_back_to_gunner = False
        self.failed_supply_search_frontiers = set()
        self.supply_search_target = None
        self.supply_seen_ores = set()
        self.supply_replan_candidates = []
        self.supply_plan_cost = None

    def search_for_titanium(self, controller: Controller) -> None:
        """Explore the Gunner's rear-side frontier until titanium becomes visible.

        This is reconnaissance, not supply-line construction.  It uses a
        bounded A* path through known terrain instead of repeatedly walking
        in one absolute direction; a wall at the edge of the map otherwise
        strands the Intruder after it has built a trail of roads.
        """
        if self.gunner_direction is None:
            return
        current = self.get_cached_position()
        target = self.supply_search_frontier(current)
        self.supply_search_target = target
        if target is None:
            return
        search_state = self.a_star_state("titanium_search")
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
            return
        if not path:
            # This frontier may be visible across a wall or behind a solid
            # building.  A* has already spent its bounded attempt proving no
            # known route, so allow the next turn to consider another one.
            self.failed_supply_search_frontiers.update((target,))
            return
        if self.try_move_step(
            controller,
            current.direction_to(path[0]),
            build_road=True,
        ):
            # A successful scout move changes the visible frontier ring, so
            # earlier failed routes may now have a way around their obstacle.
            self.failed_supply_search_frontiers = set()

    def supply_search_frontier(self, current: Position) -> Position | None:
        """Choose the next untried cache frontier on the Gunner's resource side."""
        if self.gunner_site is None or self.gunner_direction is None:
            return None
        dx, dy = self.gunner_direction.opposite().delta()
        frontiers = [
            pos
            for pos in self.known_env
            if pos != current
            and pos not in self.failed_supply_search_frontiers
            and self.is_roadable_position(pos)
            and any(
                neighbor is not None and neighbor not in self.known_env
                for direction in DIRECTIONS
                if (neighbor := self.tile_cache.neighbor(pos, direction)) is not None
            )
        ]
        if not frontiers:
            return None

        def resource_side(pos: Position) -> bool:
            return (
                (pos.x - self.gunner_site.x) * dx
                + (pos.y - self.gunner_site.y) * dy
            ) >= 0

        candidates = [pos for pos in frontiers if resource_side(pos)] or frontiers
        return min(
            candidates,
            key=lambda pos: (
                current.distance_squared(pos),
                -(
                    (pos.x - self.gunner_site.x) * dx
                    + (pos.y - self.gunner_site.y) * dy
                ),
                pos.y,
                pos.x,
            ),
        )
