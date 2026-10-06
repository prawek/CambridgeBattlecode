"""Resumable planning of conveyor branches and bridge crossings."""

from cambc import Controller, Direction, EntityType, Environment, Position
from finalbot.world.fire_lanes import transport_risk
from finalbot.shared.constants import (
    BRIDGE_MAX_JUMP_DISTANCE,
    BRIDGE_ROUTE_MAX_EXPANSIONS,
    DIRECTIONS,
    MAX_FLOW_PLAN_ALTERNATIVES,
    MAX_HARVESTERS_PER_LINE,
    ORTHOGONAL_DIRECTIONS,
    PASSABLE_BUILDINGS,
    RESOURCE_AXIONITE,
    RESOURCE_TITANIUM,
)
from finalbot.economy.exploration import frontier_search_steps
from finalbot.economy.network.planner import (
    dedicated_route_tree,
    flow_augmentation_steps,
    residual_capacity_tree,
    transport_max_flow,
)
from finalbot.economy.builder.settings import TRANSPORT_BRIDGE_OFFSETS


class BuilderRouting:
    """Uses state initialized by BuilderBot."""

    def connection_plan(
            self,
            controller: Controller,
            ore: Position,
    ) -> tuple[
        Position,
        list[Position],
        dict[Position, Direction],
        dict[Position, Position],
        Position,
    ] | None:
        """Return the cheapest construction which raises transport max flow."""
        network = self.known_connected_network()
        if not network:
            return None
        core_receivers = self.sector_core_receiver_tiles()
        if not core_receivers:
            return None

        direct_tree = dedicated_route_tree(core_receivers)
        network_loads = self.known_network_loads(network)
        effective_loads = dict(network_loads)
        for pos in network:
            if self.network_memory.continuously_busy(pos):
                effective_loads[pos] = MAX_HARVESTERS_PER_LINE
        residual_tree = residual_capacity_tree(
            network,
            effective_loads,
            self.transport_receiver,
            self.is_core_receiver_tile,
            MAX_HARVESTERS_PER_LINE,
        )
        locally_owned_source = (
            not self.is_harvester_on_tile(ore)
            or ore in self.owned_harvester_tiles
        )
        if locally_owned_source:
            # Python state is not shared between builders.  Only this
            # process's owned lines have a complete source/reservation count;
            # a globally observed allied trunk can hide harvesters discovered
            # by another scout and must not advertise fake residual capacity.
            residual_tree.intersection_update(self.owned_network_tiles)
        else:
            # Lost and foreign mines receive a physically separate line.  A
            # replacement builder cannot reconstruct the dead owner's flow
            # reservations safely enough to merge into any existing trunk.
            residual_tree.clear()
        # A candidate is legal only if it reaches a residual-capacity node or
        # an unused core intake.  Maximise flow first; among all one-unit
        # augmentations, minimise actual marginal construction cost.
        primary_tree = direct_tree | residual_tree

        sector_entries = self.sector_core_entry_tiles()
        chosen = self.flow_augmentation_plan(
            controller,
            ore,
            network,
            primary_tree,
            sector_entries,
            network_loads,
        )
        if chosen is not None:
            self.last_plan_starts_new_line = chosen[4] in direct_tree
            return chosen

        # Edge maps can leave a sector with only one usable intake.  Once it
        # is occupied, reserve any still-free perimeter port rather than
        # forcing every later mine through that same bottleneck.  Existing
        # transport remains excluded, so this is a new physical lane, not an
        # unmeasured cross-process merge.
        global_receivers = self.core_receiver_tiles()
        global_entries = self.core_entry_tiles()
        global_tree = dedicated_route_tree(global_receivers)
        chosen = self.flow_augmentation_plan(
            controller,
            ore,
            network,
            global_tree | residual_tree,
            global_entries,
            network_loads,
        )
        self.last_plan_starts_new_line = (
            chosen is not None and chosen[4] in global_tree
        )
        return chosen

    def flow_augmentation_plan(
            self,
            controller: Controller,
            ore: Position,
            network: set[Position],
            anchors: set[Position],
            allowed_core_entries: set[Position],
            network_loads: dict[Position, int],
    ) -> tuple[
        Position,
        list[Position],
        dict[Position, Direction],
        dict[Position, Position],
        Position,
    ] | None:
        """Find one min-cost conveyor/bridge augmentation of current flow."""
        conveyor_cost = controller.get_conveyor_cost()[0]
        bridge_cost = controller.get_bridge_cost()[0]
        for receiver in self.buildable_approaches(ore):
            if (
                receiver in anchors
                and self.network_receiver_accepts(receiver, ore)
                and self.plan_raises_transport_flow(ore, network, [], {}, {}, allowed_core_entries)
            ):
                return receiver, [], {}, {}, receiver
        remaining_anchors = set(anchors)
        for _ in range(MAX_FLOW_PLAN_ALTERNATIVES):
            result = self.transport_flow_augmentation(
                self.buildable_approaches(ore),
                remaining_anchors,
                network,
                conveyor_cost,
                bridge_cost,
                allowed_core_entries,
                network_loads,
                source_ore=ore,
            )
            if result is None:
                return None
            nodes, directions, bridge_targets, _ = result
            approach = nodes[0]
            anchor = nodes[-1]
            build_tiles = nodes[:-1]
            source = ore if not build_tiles else build_tiles[-1]
            valid = ((self.is_core_receiver_tile(anchor) and source in bridge_targets) or self.network_plan_receiver_accepts(
                anchor,
                source,
                allowed_core_entries,
            )) and not any(
                self.is_incompatible_existing_conveyor(tile, direction)
                for tile, direction in directions.items()
            )
            if valid and self.plan_raises_transport_flow(
                ore,
                network,
                build_tiles,
                directions,
                bridge_targets,
                allowed_core_entries,
            ):
                return approach, build_tiles, directions, bridge_targets, anchor

            # The cheapest sink can be stale or only appear residual in this
            # process's partial cache.  Exclude it and continue with the next
            # min-cost lane instead of repeatedly deferring the mine forever.
            remaining_anchors.discard(anchor)
            if not remaining_anchors:
                break
        return None

    def plan_raises_transport_flow(
            self,
            ore: Position,
            network: set[Position],
            build_tiles: list[Position],
            directions: dict[Position, Direction],
            bridge_targets: dict[Position, Position],
            allowed_core_entries: set[Position],
    ) -> bool:
        """Verify a proposed branch on the actual directed max-flow graph.

        Residual anchors are a fast search heuristic, not a proof: stale
        observations, a wrong-way reused conveyor, or a bridge landing can
        make a geometrically complete route carry no resources.  Materialise
        the candidate in memory and reject it unless the source itself becomes
        served and total sustainable flow grows.
        """
        # Populate the baseline value and source set once for this network.
        self.known_network_loads(network)
        baseline = self.network_flow_cache_value
        virtual_network = network | set(build_tiles)

        def virtual_receiver(pos: Position) -> Position | None:
            bridge_target = bridge_targets.get(pos)
            if bridge_target is not None:
                return bridge_target
            direction = directions.get(pos)
            if direction is not None:
                return self.tile_cache.neighbor(pos, direction)
            return self.transport_receiver(pos)

        def virtual_accepts(receiver: Position, source: Position) -> bool:
            if self.is_core_receiver_tile(receiver):
                return True
            if receiver in bridge_targets:
                return True
            direction = directions.get(receiver)
            if direction is not None:
                return direction != receiver.direction_to(source)
            return self.network_receiver_accepts(receiver, source)

        harvesters = {
            pos
            for pos, building in self.known_buildings.items()
            if building is not None
            and building[1] == self.team
            and building[0] == EntityType.HARVESTER
        }
        harvesters.add(ore)
        harvester_outputs = {
            source: [
                receiver
                for direction in ORTHOGONAL_DIRECTIONS
                if (receiver := self.tile_cache.neighbor(source, direction)) is not None
                and receiver in virtual_network
                and virtual_accepts(receiver, source)
            ]
            for source in harvesters
        }
        value, _, served = transport_max_flow(
            virtual_network,
            harvester_outputs,
            virtual_receiver,
            self.is_core_receiver_tile,
            MAX_HARVESTERS_PER_LINE,
        )
        return value > baseline and ore in served

    def transport_flow_augmentation(
            self,
            starts: list[Position],
            anchors: set[Position],
            network: set[Position],
            conveyor_cost: int,
            bridge_cost: int,
            allowed_core_entries: set[Position],
            network_loads: dict[Position, int],
            source_ore: Position | None = None,
    ) -> tuple[
        list[Position],
        dict[Position, Direction],
        dict[Position, Position],
        int,
    ] | None:
        """Run min-cost augmentation over conveyors, bridges, and residual edges."""
        blocked = {
            pos for pos, building in self.known_buildings.items()
            if building is not None and (
                building[0] not in PASSABLE_BUILDINGS
                or (building[0] == EntityType.CORE and building[1] != self.team)
            )
        }
        reachable = self.construction_access.reachable(
            self.current_position or self.core_pos,
            self.known_env,
            blocked,
            self.tile_cache.neighbor,
            DIRECTIONS,
            self.planning_budget,
        )

        def usable(pos: Position) -> bool:
            return pos in anchors or (
                pos in reachable
                and pos != source_ore
                and pos not in network
                and self.traversable_for_connection(pos)
            )

        def confirmed_bridge_obstacle(pos: Position) -> bool:
            env = self.known_env.get(pos)
            if env is None:
                # Never commit an expensive bridge merely because its middle
                # tile has not been observed yet.
                return False
            if pos in getattr(self, 'threatened_transport_tiles', ()):
                return True
            if env == Environment.WALL or pos == source_ore:
                return True
            if pos in network:
                # A lane excluded from this builder's residual anchors is a
                # physical crossing obstacle even if its observed load is low.
                # Crossing it preserves independent intake capacity.
                return pos not in anchors
            building = self.known_buildings.get(pos)
            if building is None:
                return False
            building_type, building_team = building
            if building_type == EntityType.ROAD:
                return False
            if (
                building_team == self.team
                and building_type in {
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                    EntityType.BRIDGE,
                }
            ):
                return False
            return True

        def bridge_crosses_block(
                current: Position,
                direction: Direction,
                distance: int,
        ) -> bool:
            dx, dy = direction.delta()
            return any(
                confirmed_bridge_obstacle(pos)
                for step in range(1, distance)
                if (pos := self.tile_cache.offset(current, dx * step, dy * step)) is not None
            )

        def bridge_obstacle(source: Position, target: Position) -> bool:
            # A bridge into Core can reach its entire footprint, including
            # diagonal ports beyond the conveyor-only intake perimeter.
            if self.is_core_receiver_tile(target):
                return True
            dx, dy = target.x - source.x, target.y - source.y
            steps = max(abs(dx), abs(dy))
            return any(
                confirmed_bridge_obstacle(middle)
                for step in range(1, steps)
                if (middle := self.tile_cache.offset(source, round(dx * step / steps), round(dy * step / steps))) is not None
            )

        def conveyor_cost_at(pos: Position, direction: Direction) -> int:
            building = self.known_buildings.get(pos)
            if (
                building is not None
                and building[1] == self.team
                and building[0] in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
                and self.known_conveyor_directions.get(pos) == direction
            ):
                # Reuse saves the actual build action, but pricing its occupied
                # tile like one conveyor keeps the spatial heuristic exact and
                # prevents an 800-cell Dijkstra scan under the 2 ms limit.
                # Direction compatibility is still reused during execution.
                return conveyor_cost + transport_risk(self, pos, conveyor_cost)
            # Crossing an enemy road requires two 2-Ti builder attacks before
            # the conveyor can be installed.  Price that delay and resource
            # loss instead of repeatedly preferring a contested shortcut.
            attack_cost = 4 if self.is_enemy_road(pos) else 0
            return conveyor_cost + attack_cost + transport_risk(self, pos, conveyor_cost)

        def edge_is_usable(pos: Position, direction: Direction) -> bool:
            building = self.known_buildings.get(pos)
            if (
                building is None
                or building[1] != self.team
                or building[0] not in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
            ):
                return True
            return (
                self.known_conveyor_directions.get(pos) == direction
                or pos in self.unfinished_branch_tiles
                or pos in self.abandoned_branch_tiles
            )

        if self.search_network is not network:
            self.search_memory.jobs.clear()
            self.search_network = network
        search_key = (
            frozenset(starts), frozenset(anchors), frozenset(allowed_core_entries),
            id(network), self.construction_access.signature, source_ore,
        )
        result = self.search_memory.run(search_key, lambda: flow_augmentation_steps(
            starts,
            anchors,
            ORTHOGONAL_DIRECTIONS,
            self.tile_cache.neighbor,
            self.tile_cache.offset,
            usable,
            bridge_crosses_block,
            lambda receiver, source: self.network_plan_receiver_accepts(
                receiver,
                source,
                allowed_core_entries,
            ),
            conveyor_cost,
            bridge_cost,
            BRIDGE_MAX_JUMP_DISTANCE,
            max(BRIDGE_ROUTE_MAX_EXPANSIONS, len(reachable) + len(anchors)),
            conveyor_cost_fn=conveyor_cost_at,
            anchor_cost_fn=lambda anchor: network_loads.get(anchor, 0),
            edge_usable_fn=edge_is_usable,
            minimum_conveyor_cost=conveyor_cost,
            bridge_offsets=TRANSPORT_BRIDGE_OFFSETS,
            bridge_obstacle_fn=bridge_obstacle,
            bridge_anchor_accepts_fn=lambda receiver, source: (
                self.is_core_receiver_tile(receiver)
                or self.network_receiver_accepts(receiver, source)
            ),
        ))
        if result is None:
            return None
        nodes, bridge_targets, cost = result
        directions = {
            node: node.direction_to(nodes[index + 1])
            for index, node in enumerate(nodes[:-1])
            if node not in bridge_targets
        }
        return nodes, directions, bridge_targets, cost

    def connection_walk(self, start: Position, targets: set[Position]) -> list[Position]:
        """Retain construction detours too; a bridge can require a long walk."""
        if start in targets:
            return []
        return self.walk_search_memory.run(
            (start, frozenset(targets), self.construction_access.signature),
            lambda: frontier_search_steps(
                start, targets, self.tile_cache.neighbor,
                lambda pos: pos in self.known_env
                and self.traversable_for_planning(None, pos), DIRECTIONS,
            ),
        )

    def assign_connection_target(self, controller: Controller, current: Position, ore: Position) -> bool:
        """Commit the shortest safe branch plan and path toward its first tile."""
        plan = self.connection_plan(
            controller,
            ore,
        )
        if plan is None:
            return False
        approach, build_tiles, directions, bridge_targets, anchor = plan
        # Install from sink to source.  Every newly activated tile feeds a
        # completed downstream segment, even if this builder is later killed.
        execution_tiles = list(reversed(build_tiles))
        path_to_approach: list[Position] = []
        if build_tiles:
            path_to_approach = self.connection_walk(current, {execution_tiles[0]})
            if not path_to_approach and current != execution_tiles[0]:
                return False
        path = list(path_to_approach)
        previous = execution_tiles[0] if execution_tiles else current
        for tile in execution_tiles:
            if previous.distance_squared(tile) <= 2:
                if not path or path[-1] != tile:
                    path.append(tile)
                previous = tile
                continue
            detour = self.connection_walk(previous, {tile})
            if not detour:
                return False
            path.extend(detour)
            previous = tile
        if not build_tiles:
            approaches = set(self.ore_action_approaches(ore))
            if current not in approaches:
                path = self.connection_walk(current, approaches)
                if not path:
                    return False
        self.target_ore = ore
        self.target_resource = (
            RESOURCE_TITANIUM
            if self.resource_at(ore) == Environment.ORE_TITANIUM
            else RESOURCE_AXIONITE
        )
        self.target_is_connection = True
        self.scout_target = None
        self.path = path
        self.path_index = 0
        self.conveyor_path_tiles = set(build_tiles)
        self.conveyor_directions = directions
        self.bridge_targets = bridge_targets
        self.deferred_bridge_sources = set()
        self.bridge_activation_path_index = 0
        self.connection_anchor = anchor
        self.connection_starts_new_line = self.last_plan_starts_new_line
        self.network_memory.replan_owned_branch(
            set(build_tiles),
            self.known_connected_network(),
        )
        self.mode = "connect"
        return True
