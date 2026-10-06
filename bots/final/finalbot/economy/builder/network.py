"""Read-only network connectivity, capacity and receiver rules."""

from collections import deque
from cambc import Direction, EntityType, Environment, Position
from finalbot.shared.constants import (
    DIRECTIONS,
    MAX_HARVESTERS_PER_LINE,
    ORTHOGONAL_DIRECTIONS,
)
from finalbot.economy.network.planner import (
    receivers_need_capacity_relief,
    sector_entry_offsets,
    sector_receiver_offsets,
    transport_max_flow,
)


class BuilderNetwork:
    """Uses state initialized by BuilderBot."""

    def ore_network_needs_work(self, ore: Position) -> bool:
        """Return whether a harvester lacks either continuity or transport capacity."""
        # A refinery's titanium input deliberately terminates at the foundry.
        # Reconnecting that mine directly to the core would starve refinement.
        for direction in ORTHOGONAL_DIRECTIONS:
            feed = self.tile_cache.neighbor(ore, direction)
            visited = set()
            while feed is not None and feed not in visited and len(visited) < 64:
                visited.add(feed)
                building = self.known_buildings.get(feed)
                if building == (EntityType.FOUNDRY, self.team):
                    return False
                feed = self.transport_receiver(feed)
        return (
            not self.harvester_is_connected(ore)
            or self.ore_needs_capacity_relief(ore)
        )

    def ore_needs_capacity_relief(
            self,
            ore: Position,
            network: set[Position] | None = None,
            loads: dict[Position, int] | None = None,
    ) -> bool:
        """Detect a mine which cannot fit through any accepting output.

        Responsibility must not die with the builder that erected the mine.
        Any scout may recover an unserved source; ``connection_plan`` treats
        foreign/recovered harvesters as separate-line work and will not merge
        them into that scout's local branch merely because it is nearby.
        """
        if network is None:
            network = self.known_connected_network()
        if loads is None:
            loads = self.known_network_loads(network)
        if (
            self.network_flow_cache_network is network
            and ore not in self.network_flow_cache_served_harvesters
        ):
            return True
        receivers = [
            receiver
            for direction in ORTHOGONAL_DIRECTIONS
            if (receiver := self.tile_cache.neighbor(ore, direction)) is not None
            and receiver in network
            and self.network_receiver_accepts(receiver, ore)
        ]
        return receivers_need_capacity_relief(
            [
                (
                    loads.get(receiver, 0),
                    self.network_memory.continuously_busy(receiver),
                )
                for receiver in receivers
            ],
            MAX_HARVESTERS_PER_LINE,
        )

    def ore_action_approaches(self, ore: Position) -> list[Position]:
        """Return movement tiles from which a builder can act on an ore deposit."""
        return [
            approach
            for direction in DIRECTIONS
            if (approach := self.tile_cache.neighbor(ore, direction)) is not None
            and self.traversable_for_ore_path(None, approach)
        ]

    def core_receiver_tiles(self) -> set[Position]:
        """Return in-bounds tiles that deliver resources directly into the core."""
        if self.core_pos is None:
            return set()
        if self._core_tiles_key == self.core_pos:
            return self._core_tiles
        self._core_tiles_key = self.core_pos
        self._core_tiles = {
            pos
            for dx in range(-1, 2)
            for dy in range(-1, 2)
            if (pos := self.tile_cache.offset(self.core_pos, dx, dy)) is not None
        }
        return self._core_tiles

    def sector_core_receiver_tiles(self) -> set[Position]:
        """Reserve one Core edge for this builder's distributed lane family."""
        if self.core_pos is None or self.work_direction is None:
            return self.core_receiver_tiles()
        offsets = sector_receiver_offsets(self.work_direction)
        return {
            pos
            for dx, dy in offsets
            if (pos := self.tile_cache.offset(self.core_pos, dx, dy)) is not None
        }

    def sector_core_entry_tiles(self) -> set[Position]:
        """Return the three non-overlapping outer intake tiles for this sector."""
        if self.core_pos is None or self.work_direction is None:
            return set()
        offsets = sector_entry_offsets(self.work_direction)
        return {
            pos
            for dx, dy in offsets
            if (pos := self.tile_cache.offset(self.core_pos, dx, dy)) is not None
        }

    def core_entry_tiles(self) -> set[Position]:
        """Return every cardinal perimeter tile that can feed the 3x3 core."""
        if self.core_pos is None:
            return set()
        entries: set[Position] = set()
        for direction in ORTHOGONAL_DIRECTIONS:
            for dx, dy in sector_entry_offsets(direction):
                pos = self.tile_cache.offset(self.core_pos, dx, dy)
                if pos is not None:
                    entries.add(pos)
        return entries

    def network_plan_receiver_accepts(
            self,
            receiver: Position,
            source: Position,
            allowed_core_entries: set[Position] | None = None,
    ) -> bool:
        """Apply the sector intake reservation while planning new transport."""
        if self.is_core_receiver_tile(receiver):
            entries = (
                self.sector_core_entry_tiles()
                if allowed_core_entries is None
                else allowed_core_entries
            )
            return source in entries
        return self.network_receiver_accepts(receiver, source)

    def is_core_receiver_tile(self, pos: Position) -> bool:
        """Return whether a conveyor at ``pos`` can send resources into the core."""
        return pos in self.core_receiver_tiles()

    def known_connected_network(self) -> set[Position]:
        """Return the part of the observed conveyor graph that truly reaches core."""
        if self.connected_network_cache is not None:
            return self.connected_network_cache

        connected = set(self.core_receiver_tiles())
        # Reverse edges let us traverse the directed conveyor graph from the
        # core in linear time.  The earlier fixed-point scan became quadratic
        # on a long line and could consume the per-turn time budget.
        incoming: dict[Position, list[Position]] = {}
        for pos, building in self.known_buildings.items():
            if building is None or building[1] != self.team:
                continue
            if building[0] in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
                direction = self.known_conveyor_directions.get(pos)
                if direction is not None:
                    receiver = self.tile_cache.neighbor(pos, direction)
                    if receiver is not None:
                        incoming.setdefault(receiver, []).append(pos)
            elif building[0] == EntityType.BRIDGE:
                target = self.known_bridge_targets.get(pos)
                if target is not None:
                    incoming.setdefault(target, []).append(pos)

        queue = deque(connected)
        while queue:
            receiver = queue.popleft()
            for source in incoming.get(receiver, []):
                if source in connected:
                    continue
                if not self.network_receiver_accepts(receiver, source):
                    continue
                connected.add(source)
                queue.append(source)
        self.connected_network_cache = connected
        return connected

    def network_receiver_accepts(self, receiver: Position, source: Position) -> bool:
        """Return whether a connected receiver can accept flow from ``source``."""
        if self.is_core_receiver_tile(receiver):
            return True
        building = self.known_buildings.get(receiver)
        if building is None or building[1] != self.team:
            return False
        if building[0] == EntityType.BRIDGE:
            return True
        direction = self.known_conveyor_directions.get(receiver)
        return direction is not None and direction != receiver.direction_to(source)

    def transport_receiver(self, pos: Position) -> Position | None:
        """Return the next tile in the known allied transport graph."""
        building = self.known_buildings.get(pos)
        if building is None or building[1] != self.team:
            return None
        if building[0] in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
            direction = self.known_conveyor_directions.get(pos)
            return None if direction is None else self.tile_cache.neighbor(pos, direction)
        if building[0] == EntityType.BRIDGE:
            return self.known_bridge_targets.get(pos)
        return None

    def known_network_loads(self, network: set[Position]) -> dict[Position, int]:
        """Compute the maximum sustainable flow through the directed network."""
        harvesters = sorted(
            (
                pos
                for pos, building in self.known_buildings.items()
                if building is not None
                and building[0] == EntityType.HARVESTER
            ),
            key=lambda pos: (pos.x, pos.y),
        )
        harvester_set = frozenset(harvesters)
        if (
            self.network_flow_cache_network is network
            and self.network_flow_cache_harvesters == harvester_set
        ):
            return self.network_flow_cache_loads
        harvester_outputs: dict[Position, list[Position]] = {}
        for ore in harvesters:
            harvester_outputs[ore] = [
                receiver
                for direction in ORTHOGONAL_DIRECTIONS
                if (receiver := self.tile_cache.neighbor(ore, direction)) is not None
                and receiver in network
                and self.network_receiver_accepts(receiver, ore)
            ]
        value, loads, served_harvesters = transport_max_flow(
            network,
            harvester_outputs,
            self.transport_receiver,
            self.is_core_receiver_tile,
            MAX_HARVESTERS_PER_LINE,
        )
        self.network_flow_cache_network = network
        self.network_flow_cache_harvesters = harvester_set
        self.network_flow_cache_value = value
        self.network_flow_cache_loads = loads
        self.network_flow_cache_served_harvesters = served_harvesters
        return loads

    def transport_lane_is_saturated(self, pos: Position, loads: dict[Position, int]) -> bool:
        """Combine structural source count with four observed occupancy turns."""
        if self.is_core_receiver_tile(pos):
            return False
        if loads.get(pos, 0) >= MAX_HARVESTERS_PER_LINE:
            return True
        return self.network_memory.continuously_busy(pos)

    def harvester_is_connected(self, ore: Position) -> bool:
        """Return whether a harvester has a directed allied conveyor path to core."""
        network = self.known_connected_network()
        for direction in ORTHOGONAL_DIRECTIONS:
            receiver = self.tile_cache.neighbor(ore, direction)
            if receiver is None:
                continue
            if receiver in network and self.network_receiver_accepts(receiver, ore):
                return True
        return False

    def traversable_for_connection(self, pos: Position) -> bool:
        """Whether a branch conveyor can be safely installed on ``pos``.

        Movement may cross an opponent's road or conveyor, but a transport
        branch cannot use it: it would either have no ownership or require an
        impossible overwrite.  Keep the two predicates separate so A* still
        has normal movement freedom while branch planning is ownership-safe.
        """
        if (
            not self.in_bounds(pos)
            or pos in self.permanently_blocked
            or self.is_yield_blocked(pos)
            # A conveyor branch is a committed construction job.  Unlike
            # scouting, it must not invent a shortcut through unseen terrain:
            # an unknown wall would otherwise leave a half-built branch with
            # its last conveyor pointing into the obstacle.
            or pos not in self.known_env
        ):
            return False
        env = self.known_env.get(pos)
        if env == Environment.WALL:
            return False
        building = self.known_buildings.get(pos)
        if building is None:
            return True
        building_type, building_team = building
        # An already laid conveyor may belong to another builder's live route
        # that is outside this bot's vision.  It is not rewriteable.  The
        # connection planner validates its existing direction before using it
        # as part of a branch; roads carry no resource flow and may safely be
        # converted on the next action.
        if building_team != self.team:
            # Enemy roads remain walkable.  A builder can deliberately enter
            # one, destroy it from underfoot, and replace it with the planned
            # conveyor.  Treating every rival road as a permanent wall made a
            # single scouting trail sever otherwise short mining branches.
            return building_type == EntityType.ROAD
        if building_type == EntityType.ROAD:
            return True
        return building_type in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}

    def is_incompatible_existing_conveyor(self, pos: Position, direction: Direction) -> bool:
        """Return whether an allied conveyor at ``pos`` points the wrong way."""
        building = self.known_buildings.get(pos)
        if (
            building is None
            or building[1] != self.team
            or building[0] not in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
        ):
            return False
        return self.known_conveyor_directions.get(pos) != direction

    def buildable_approaches(self, ore_pos: Position) -> list[Position]:
        """Return cardinal ore-adjacent tiles suitable for the first branch conveyor."""
        return [
            approach
            for direction in ORTHOGONAL_DIRECTIONS
            if (approach := self.tile_cache.neighbor(ore_pos, direction)) is not None
            if (
                self.is_core_receiver_tile(approach)
                or self.traversable_for_connection(approach)
            )
        ]

    def get_conveyor_direction(self, target: Position) -> Direction:
        """Return the planned outgoing direction for a branch conveyor tile."""
        direction = self.conveyor_directions.get(target)
        if direction is not None:
            return direction
        return Direction.CENTRE
