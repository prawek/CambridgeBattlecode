"""Sector economy and siege roles for Florent Code League."""

from collections import Counter, deque
from heapq import heappop, heappush

from fcode import Controller, Direction, EntityType, Environment, GameConstants, Position, ResourceType


CARDINALS = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)
CARDINAL_DELTAS = tuple(direction.delta() for direction in CARDINALS)
ORE = (Environment.ORE_TITANIUM, Environment.ORE_VOLTIUM)
UNKNOWN_OR_BLOCKED = (None, Environment.WALL, Environment.VOID)
WALKABLE = (None, EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.MINE)
TURRETS = (EntityType.GUNNER, EntityType.SENTINEL, EntityType.SPIKE, EntityType.LAUNCHER)
RANGED = (EntityType.GUNNER, EntityType.SENTINEL)
TRANSPORT = (EntityType.CONVEYOR, EntityType.SPLITTER)
TARGET_PRIORITY = {
    EntityType.CORE: 100,
    EntityType.SENTINEL: 90,
    EntityType.GUNNER: 90,
    EntityType.SPIKE: 85,
    EntityType.BUILDER_BOT: 80,
    EntityType.LAUNCHER: 65,
    EntityType.HARVESTER: 55,
    EntityType.CONVEYOR: 30,
    EntityType.SPLITTER: 30,
    EntityType.BARRIER: 10,
}

OWN_CORE, ENEMY_CORE, THREAT, SPAWN_ORDER = range(4)
WORKER_STATUS = 4  # Eight slots, each holds the worker's last round and claimed ore.
COMBAT_STATUS = 12  # A different combat role writes each round.
ORE_REPORT = 13
LAUNCH_BUILDER = 14
SPAWN_ROLE = 15
ECONOMY_ROLES = 8
ATTACKER, DEFENDER = ECONOMY_ROLES, ECONOMY_ROLES + 6
COMBAT_ROLES = 7
SPAWN_CODES = DEFENDER + 2
HEARTBEAT_TIMEOUT = 10
LINE_CAPACITY = 4
POSITION_BASE = 128
POSITION_SPACE = POSITION_BASE ** 2 + 1
MAX_ROUTE_STEPS = 24
ROUTING_BUDGET_US = 6_500
PLANNING_BUDGET_US = 7_500


def pack(tile):
    return 0 if tile is None else 1 + tile.x * POSITION_BASE + tile.y


def unpack(value):
    return Position(*divmod(value - 1, POSITION_BASE)) if value else None


def pack_status(turn, tile):
    return (turn + 1) * POSITION_SPACE + pack(tile)


def unpack_status(value):
    turn, tile = divmod(value, POSITION_SPACE)
    return turn - 1, unpack(tile)


def core_tiles(anchor):
    return tuple(Position(anchor.x + dx, anchor.y + dy) for dx in (0, 1) for dy in (0, 1))


def manhattan(a, b):
    return abs(a.x - b.x) + abs(a.y - b.y)


def neighbors(tile):
    return tuple(Position(tile.x + dx, tile.y + dy) for dx, dy in CARDINAL_DELTAS)


def toward_core(tile, anchor):
    dx = max(anchor.x - tile.x, 0, tile.x - anchor.x - 1)
    dy = max(anchor.y - tile.y, 0, tile.y - anchor.y - 1)
    return dx * dx + dy * dy


def can_reach_enemy(ct, core, enemy):
    pit = ct.get_pit()
    if pit is None or ct.pit_crossable():
        return True
    if enemy is None or not ct.pit_separates(core, enemy):
        return False
    axis, edge, width = pit
    coordinate = (lambda tile: tile.x) if axis == "x" else (lambda tile: tile.y)
    shore = edge - 1 if coordinate(core) < edge else edge + width
    gap = min(abs(shore - coordinate(tile)) for tile in core_tiles(enemy))
    return gap * gap <= GameConstants.SENTINEL_VISION_RADIUS_SQ


class MapMemory:
    def __init__(self):
        self.terrain = {}
        self.buildings = {}
        self.transport = {}
        self.harvesters = set()
        self.ores = {}
        self.adjacent = {}
        self.frontier = {}
        self.visits = Counter()
        self.visible = set()
        self.bounds = None
        self.infrastructure_revision = 0
        self.terrain_revision = 0
        self.guns = {}
        self.danger = set()
        self.launch_zones = set()
        self.symmetries = {"horizontal", "vertical", "rotation"}

    def observe(self, ct, team):
        """Refresh visible occupancy and remember terrain and conveyor facing."""
        if self.bounds is None:
            self.bounds = ct.get_map_width(), ct.get_map_height()
        self.visible = set(ct.get_nearby_tiles())
        seen_buildings = {}
        discoveries = []
        for tile in self.visible:
            if tile not in self.terrain:
                env = ct.get_tile_env(tile)
                self.terrain[tile] = env
                self.adjacent[tile] = neighbors(tile)
                discoveries.append(tile)
                if env in ORE:
                    self.ores[tile] = env
            entity = ct.get_tile_building_id(tile)
            old = self.buildings.get(tile)
            if old is not None and entity == old[0]:
                continue
            transport = self.transport.pop(tile, None)
            harvester = tile in self.harvesters
            self.harvesters.discard(tile)
            if transport is not None or harvester:
                self.infrastructure_revision += 1
            if entity is None:
                self.buildings.pop(tile, None)
                continue
            if entity not in seen_buildings:
                seen_buildings[entity] = (entity, ct.get_entity_type(entity), ct.get_team(entity))
            building = self.buildings[tile] = seen_buildings[entity]
            if building[2] == team:
                if building[1] in TRANSPORT:
                    self.transport[tile] = building[1], ct.get_direction(entity)
                    self.infrastructure_revision += 1
                elif building[1] == EntityType.HARVESTER:
                    self.harvesters.add(tile)
                    self.infrastructure_revision += 1
        if discoveries:
            self.terrain_revision += 1
            for symmetry in tuple(self.symmetries):
                for tile in discoveries:
                    other = self.terrain.get(self.mirror(tile, symmetry))
                    if other is not None and other != self.terrain[tile]:
                        self.symmetries.remove(symmetry)
                        break
            changed = set(discoveries)
            changed.update(other for tile in discoveries for other in self.adjacent[tile] if other in self.terrain)
            width, height = self.bounds
            for tile in changed:
                self.frontier[tile] = sum(0 <= other.x < width and 0 <= other.y < height
                                          and other not in self.terrain for other in self.adjacent[tile])
        self.visits[ct.get_position()] += 1

    def mirror(self, tile, symmetry, size=1):
        width, height = self.bounds
        x = width - size - tile.x if symmetry in ("horizontal", "rotation") else tile.x
        y = height - size - tile.y if symmetry in ("vertical", "rotation") else tile.y
        return Position(x, y)

    def core_hypotheses(self, core):
        # If the terrain evidence is ambiguous, scout each distinct hypothesis.
        options = self.symmetries or {"horizontal", "vertical", "rotation"}
        return sorted({self.mirror(core, symmetry, 2) for symmetry in options} - {core})

    def observe_weapons(self, ct, team):
        guns = {tile: value for tile, value in self.guns.items() if tile not in self.visible}
        for tile in self.visible:
            building = self.buildings.get(tile)
            if building is None or building[2] == team or building[1] not in TURRETS:
                continue
            entity, kind, _ = building
            facing = ct.get_direction(entity) if kind in RANGED else Direction.CENTRE
            old = self.guns.get(tile)
            if old is not None and old[:2] == (kind, facing):
                guns[tile] = old
            else:
                ray = ct.get_attackable_tiles_from(tile, facing, kind)
                guns[tile] = kind, facing, tuple(ray)
        if guns != self.guns:
            self.guns = guns
            self.danger = {tile for kind, _, ray in guns.values() if kind != EntityType.LAUNCHER for tile in ray}
            self.launch_zones = {Position(tile.x + dx, tile.y + dy)
                                 for tile, (kind, _, _) in guns.items() if kind == EntityType.LAUNCHER
                                 for dx in (-1, 0, 1) for dy in (-1, 0, 1)}

    def kind(self, tile):
        building = self.buildings.get(tile)
        return building[1] if building else None

    def walk(self, ct, start, avoid):
        """Find reachable standing tiles and their first legal step."""
        found = {start: (0, None)}
        queue = deque()
        for direction in CARDINALS:
            tile = start.add(direction)
            if tile not in avoid and ct.can_move(direction):
                found[tile] = (1, direction)
                queue.append(tile)
        expanded = 0
        while queue:
            if expanded % 64 == 0 and ct.get_cpu_time_elapsed() >= ROUTING_BUDGET_US:
                break
            expanded += 1
            tile = queue.popleft()
            dist, first = found[tile]
            for other in self.adjacent[tile]:
                if other in found or other in avoid or self.terrain.get(other) in UNKNOWN_OR_BLOCKED:
                    continue
                if self.kind(other) in WALKABLE:
                    found[other] = (dist + 1, first)
                    queue.append(other)
        return found

    def explore(self, ct, reachable, target, sector):
        best = None
        least_visited = None
        dx, dy = sector.delta() if sector is not None else (0, 0)
        for tile, (distance, direction) in reachable.items():
            if direction is None:
                continue
            goal_penalty = manhattan(tile, target) if target is not None else 0
            visit_rank = (self.visits[tile] + goal_penalty, distance, tile)
            if least_visited is None or visit_rank < least_visited[0]:
                least_visited = visit_rank, direction
            fog = self.frontier.get(tile, 0)
            if fog:
                priority = distance + 2 * self.visits[tile] - fog
                if target is not None:
                    priority += manhattan(tile, target) * 2
                else:
                    priority -= (tile.x * dx + tile.y * dy) // 3
                candidate = priority, tile, direction
                if best is None or candidate < best:
                    best = candidate
        if best is not None:
            direction = best[2]
        elif least_visited is not None:
            direction = least_visited[1]
        else:
            return
        if ct.can_move(direction):
            ct.move(direction)


