"""Terrain, ore reports and home-core observations."""

from cambc import Controller, EntityType, Environment, Position
from finalbot.shared.constants import (
    BUILDER_CODE_DIRECTIONS,
    DIRECTIONS,
    MARKER_KIND_ORE_AX,
    MARKER_KIND_ORE_TI,
    MARKER_KIND_SECTOR_ORE_AX,
    MARKER_KIND_SECTOR_ORE_TI,
    MARKER_KIND_SPAWN_DIRECTION,
    MARKER_KIND_SPAWN_ORE_AX,
    MARKER_KIND_SPAWN_ORE_TI,
    ORE_TYPES,
    ORTHOGONAL_DIRECTIONS,
    PASSABLE_BUILDINGS,
    TRANSPORT_BUSY_SAMPLE_LIMIT,
)
from finalbot.shared.geometry import decode_marker
from finalbot.economy.orders import spawn_order_for


class BuilderObservation:
    """Uses state initialized by BuilderBot."""

    def observe_tiles(self, controller: Controller) -> None:
        """Refresh known terrain, buildings, conveyor directions, and scout frontier."""
        network_changed = False
        busy_candidates: list[tuple[int, Position, int]] = []
        current = self.get_cached_position()
        for pos in self.tile_cache.visible_tiles:
            self.inferred_ores.pop(pos, None)
            self.reported_ores.pop(pos, None)
            building = self.known_buildings.get(pos)
            building_id = self.tile_cache.building_id_at(pos)
            if building is not None and building[0] == EntityType.BRIDGE:
                if building_id is not None and self.known_bridge_ids.get(pos) != building_id:
                    self.known_bridge_targets[pos] = controller.get_bridge_target(building_id)
                    self.known_bridge_ids[pos] = building_id
            else:
                self.known_bridge_targets.pop(pos, None)
                self.known_bridge_ids.pop(pos, None)

            transport_state = None
            if (
                building is not None
                and building[1] == self.team
                and building[0] in {
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                    EntityType.BRIDGE,
                }
            ):
                transport_state = (
                    building[0],
                    self.known_conveyor_directions.get(pos),
                    self.known_bridge_targets.get(pos),
                )
            previous_state = self.observed_network_state.get(pos)
            if previous_state != transport_state and (
                previous_state is not None or transport_state is not None
            ):
                network_changed = True
            self.observed_network_state[pos] = transport_state

            self.network_memory.audit(
                pos,
                None if building is None else building[0],
                building is not None and building[1] == self.team,
                self.known_conveyor_directions.get(pos),
                self.known_bridge_targets.get(pos),
            )

            if (
                building is not None
                and building[1] == self.team
                and building[0] in {
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                    EntityType.BRIDGE,
                }
                and building_id is not None
            ):
                if pos not in self.network_blueprint:
                    self.network_memory.remember(
                        pos,
                        building[0],
                        self.known_conveyor_directions.get(pos),
                        self.known_bridge_targets.get(pos),
                    )
                # Stored-resource reads are one of the expensive controller
                # calls.  Structural source counts handle normal capacity;
                # sample only the nearest transport to spot a persistently
                # full merge without inspecting the entire visible network.
                busy_candidates.append((current.distance_squared(pos), pos, building_id))
        busy_candidates.sort(key=lambda item: (item[0], item[1].x, item[1].y))
        for _, pos, building_id in busy_candidates[:TRANSPORT_BUSY_SAMPLE_LIMIT]:
            self.network_memory.record_busy(
                pos,
                controller.get_stored_resource(building_id) is not None,
            )
        if network_changed:
            self.connected_network_cache = None
        for pos in self.tile_cache.newly_observed_tiles:
            env = self.known_env[pos]
            self.update_scout_frontier(pos)
            if env in ORE_TYPES:
                self.infer_symmetric(pos, env)

    def read_ore_markers(self) -> None:
        """Read core orders and shared ore hints from nearby marker buildings."""
        records: list[tuple[int, Position, int]] = []
        for entity_id in self.tile_cache.marker_ids():
            marker_value = self.tile_cache.marker_values.get(entity_id)
            if marker_value is None:
                continue
            try:
                kind, pos, payload = decode_marker(
                    marker_value,
                    self.tile_cache.position_at,
                )
            except Exception:
                continue
            records.append((kind, pos, payload))

        # A newly created builder has no durable memory yet.  The core writes
        # one handoff marker in the same round as spawn, which is necessary
        # when a map edge forces it to use a non-cardinal core tile.
        if self.work_direction is None:
            current = self.get_cached_position()
            order = spawn_order_for(
                records,
                current,
                {
                    MARKER_KIND_SPAWN_DIRECTION,
                    MARKER_KIND_SPAWN_ORE_TI,
                    MARKER_KIND_SPAWN_ORE_AX,
                },
                BUILDER_CODE_DIRECTIONS,
            )
            if order is not None:
                kind, pos, direction = order
                self.work_direction = direction
                if kind == MARKER_KIND_SPAWN_ORE_TI:
                    self.assigned_ores[pos] = Environment.ORE_TITANIUM
                elif kind == MARKER_KIND_SPAWN_ORE_AX:
                    self.assigned_ores[pos] = Environment.ORE_AXIONITE

        if self.work_direction is None and self.spawn_direction in ORTHOGONAL_DIRECTIONS:
            self.work_direction = self.spawn_direction

        for kind, pos, payload in records:
            if kind == MARKER_KIND_ORE_TI and pos not in self.observed_tiles:
                self.reported_ores[pos] = Environment.ORE_TITANIUM
            elif kind == MARKER_KIND_ORE_AX and pos not in self.observed_tiles:
                self.reported_ores[pos] = Environment.ORE_AXIONITE
            elif (
                kind in {MARKER_KIND_SECTOR_ORE_TI, MARKER_KIND_SECTOR_ORE_AX}
                and self.work_direction is not None
                and BUILDER_CODE_DIRECTIONS.get(payload) == self.work_direction
            ):
                # Unlike a symmetry hint, a sector order comes from a core
                # that has directly observed the ore.  It is therefore a real
                # mining target even before this builder sees the tile itself.
                self.assigned_ores[pos] = (
                    Environment.ORE_TITANIUM
                    if kind == MARKER_KIND_SECTOR_ORE_TI
                    else Environment.ORE_AXIONITE
                )

    def infer_symmetric(self, pos: Position, env: Environment) -> None:
        """Record an ore hint only after the cache proves map symmetry."""
        mirror = self.tile_cache.mirrored_position(pos)
        if mirror is not None and mirror not in self.observed_tiles:
            self.inferred_ores[mirror] = env

    def update_scout_frontier(self, known_pos: Position) -> None:
        """Update unknown boundary cells adjacent to a newly known tile."""
        self.scout_frontier_initialized = True
        self.scout_frontier.discard(known_pos)
        # A wall cannot be the known side of an exploration edge.
        # Adding all of its unknown neighbours creates phantom frontiers behind
        # solid barriers, which repeatedly win the sector score but have no
        # legal route from the explored component.
        env = self.known_env.get(known_pos)
        building = self.known_buildings.get(known_pos)
        if (
            env == Environment.WALL
            or (building is not None and building[0] not in PASSABLE_BUILDINGS)
            or (
                building is not None
                and building[0] == EntityType.CORE
                and building[1] != self.team
            )
        ):
            return
        for direction in DIRECTIONS:
            probe = self.tile_cache.neighbor(known_pos, direction)
            if probe is None:
                continue
            if probe in self.observed_tiles:
                self.scout_frontier.discard(probe)
            else:
                self.scout_frontier.add(probe)

    def rebuild_scout_frontier(self) -> None:
        """Reconstruct the exploration frontier from all observed tiles."""
        for known_pos in self.observed_tiles:
            self.update_scout_frontier(known_pos)

    def find_home_core(self) -> Position | None:
        """Locate the friendly core while it is within local vision."""
        for entity_id in self.tile_cache.visible_entity_ids:
            if (
                self.tile_cache.entity_type(entity_id) == EntityType.CORE
                and self.tile_cache.entity_team(entity_id) == self.team
            ):
                return self.tile_cache.entity_position(entity_id)
        return None

    def known_titanium_ores(self) -> list[Position]:
        """Return all directly observed titanium deposits."""
        return [pos for pos, env in self.known_env.items() if env == Environment.ORE_TITANIUM]

    def known_axionite_ores(self) -> list[Position]:
        """Return all directly observed axionite deposits."""
        return [pos for pos, env in self.known_env.items() if env == Environment.ORE_AXIONITE]

    def resource_at(self, pos: Position) -> Environment | None:
        """Return the observed or core-assigned ore type at ``pos``."""
        return self.known_env.get(pos) or self.assigned_ores.get(pos)