def stand_near(reachable, target):
    return min((reachable[tile] for tile in neighbors(target) if tile in reachable),
               key=lambda option: option[0], default=None)


def step(ct, option):
    if option is not None and option[1] is not None and ct.can_move(option[1]):
        ct.move(option[1])
        return True
    return False


class TransportNetwork:
    """Sustainable flow in stacks per harvester period (four rounds)."""

    SOURCE = "source"
    SINK = "core"

    def __init__(self, memory, core):
        self.core = set(core_tiles(core))
        self.transport = memory.transport.copy()
        self.edges = {self.SOURCE: {}, self.SINK: {}}
        incoming = {}
        outlets = {}
        for tile, (kind, direction) in self.transport.items():
            facing = tile.add(direction)
            targets = (facing,) if kind == EntityType.CONVEYOR else (
                other for other in memory.adjacent[tile] if other != tile.add(direction.opposite())
            )
            outlets[tile] = [other for other in targets if self.accepts(other, tile)]
            for other in outlets[tile]:
                incoming.setdefault(other, []).append(tile)

        self.linked = self.core.copy()
        queue = deque(sorted(self.core))
        while queue:
            for tile in incoming.get(queue.popleft(), ()):
                if tile not in self.linked:
                    self.linked.add(tile)
                    queue.append(tile)
        intake_capacity = len(memory.harvesters) + LINE_CAPACITY
        for tile in sorted(self.core):
            self.add_edge(tile, self.SINK, intake_capacity)
        for tile, targets in outlets.items():
            if tile not in self.linked:
                continue
            output = (tile,)
            self.add_edge(tile, output, LINE_CAPACITY)
            for target in targets:
                if target in self.linked:
                    self.add_edge(output, target, LINE_CAPACITY)
        for ore in sorted(memory.harvesters):
            receivers = self.outputs(ore, memory.adjacent[ore])
            if receivers:
                source = ("ore", ore)
                self.add_edge(self.SOURCE, source, 1)
                for receiver in receivers:
                    self.add_edge(source, receiver, 1)
                self.augment(source)
        self.served = {node[1] for node, capacity in self.edges[self.SOURCE].items() if capacity == 0}
        self.loads = {tile: LINE_CAPACITY - self.edges[tile][(tile,)] for tile in self.linked - self.core}
        self.residual = self.open_inputs()

    def accepts(self, tile, source):
        if tile in self.core:
            return True
        transport = self.transport.get(tile)
        if transport is None:
            return False
        kind, direction = transport
        if kind == EntityType.CONVEYOR:
            return tile.add(direction) != source
        return tile.add(direction.opposite()) == source

    def outputs(self, ore, adjacent):
        return [tile for tile in adjacent if tile in self.linked and self.accepts(tile, ore)]

    def add_edge(self, start, end, capacity):
        self.edges.setdefault(start, {})[end] = capacity
        self.edges.setdefault(end, {}).setdefault(start, 0)

    def augment(self, source):
        # An augmenting path may reassign a harvester with two valid outlets.
        previous = {self.SOURCE: None, source: self.SOURCE}
        queue = deque([source])
        while queue and self.SINK not in previous:
            node = queue.popleft()
            for other, capacity in self.edges[node].items():
                if capacity and other not in previous:
                    previous[other] = node
                    queue.append(other)
        if self.SINK not in previous:
            return
        node = self.SINK
        while node != self.SOURCE:
            parent = previous[node]
            self.edges[parent][node] -= 1
            self.edges[node][parent] += 1
            node = parent

    def open_inputs(self, blocked=()):
        """Find receivers that can deliver another source through to Core."""
        seen = {self.SOURCE, self.SINK}
        for tile in blocked:
            seen.update((tile, (tile,)))
        queue = deque([self.SINK])
        while queue:
            node = queue.popleft()
            for other in self.edges[node]:
                if other not in seen and self.edges[other][node] > 0:
                    seen.add(other)
                    queue.append(other)
        return self.linked & seen - set(blocked)


def construction_reserve(ct):
    return ct.get_builder_bot_cost() + ct.get_harvester_cost() + 4 * ct.get_conveyor_cost()


class Economy:
    def __init__(self):
        self.ore = None
        self.network_revision = -1
        self.flow = None
        self.blueprint = {}
        self.owned = {}
        self.busy_at = {}
        self.sampled = None
        self.sample_started = 0
        self.defer_until = {}
        self.last_ore_progress = 0

    def network(self, memory, core):
        if self.network_revision != memory.infrastructure_revision:
            self.flow = TransportNetwork(memory, core)
            self.network_revision = memory.infrastructure_revision
            for tile in self.flow.linked & memory.visible - self.flow.core:
                kind, direction = memory.transport[tile]
                if kind == EntityType.CONVEYOR:
                    self.blueprint[tile] = direction
        return self.flow

    def sample_transport(self, ct, memory, flow, now):
        """Sample one visible lane, requiring four consecutive full turns."""
        self.busy_at = {tile: data for tile, data in self.busy_at.items()
                        if tile in flow.loads and now - data[0] <= 12}
        candidates = memory.visible & flow.loads.keys()
        complete = now - self.sample_started >= LINE_CAPACITY
        sample = self.sampled
        if sample not in candidates or complete:
            sample = max(candidates, key=lambda tile: (now - self.busy_at.get(tile, (-16, 0))[0],
                                                        flow.loads[tile], tile), default=None)
            self.sample_started = now
        self.sampled = sample
        if sample is not None:
            last, streak = self.busy_at.get(sample, (-1, 0))
            loaded = ct.get_stored_resource(memory.buildings[sample][0]) is not None
            self.busy_at[sample] = now, (streak + 1 if last == now - 1 else 1) if loaded else 0
        return {tile for tile, (_, streak) in self.busy_at.items() if streak >= LINE_CAPACITY}

    def seals(self, memory):
        return {tile for tile, (kind, facing) in memory.transport.items()
                if kind == EntityType.CONVEYOR and tile.add(facing) in memory.harvesters}

    def routes(self, ct, memory, flow, anchors, seals):
        """Price construction from every residual receiver back toward ore."""
        routes = {tile: (flow.loads.get(tile, 0), 0, None) for tile in anchors}
        queue = [(cost, steps, tile) for tile, (cost, steps, _) in routes.items()]
        queue.sort()
        for expanded in range(len(memory.terrain) * 2):
            if not queue or (expanded % 48 == 0 and ct.get_cpu_time_elapsed() >= ROUTING_BUDGET_US):
                break
            cost, steps, tile = heappop(queue)
            if (cost, steps) != routes[tile][:2] or steps >= MAX_ROUTE_STEPS:
                continue
            for other in memory.adjacent.get(tile) or neighbors(tile):
                env = memory.terrain.get(other)
                if env in UNKNOWN_OR_BLOCKED or other in anchors:
                    continue
                if other in memory.buildings and other not in seals:
                    continue
                if tile in anchors and not flow.accepts(tile, other):
                    continue
                price = 2 + 5 * (env in ORE) + 12 * (other in memory.danger) + (other in seals)
                new_cost = cost + price
                if other not in routes or (new_cost, steps + 1) < routes[other][:2]:
                    routes[other] = new_cost, steps + 1, tile
                    heappush(queue, (new_cost, steps + 1, other))
        return routes

    def repair(self, ct, memory, flow, current):
        for tile in memory.adjacent[current]:
            facing = self.repair_facing(memory, flow, tile)
            if facing is None:
                continue
            if ct.can_build_conveyor(tile, facing):
                ct.build_conveyor(tile, facing)
                return True
        return False

    def repair_facing(self, memory, flow, tile):
        facing = self.blueprint.get(tile)
        if facing is None or tile in memory.buildings or tile in memory.danger:
            return None
        output = tile.add(facing)
        if output not in flow.residual or not flow.accepts(output, tile):
            return None
        if any(other in memory.harvesters
               or (other in memory.transport and other.add(memory.transport[other][1]) == tile)
               for other in memory.adjacent[tile] if other != output):
            return facing
        return None

    def cleanup(self, ct, memory, flow, current, now):
        for tile in memory.adjacent[current]:
            if tile not in self.owned:
                continue
            owner, built = self.owned[tile]
            building = memory.buildings.get(tile)
            if building is None or building[0] != owner:
                self.owned.pop(tile, None)
                continue
            if tile in flow.linked or now - built < 48 or tile in memory.danger:
                continue
            if any(other in memory.harvesters or other in memory.transport
                   for other in memory.adjacent[tile]):
                continue
            if ct.get_stored_resource(owner) is None and ct.can_destroy(tile):
                ct.destroy(tile)
                self.owned.pop(tile)
                self.blueprint.pop(tile, None)

    def guard(self, ct, memory, flow, core, current, team, enemies, urgent):
        """Deny unused outlets and cover a threatened harvesting site."""
        titanium = ct.get_global_resources()
        reserve = construction_reserve(ct)
        if titanium < reserve + ct.get_conveyor_cost():
            return False
        for port in memory.adjacent[current]:
            if memory.terrain.get(port) != Environment.EMPTY or port in memory.buildings:
                continue
            ores = [ore for ore in memory.adjacent[port] if ore in flow.served]
            for ore in ores:
                close = [target for target, kind in enemies
                         if kind in (*TURRETS, EntityType.BUILDER_BOT) and target.distance_squared(ore) <= 13]
                if urgent != bool(close) or (not close and toward_core(ore, core) > 25):
                    continue
                guns = [other for other in memory.adjacent[ore]
                        if memory.buildings.get(other, (None, None, None))[1:] in (
                            (EntityType.GUNNER, team), (EntityType.SPIKE, team))]
                if close and ct.get_unit_count() < GameConstants.MAX_TEAM_UNITS - 10:
                    if len(guns) < 2:
                        for target in close:
                            if any(self.guard_covers(ct, memory, gun, target) for gun in guns):
                                continue
                            if titanium >= reserve + ct.get_spike_cost() and port.distance_squared(target) <= 2:
                                if ct.can_build_spike(port):
                                    ct.build_spike(port)
                                    return True
                            direction = port.direction_to(target)
                            if (direction != Direction.CENTRE
                                    and ct.get_global_ammo() >= 3 * GameConstants.GUNNER_AMMO_COST
                                    and titanium >= reserve + ct.get_gunner_cost()
                                    and ct.can_fire_from(port, direction, EntityType.GUNNER, target)
                                    and ct.can_build_gunner(port, direction)):
                                ct.build_gunner(port, direction)
                                return True
                if (not close and not guns and toward_core(ore, core) <= 12
                        and ct.get_global_ammo() >= 8 * GameConstants.GUNNER_AMMO_COST
                        and titanium >= reserve + 2 * ct.get_gunner_cost()
                        and ct.get_unit_count() < GameConstants.MAX_TEAM_UNITS - 10):
                    facing = ore.cardinal_direction_to(port)
                    if ct.can_build_gunner(port, facing):
                        ct.build_gunner(port, facing)
                        return True
                # It remains possible to walk over a seal. A belt pointing
                # into the harvester refuses a stack from that same side.
                facing = port.cardinal_direction_to(ore)
                if any(other != ore and other in memory.ores and other not in flow.served
                       for other in memory.adjacent[port]):
                    continue
                if port not in memory.danger and ct.can_build_conveyor(port, facing):
                    ct.build_conveyor(port, facing)
                    return True
        return False

    def guard_covers(self, ct, memory, gun, target):
        entity, kind, _ = memory.buildings[gun]
        if kind == EntityType.SPIKE:
            return gun.distance_squared(target) <= GameConstants.SPIKE_ATTACK_RADIUS_SQ
        return gun in memory.visible and ct.can_fire_from(gun, ct.get_direction(entity), kind, target)

    def approach_guard(self, ct, memory, flow, reachable, enemies):
        if not enemies or ct.get_global_resources() < construction_reserve(ct) + ct.get_conveyor_cost():
            return False
        choices = []
        for ore in flow.served & memory.visible:
            close = [tile for tile, kind in enemies
                     if kind in (*TURRETS, EntityType.BUILDER_BOT) and tile.distance_squared(ore) <= 13]
            for port in memory.adjacent[ore]:
                if memory.terrain.get(port) != Environment.EMPTY or port in memory.buildings or port in memory.danger:
                    continue
                if not any(port.distance_squared(tile) <= 8 for tile in close):
                    continue
                approach = stand_near(reachable, port)
                if approach is not None and 0 < approach[0] <= 4:
                    choices.append(approach)
        return bool(choices) and step(ct, min(choices, key=lambda option: option[0]))

    def capture_outlet(self, ct, memory, flow, current, team):
        """Turn an exposed hostile outlet into a short feed to our Core."""
        if ct.get_global_resources() < construction_reserve(ct) + ct.get_conveyor_cost():
            return False
        for port in memory.adjacent[current]:
            if memory.terrain.get(port) != Environment.EMPTY or port in memory.buildings or port in memory.danger:
                continue
            receivers = [tile for tile in memory.adjacent[port] if tile in flow.core]
            if not receivers:
                continue
            for source in memory.adjacent[port]:
                entity, kind, owner = memory.buildings.get(source, (None, None, team))
                if owner == team or source not in memory.visible:
                    continue
                feeds = kind == EntityType.HARVESTER or (
                    kind == EntityType.CONVEYOR and source.add(ct.get_direction(entity)) == port
                    and ct.get_stored_resource(entity) is not None
                )
                if feeds:
                    facing = port.cardinal_direction_to(receivers[0])
                    if ct.can_build_conveyor(port, facing):
                        ct.build_conveyor(port, facing)
                        return True
        return False

    def work(self, ct, memory, core, team, role, current, reachable, enemies):
        flow = self.network(memory, core)
        now = ct.get_current_round()
        if self.repair(ct, memory, flow, current) or self.guard(ct, memory, flow, core, current, team, enemies, urgent=True):
            return True
        if self.capture_outlet(ct, memory, flow, current, team):
            return True
        self.cleanup(ct, memory, flow, current, now)
        busy = self.sample_transport(ct, memory, flow, now)
        anchors = flow.open_inputs(busy) if busy else flow.residual
        claimed = {}
        for other in reversed(range(ECONOMY_ROLES)):
            if other == role:
                continue
            last_seen, ore = unpack_status(ct.read_store(WORKER_STATUS + other))
            if ore is not None and now - last_seen < HEARTBEAT_TIMEOUT:
                claimed[ore] = other
        if self.ore is not None and now - self.last_ore_progress >= 40:
            self.defer_until[self.ore] = now + 32
            self.ore = None
        enemy = unpack(ct.read_store(ENEMY_CORE))
        needs_ammo = can_reach_enemy(ct, core, enemy)
        candidates = [ore for ore in memory.ores
                      if ore not in flow.served and now >= self.defer_until.get(ore, 0)
                      and (memory.ores[ore] == Environment.ORE_TITANIUM or needs_ammo or now >= 870)
                      and (ore not in memory.buildings or ore in memory.harvesters)
                      and (ore not in claimed or (ore == self.ore and role < claimed[ore]))]
        if candidates:
            seals = self.seals(memory)
            routes = self.routes(ct, memory, flow, anchors, seals)
            live_ammo = ct.get_global_voltium() * 2 + ct.get_global_ammo()
            titanium_sources = sum(memory.ores.get(ore) == Environment.ORE_TITANIUM for ore in flow.served)
            sector_x, sector_y = CARDINAL_DELTAS[role % 4]
            choices = []
            for index, ore in enumerate(candidates):
                if index % 16 == 0 and ct.get_cpu_time_elapsed() >= PLANNING_BUDGET_US:
                    break
                for outlet in memory.adjacent[ore]:
                    if outlet not in routes:
                        continue
                    target = outlet
                    downstream = routes[target][2]
                    while downstream is not None and downstream not in anchors and target != ore:
                        target = downstream
                        downstream = routes[target][2]
                    if target == ore:
                        continue
                    if downstream is None:
                        if ore in memory.harvesters or not flow.accepts(outlet, ore):
                            continue
                        target = ore
                    option = stand_near(reachable, target)
                    if option is None:
                        continue
                    sector = max(0, -((ore.x - core.x) * sector_x + (ore.y - core.y) * sector_y))
                    ammo = 0
                    if memory.ores[ore] == Environment.ORE_VOLTIUM:
                        if titanium_sources < 2 and now < 140:
                            ammo = (2 - titanium_sources) * 7
                        elif live_ammo >= 100:
                            ammo = 18
                        elif live_ammo < 30 and now >= 10:
                            ammo = -5
                    score = routes[outlet][0] + option[0] + sector + ammo + 8 * (ore in memory.danger)
                    score -= 6 * (ore == self.ore) + 6 * (ore in memory.harvesters)
                    choices.append((score, ore, target, downstream, option))
            for _, ore, target, downstream, option in sorted(choices, key=lambda choice: choice[:3])[:8]:
                if self.execute(ct, memory, current, target, downstream, option, seals, now):
                    if ore != self.ore or option[0] == 0:
                        self.last_ore_progress = now
                    self.ore = ore
                    return True
        self.ore = None
        if self.approach_guard(ct, memory, flow, reachable, enemies):
            return True
        if self.guard(ct, memory, flow, core, current, team, enemies, urgent=False):
            return True
        damaged = [tile for tile in self.blueprint.keys() & memory.visible
                   if self.repair_facing(memory, flow, tile) is not None]
        repairs = [option for tile in damaged if (option := stand_near(reachable, tile)) is not None
                   and 0 < option[0] <= 5]
        return bool(repairs) and step(ct, min(repairs, key=lambda option: option[0]))

    def execute(self, ct, memory, current, target, downstream, option, seals, now):
        if option[0]:
            return step(ct, option)
        if downstream is None:
            if ct.can_build_harvester(target):
                ct.build_harvester(target)
                return True
            return False
        if target in seals:
            entity = memory.buildings[target][0]
            if ct.get_stored_resource(entity) is not None or not ct.can_destroy(target):
                return False
            ct.destroy(target)
            self.blueprint.pop(target, None)
            return True
        direction = target.cardinal_direction_to(downstream)
        if ct.can_build_conveyor(target, direction):
            ct.build_conveyor(target, direction)
            self.owned[target] = ct.get_tile_building_id(target), now
            return True
        return False


class Core:
    def __init__(self):
        self.spawned = {}
        self.combat_alive = {}
        self.last_expansion = -100

    def run(self, ct):
        core = ct.get_position()
        footprint = core_tiles(core)
        team = ct.get_team()
        ct.write_store(OWN_CORE, pack(core))
        threat = None
        enemy = unpack(ct.read_store(ENEMY_CORE))
        round_number = ct.get_current_round()
        combat = ct.read_store(COMBAT_STATUS)
        if combat:
            seen, role_index = divmod(combat, COMBAT_ROLES)
            self.combat_alive[ATTACKER + role_index] = seen - 1
        for entity in ct.get_nearby_entities():
            if ct.get_team(entity) == team:
                continue
            kind = ct.get_entity_type(entity)
            pos = ct.get_position(entity)
            if kind == EntityType.CORE:
                enemy = pos
                ct.write_store(ENEMY_CORE, pack(pos))
            dist = toward_core(pos, core)
            threatens_core = False
            if kind in RANGED:
                facing = ct.get_direction(entity)
                threatens_core = any(ct.can_fire_from(pos, facing, kind, tile) for tile in footprint)
            if threatens_core or (dist <= 25 and kind in (*TURRETS, EntityType.BUILDER_BOT)):
                candidate = (dist + 8 * (kind == EntityType.BUILDER_BOT) - 30 * threatens_core, pos)
                if threat is None or candidate < threat:
                    threat = candidate
        ct.write_store(THREAT, pack(threat[1] if threat else None))

        shortfall = (120 if threat else 80) - ct.get_global_ammo()
        if shortfall > 0:
            amount = min((shortfall + 1) // 2, ct.get_global_voltium())
            if amount and ct.can_convert_ammo(amount):
                ct.convert_ammo(amount)

        roles = list(range(4))
        if threat:
            roles.insert(0, DEFENDER)
        titanium = ct.get_global_resources()
        if round_number >= 12 and can_reach_enemy(ct, core, enemy):
            roles.append(ATTACKER)
        if titanium >= 250 and round_number >= 100:
            extra = min(4, 1 + (round_number - 100) // 100)
            roles.extend(range(4, 4 + extra))
        if ATTACKER in roles and round_number >= 100 and titanium >= 300:
            attack_slots = 3 if titanium < 600 else 4 if titanium < 1_200 else 6
            roles.extend(range(ATTACKER + 1, ATTACKER + attack_slots))
        reserve = ct.get_harvester_cost() + 4 * ct.get_conveyor_cost()
        for role in roles:
            last_spawn = self.spawned.get(role, -100)
            is_economy = role < ECONOMY_ROLES
            retry_after = 18 if is_economy or role == DEFENDER else 64 if titanium >= 600 else 96
            if role in self.spawned and round_number - last_spawn < retry_after:
                continue
            if 4 <= role < ECONOMY_ROLES and round_number - self.last_expansion < 45:
                continue
            if role in self.spawned:
                if is_economy:
                    seen, _ = unpack_status(ct.read_store(WORKER_STATUS + role))
                else:
                    seen = self.combat_alive.get(role, -100)
                if seen >= last_spawn and round_number - seen < 2 * HEARTBEAT_TIMEOUT:
                    continue
            protected = reserve if self.spawned and role != DEFENDER else 0
            if titanium < ct.get_builder_bot_cost() + protected:
                return
            positions = [pos for pos in ct.get_nearby_tiles(dist_sq=2) if ct.can_spawn(pos)]
            if not positions:
                return
            target = threat[1] if role == DEFENDER else enemy
            direction = CARDINALS[role % 4] if is_economy else None
            if direction is not None:
                dx, dy = direction.delta()
                positions.sort(key=lambda pos: (-(pos.x * dx + pos.y * dy),
                                                ct.get_tile_env(pos) in ORE, manhattan(pos, core)))
            elif target is not None:
                positions.sort(key=lambda pos: (manhattan(pos, target), ct.get_tile_env(pos) in ORE))
            entity = ct.spawn_builder(positions[0])
            self.spawned[role] = round_number
            if 4 <= role < ECONOMY_ROLES:
                self.last_expansion = round_number
            ct.write_store(SPAWN_ORDER, entity)
            ore = self.sector_order(ct, core, direction, round_number, role) if is_economy else None
            ct.write_store(SPAWN_ROLE, pack(ore) * SPAWN_CODES + role + 1)
            return

    def sector_order(self, ct, core, direction, now, role):
        claimed = set()
        for other in range(ECONOMY_ROLES):
            if other != role:
                seen, ore = unpack_status(ct.read_store(WORKER_STATUS + other))
                if ore is not None and now - seen < HEARTBEAT_TIMEOUT:
                    claimed.add(ore)
        dx, dy = direction.delta()
        options = []
        for tile in ct.get_nearby_tiles(dist_sq=20):
            if tile in claimed or (tile.x - core.x) * dx + (tile.y - core.y) * dy <= 0:
                continue
            env = ct.get_tile_env(tile)
            if env in ORE and ct.get_tile_building_id(tile) is None:
                options.append((toward_core(tile, core) + 10 * (env == Environment.ORE_VOLTIUM), tile))
        return min(options)[1] if options else None


def enemy_tiles(ct, team, tiles):
    """Yield legal target occupants, with mobile units taking precedence."""
    for tile in tiles:
        entity = ct.get_tile_builder_bot_id(tile)
        if entity is None:
            entity = ct.get_tile_building_id(tile)
        if entity is not None and ct.get_team(entity) != team:
            yield tile, entity, ct.get_entity_type(entity)


def weapon_score(ct, entity, kind, damage, repairing=False):
    hp = ct.get_hp(entity)
    if kind == EntityType.CORE and hp <= damage:
        return 200
    return TARGET_PRIORITY.get(kind, 0) + 12 * (hp <= damage) + 45 * repairing


def run_turret(ct):
    if not ct.can_act():
        return
    kind, team = ct.get_entity_type(), ct.get_team()
    if kind == EntityType.SPIKE:
        for tile in ct.get_attackable_tiles():
            occupants = (ct.get_tile_builder_bot_id(tile), ct.get_tile_building_id(tile))
            if any(entity is not None and ct.get_team(entity) != team for entity in occupants):
                if ct.can_fire(tile):
                    ct.fire(tile)
                    return
        return

    ammo_cost = GameConstants.GUNNER_AMMO_COST if kind == EntityType.GUNNER else GameConstants.SENTINEL_AMMO_COST
    if ct.get_global_ammo() < ammo_cost:
        return
    if kind == EntityType.SENTINEL:
        targets = list(enemy_tiles(ct, team, ct.get_attackable_tiles()))
        batteries = [ct.get_position(entity) for entity in ct.get_nearby_buildings()
                     if ct.get_team(entity) != team and ct.get_entity_type(entity) in RANGED]
        targets.sort(key=lambda obs: -weapon_score(
            ct, obs[1], obs[2], GameConstants.SENTINEL_DAMAGE,
            obs[2] == EntityType.BUILDER_BOT and any(obs[0].distance_squared(tile) <= 1 for tile in batteries),
        ))
        for tile, _, _ in targets:
            if ct.can_fire(tile):
                ct.fire(tile)
                return
        return

    target = ct.get_gunner_target()
    if target is not None and next(enemy_tiles(ct, team, (target,)), None) and ct.can_fire(target):
        ct.fire(target)
        return
    origin = ct.get_position()
    targets = list(enemy_tiles(ct, team, ct.get_nearby_tiles()))
    targets.sort(key=lambda obs: -weapon_score(ct, obs[1], obs[2], GameConstants.GUNNER_DAMAGE))
    for tile, _, target_kind in targets:
        if target_kind in (EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BARRIER):
            continue
        facing = origin.direction_to(tile)
        if ct.can_rotate(facing) and ct.can_fire_from(origin, facing, EntityType.GUNNER, tile):
            ct.rotate(facing)
            return


def landing_tiles(ct, source, tiles):
    if not ct.pit_crossable():
        return []
    return [tile for tile in tiles if ct.pit_separates(source, tile) and ct.is_tile_passable(tile)]


def forward_landings(ct, source, tiles, goal):
    current = manhattan(source, goal)
    return [tile for tile in tiles if not ct.pit_separates(source, tile)
            and manhattan(tile, goal) <= current - 3 and ct.is_tile_passable(tile)]


def run_launcher(ct):
    if not ct.can_act():
        return
    order = ct.read_store(LAUNCH_BUILDER)
    team = ct.get_team()
    home = unpack(ct.read_store(OWN_CORE))
    enemy = unpack(ct.read_store(ENEMY_CORE))
    for entity in ct.get_nearby_units(dist_sq=2):
        if ct.get_entity_type(entity) != EntityType.BUILDER_BOT:
            continue
        source = ct.get_position(entity)
        if ct.get_team(entity) == team:
            if entity != order:
                continue
            tiles = ct.get_attackable_tiles()
            if enemy is None or ct.pit_separates(source, enemy):
                targets = landing_tiles(ct, source, tiles)
            else:
                targets = forward_landings(ct, source, tiles, enemy)
            if enemy is not None:
                targets.sort(key=lambda tile: manhattan(tile, enemy))
        elif home is not None and toward_core(source, home) <= 25:
            targets = [tile for tile in ct.get_attackable_tiles() if not ct.pit_separates(source, tile)
                       and toward_core(tile, home) > toward_core(source, home) + 8]
            targets.sort(key=lambda tile: toward_core(tile, home), reverse=True)
        else:
            continue
        for tile in targets:
            if ct.can_launch(source, tile):
                ct.launch(source, tile)
                return


class Builder:
    def __init__(self):
        self.role = None
        self.assigned = True
        self.first_round = None
        self.memory = MapMemory()
        self.economy = Economy()
        self.trail = deque(maxlen=8)
        self.last_useful = 0
        self.scout_goal = None
        self.siege_site = None
        self.rejected_batteries = {}
        self.last_attack = None
        self.rejected_attacks = {}
        self.launch_wait = None
        self.rejected_launchers = {}

    def run(self, ct):
        turn = ct.get_current_round()
        if self.first_round is None:
            self.first_round = turn
        if self.role is None:
            ore, role = divmod(ct.read_store(SPAWN_ROLE), SPAWN_CODES)
            if role and ct.read_store(SPAWN_ORDER) == ct.get_id():
                self.role = role - 1
                self.economy.ore = unpack(ore)
                self.economy.last_ore_progress = turn
            elif turn > self.first_round:
                # A spawn can succeed just before a CPU interruption.
                self.role = ct.get_id() % 4
                self.assigned = False
            else:
                return
        core = unpack(ct.read_store(OWN_CORE))
        if core is None:
            return
        if self.assigned and self.role < ECONOMY_ROLES:
            ct.write_store(WORKER_STATUS + self.role, pack_status(turn, self.economy.ore))
        if self.assigned and self.role >= ATTACKER and turn % COMBAT_ROLES == self.role - ATTACKER:
            ct.write_store(COMBAT_STATUS, (turn + 1) * COMBAT_ROLES + self.role - ATTACKER)
        team, pos = ct.get_team(), ct.get_position()
        revision = self.memory.terrain_revision
        self.memory.observe(ct, team)
        self.memory.observe_weapons(ct, team)
        if revision != self.memory.terrain_revision:
            self.last_useful = turn
        self.trail.append(pos)
        enemy = unpack(ct.read_store(ENEMY_CORE))
        enemies = []
        for entity in ct.get_nearby_entities():
            if ct.get_team(entity) != team:
                kind, tile = ct.get_entity_type(entity), ct.get_position(entity)
                enemies.append((tile, kind))
                if kind == EntityType.CORE:
                    enemy = tile
                    ct.write_store(ENEMY_CORE, pack(enemy))
        threat = unpack(ct.read_store(THREAT))
        if self.local_action(ct, pos, core, threat, enemies, turn):
            self.last_useful = turn
            return
        avoid = self.memory.launch_zones
        if ct.get_hp() <= GameConstants.SENTINEL_DAMAGE:
            avoid = avoid | self.memory.danger
        cycling = len(self.trail) == self.trail.maxlen and len(set(self.trail)) <= 3
        if cycling and turn - self.last_useful >= 8:
            avoid = avoid | (set(self.trail) - {pos})
        reachable = self.memory.walk(ct, pos, avoid)
        if len(reachable) == 1 and cycling:
            reachable = self.memory.walk(ct, pos, self.memory.launch_zones)
        if self.role < ECONOMY_ROLES:
            previous_ore = self.economy.ore
            if ct.get_cpu_time_elapsed() < PLANNING_BUDGET_US and self.economy.work(
                ct, self.memory, core, team, self.role, pos, reachable, enemies
            ):
                if self.economy.last_ore_progress == turn:
                    self.last_useful = turn
                if self.assigned and previous_ore != self.economy.ore:
                    ct.write_store(WORKER_STATUS + self.role, pack_status(turn, self.economy.ore))
                return
            if self.assigned and previous_ore != self.economy.ore:
                ct.write_store(WORKER_STATUS + self.role, pack_status(turn, self.economy.ore))
            goal = self.report_ore(ct, core, turn)
            if (goal is None and enemy is not None and turn >= 600 and threat is None
                    and not ct.pit_separates(pos, enemy)):
                goal = enemy
                if self.advance_attack(ct, pos, goal, enemy, reachable, turn):
                    return
            if cycling and turn - self.last_useful >= 160 and len(reachable) <= 3 and threat is None:
                ct.self_destruct()
                return
            sector = CARDINALS[self.role % 4]
        elif self.role == DEFENDER:
            goal = threat or core
            if threat is not None:
                if self.cover_threat(ct, pos, threat, team):
                    self.last_useful = turn
                    return
                if step(ct, stand_near(reachable, threat)):
                    return
            sector = None
        else:
            goal = enemy or self.find_enemy_core(ct, pos, core)
            if goal is not None and self.advance_attack(ct, pos, goal, enemy, reachable, turn):
                return
            if cycling and turn - self.last_useful >= 140 and len(reachable) <= 3:
                ct.self_destruct()
                return
            sector = None
        self.memory.explore(ct, reachable, goal, sector)

    def report_ore(self, ct, core, now):
        last, suggestion = unpack_status(ct.read_store(ORE_REPORT))
        if self.assigned and now % ECONOMY_ROLES == self.role:
            available = [ore for ore in self.memory.ores if ore not in self.memory.buildings
                         and ore != self.economy.ore and self.economy.defer_until.get(ore, 0) <= now]
            if available:
                site = min(available, key=lambda tile: (manhattan(tile, core), tile))
                ct.write_store(ORE_REPORT, pack_status(now, site))
        if suggestion is not None and now - last <= 20 and suggestion not in self.memory.terrain:
            return suggestion
        return None

    def find_enemy_core(self, ct, pos, core):
        candidates = [tile for tile in self.memory.core_hypotheses(core)
                      if not all(part in self.memory.terrain and self.memory.kind(part) != EntityType.CORE
                                 for part in core_tiles(tile))]
        if ct.get_pit() is not None:
            candidates = [tile for tile in candidates if ct.pit_separates(core, tile)]
        if self.scout_goal not in candidates:
            rotated = self.memory.mirror(core, "rotation", 2)
            self.scout_goal = min(candidates, key=lambda tile: (tile != rotated, manhattan(pos, tile), tile),
                                  default=None)
        return self.scout_goal

    def local_action(self, ct, pos, core, threat, enemies, now):
        if not ct.can_act():
            return False
        adjacent = [tile for tile in self.memory.adjacent[pos] if tile in self.memory.visible]
        team = ct.get_team()
        ammo = ct.get_global_ammo()
        close = [tile for tile, kind in enemies
                 if kind in (*TURRETS, EntityType.BUILDER_BOT) and tile.distance_squared(pos) <= 8]
        if threat is not None or close:
            for tile in adjacent:
                building = self.memory.buildings.get(tile)
                if (building is not None and building[1:] == (EntityType.CORE, team)
                        and ct.get_hp(building[0]) <= GameConstants.CORE_MAX_HP - GameConstants.HEAL_AMOUNT
                        and ct.can_heal(tile)):
                    ct.heal(tile)
                    return True
        reserve = construction_reserve(ct)
        titanium = ct.get_global_resources()
        local_defense = toward_core(pos, core) <= 16
        if close and (self.role >= ATTACKER or local_defense):
            spikes = [tile for tile, building in self.memory.buildings.items()
                      if building[1:] == (EntityType.SPIKE, team) and tile.distance_squared(pos) <= 13]
            for tile in adjacent:
                covers = [target for target in close if tile.distance_squared(target) <= 2]
                if (covers and titanium >= ct.get_spike_cost() + (0 if local_defense else reserve)
                        and not any(spike.distance_squared(target) <= 2 for target in covers for spike in spikes)):
                    if ct.can_build_spike(tile):
                        ct.build_spike(tile)
                        return True
            batteries = [tile for tile in close
                         if tile in self.memory.guns and self.memory.guns[tile][0] in RANGED]
            if batteries and ammo >= 3 * GameConstants.SENTINEL_AMMO_COST:
                if titanium >= reserve + ct.get_sentinel_cost() and self.build_weapon(
                    ct, adjacent, batteries, EntityType.SENTINEL
                ):
                    return True
            if ammo >= 3 * GameConstants.GUNNER_AMMO_COST and titanium >= reserve + ct.get_gunner_cost():
                if self.build_weapon(ct, adjacent, close, EntityType.GUNNER):
                    return True

        targets = []
        for tile in adjacent:
            building = self.memory.buildings.get(tile)
            if building is None or building[2] == team:
                continue
            entity, kind, _ = building
            if now < self.rejected_attacks.get(tile, 0):
                continue
            if self.role < ATTACKER and kind not in TURRETS and not (local_defense and kind == EntityType.HARVESTER):
                continue
            score = TARGET_PRIORITY.get(kind, 0)
            if kind == EntityType.HARVESTER and self.memory.ores.get(tile) == Environment.ORE_VOLTIUM:
                score += 35
            if kind in TRANSPORT and ct.get_stored_resource(entity) == ResourceType.VOLTIUM:
                score += 35
            targets.append((-score, tile, entity, kind))
        for _, tile, entity, kind in sorted(targets):
            hp = ct.get_hp(entity)
            stalled = 0
            if self.last_attack is not None:
                previous, previous_hp, previous_round, failed = self.last_attack
                if entity == previous and now == previous_round + 1 and hp >= previous_hp:
                    stalled = failed + 1
            if stalled >= 4:
                self.rejected_attacks[tile] = now + 24
                continue
            if (kind in TURRETS or kind == EntityType.CORE or titanium >= reserve) and ct.can_fire(tile):
                ct.fire(tile)
                self.last_attack = entity, hp, now, stalled
                return True
        for tile in adjacent:
            if ct.can_heal(tile):
                ct.heal(tile)
                return True
        return False

    def cover_threat(self, ct, pos, threat, team):
        if not ct.can_act() or ct.get_global_resources() < ct.get_barrier_cost():
            return False
        gun = self.memory.guns.get(threat)
        adjacent = [tile for tile in self.memory.adjacent[pos]
                    if self.memory.terrain.get(tile) == Environment.EMPTY and tile not in self.memory.buildings]
        if gun is not None and gun[0] == EntityType.GUNNER:
            for tile in adjacent:
                if (tile in gun[2] and tile.distance_squared(threat) < pos.distance_squared(threat)
                        and sum(self.memory.terrain.get(other) not in UNKNOWN_OR_BLOCKED
                                and self.memory.kind(other) in WALKABLE
                                for other in self.memory.adjacent[tile]) >= 3
                        and ct.can_build_barrier(tile)):
                    ct.build_barrier(tile)
                    return True
        if threat in self.memory.visible and ct.get_tile_builder_bot_id(threat) is not None:
            if ct.get_global_resources() >= construction_reserve(ct) + ct.get_mine_cost():
                for tile in adjacent:
                    if tile.distance_squared(threat) == 1 and ct.can_build_mine(tile):
                        ct.build_mine(tile)
                        return True
        return False

    def build_weapon(self, ct, adjacent, targets, kind):
        team = ct.get_team()
        for entity in ct.get_nearby_buildings():
            if ct.get_entity_type(entity) == kind and ct.get_team(entity) == team:
                origin, facing = ct.get_position(entity), ct.get_direction(entity)
                if any(ct.can_fire_from(origin, facing, kind, target) for target in targets):
                    return False
        for tile in adjacent:
            for target in targets:
                facing = tile.direction_to(target)
                if facing != Direction.CENTRE and ct.can_fire_from(tile, facing, kind, target):
                    if ct.can_build(kind, tile, facing):
                        ct.build(kind, tile, facing)
                        return True
        return False

    def advance_attack(self, ct, pos, goal, enemy, reachable, now):
        if ct.get_cpu_time_elapsed() >= PLANNING_BUDGET_US:
            return False
        if enemy is not None and self.siege(ct, pos, enemy, reachable, now):
            return True

        across = ct.pit_separates(pos, goal)
        if across and not ct.pit_crossable():
            return False
        route = min((path for tile in core_tiles(goal)
                     if (path := stand_near(reachable, tile)) is not None),
                    key=lambda path: path[0], default=None)
        long_detour = route is not None and route[0] >= manhattan(pos, goal) + 5
        if (across or (enemy is not None and long_detour)) and self.request_launch(ct, pos, goal, across, now):
            return True
        if across:
            axis, edge, width = ct.get_pit()
            coordinate = (lambda tile: tile.x) if axis == "x" else (lambda tile: tile.y)
            shore = edge - 1 if coordinate(pos) < edge else edge + width
            path = min((option for tile, option in reachable.items() if coordinate(tile) == shore),
                       key=lambda option: option[0], default=None)
            return step(ct, path)
        if step(ct, route):
            return True
        # Keep closing on a rotatable hypothesis even if its footprint has not
        # entered vision. The fallback frontier scout can find a side route.
        where = min((tile for tile in reachable if manhattan(tile, goal) < manhattan(pos, goal)),
                    key=lambda tile: (manhattan(tile, goal), reachable[tile][0]), default=None)
        return where is not None and step(ct, reachable[where])

    def siege(self, ct, pos, enemy, reachable, now):
        if self.siege_site is not None:
            tile, built = self.siege_site
            if tile in self.memory.visible and self.memory.kind(tile) not in RANGED:
                if now - built < 24:
                    self.rejected_batteries[tile] = now + 48
                self.siege_site = None
        stock = ct.get_global_ammo() + 2 * ct.get_global_voltium()
        titanium = ct.get_global_resources() - construction_reserve(ct)
        if stock < 3 * GameConstants.GUNNER_AMMO_COST or titanium < ct.get_gunner_cost():
            return False
        weapons = [(EntityType.GUNNER, GameConstants.GUNNER_VISION_RADIUS_SQ)]
        if stock >= 3 * GameConstants.SENTINEL_AMMO_COST and titanium >= ct.get_sentinel_cost():
            weapons.insert(0, (EntityType.SENTINEL, GameConstants.SENTINEL_VISION_RADIUS_SQ))
        team = ct.get_team()
        targets = core_tiles(enemy)
        battery_count = 0
        for tile in self.memory.visible:
            entity, kind, owner = self.memory.buildings.get(tile, (None, None, None))
            if owner == team and kind in RANGED:
                facing = ct.get_direction(entity)
                if any(ct.can_fire_from(tile, facing, kind, target) for target in targets):
                    battery_count += 1
        if battery_count >= (2 if stock >= 150 else 1):
            return False
        choices = []
        for tile in self.memory.visible:
            if (tile in self.memory.buildings or self.memory.terrain[tile] in UNKNOWN_OR_BLOCKED
                    or tile in self.memory.launch_zones or now < self.rejected_batteries.get(tile, 0)):
                continue
            option = stand_near(reachable, tile)
            if option is None:
                continue
            for rank, (kind, radius) in enumerate(weapons):
                for target in targets:
                    dx, dy = abs(tile.x - target.x), abs(tile.y - target.y)
                    dist = dx * dx + dy * dy
                    if not 0 < dist <= radius or (dx and dy and dx != dy):
                        continue
                    score = option[0] * 3 + rank * 4 + 14 * (tile in self.memory.danger)
                    score += 6 * (self.memory.terrain[tile] in ORE) - dist // 4
                    choices.append((score, tile, target, kind, option))
        checks = set()
        for _, tile, target, kind, option in sorted(choices, key=lambda choice: choice[:3]):
            if len(checks) >= 14 or ct.get_cpu_time_elapsed() >= PLANNING_BUDGET_US:
                break
            facing = tile.direction_to(target)
            key = tile, target, kind
            if key in checks:
                continue
            checks.add(key)
            if not ct.can_fire_from(tile, facing, kind, target):
                continue
            if option[0]:
                if step(ct, option):
                    return True
            elif ct.can_build(kind, tile, facing):
                ct.build(kind, tile, facing)
                self.siege_site = tile, now
                self.last_useful = now
                return True
        return False

    def request_launch(self, ct, pos, goal, across, now):
        if self.launch_wait is not None:
            _, source, round_started = self.launch_wait
            if source != pos:
                self.launch_wait = None
        team = ct.get_team()
        titanium = ct.get_global_resources()
        reserve = construction_reserve(ct)
        for tile in self.memory.adjacent[pos]:
            if tile not in self.memory.visible or now < self.rejected_launchers.get(tile, 0):
                continue
            building = self.memory.buildings.get(tile)
            friendly_launcher = building is not None and building[1:] == (EntityType.LAUNCHER, team)
            can_build = (building is None and titanium >= reserve + ct.get_launcher_cost()
                         and ct.can_build_launcher(tile))
            if not friendly_launcher and not can_build:
                continue
            potential = ct.get_attackable_tiles_from(tile, Direction.CENTRE, EntityType.LAUNCHER)
            visible = (target for target in potential
                       if target in self.memory.visible and target not in self.memory.launch_zones)
            landings = landing_tiles(ct, pos, visible) if across else forward_landings(ct, pos, visible, goal)
            if not landings:
                continue
            if self.launch_wait is not None and self.launch_wait[0] == tile:
                if now - self.launch_wait[2] >= 10:
                    self.rejected_launchers[tile] = now + 24
                    self.launch_wait = None
                    continue
            else:
                self.launch_wait = tile, pos, now
            if can_build:
                ct.build_launcher(tile)
            ct.write_store(LAUNCH_BUILDER, ct.get_id())
            return True
        return False


class Player:
    def __init__(self):
        self.role = None

    def run(self, ct: Controller) -> None:
        kind = ct.get_entity_type()
        if kind in (EntityType.CORE, EntityType.BUILDER_BOT):
            if self.role is None:
                self.role = Core() if kind == EntityType.CORE else Builder()
            self.role.run(ct)
        elif kind == EntityType.LAUNCHER:
            run_launcher(ct)
        elif kind in TURRETS:
            run_turret(ct)
