from cambc import Controller, Direction, EntityType, Environment, GameConstants, Position

from finalbot.shared.bot import BaseBot
from finalbot.shared.constants import (
    AXIONITE_PIPELINE_ENABLED, AXIONITE_TITANIUM_THRESHOLD,
    BUILDER_DIRECTION_CODES, BUILDER_WORK_DIRECTIONS,
    MARKER_KIND_SECTOR_ORE_AX, MARKER_KIND_SECTOR_ORE_TI, ORE_TYPES,
)
from finalbot.core.deployment import CoreDeployment
from finalbot.economy.policy import fund_construction
from finalbot.combat.defense import core_threats
from finalbot.shared.intel import broadcast_threat
from finalbot.shared.geometry import encode_marker


class CoreBot(CoreDeployment, BaseBot):
    """Keeps four directional builders alive and gives each sector its ore order.

    A bot process has no shared memory with the core.  Sector markers close to
    the core therefore act as a small, persistent order board: a newborn
    builder reads the marker for the tile it was spawned from before it leaves
    the core footprint.
    """

    def __init__(self, map_width: int, map_height: int) -> None:
        """Initialize the core's map memory, sector orders, and marker board."""
        super().__init__(map_width, map_height)
        self.core_pos: Position | None = None
        self.known_env = self.tile_cache.environments
        self.known_buildings = self.tile_cache.buildings

        self.initial_spawned_directions: set[Direction] = set()
        self.replacement_direction_index = 0
        self.replacement_builders_spawned = 0
        self.last_builder_spawn_round = -128
        self.sector_targets: dict[Direction, tuple[Position, Environment]] = {}
        self.sector_marker_pads: dict[Direction, Position] = {}
        self.sector_marker_values: dict[Direction, int | None] = {}
        self.spawn_order_pad: Position | None = None
        self.spawn_order_active = False
        self.spawn_order_round: int | None = None
        self.spawn_order_position: Position | None = None
        self.marker_sync_cursor = 0
        self.economy_builder_ids: list[int] = []
        self.fleet_check_cursor = 0
        self.intruder_id: int | None = None
        self.intruder_ids = []
        self.intruders_spawned = 0
        self.intruder_spawn_round: int | None = None
        self.intruder_order_pad: Position | None = None
        self.intruder_order_active = False
        self.intruder_spawn_pos: Position | None = None
        self.defender_ids = []
        self.defender_order_pad = None
        self.defender_order_round = -10
        self.opening_directions = None

    def run(self, controller: Controller) -> None:
        """Observe the map, update sector orders, and maintain the economy fleet."""
        if self.entity_id is None:
            self.entity_id = controller.get_id()
            self.team = controller.get_team()
        if self.core_pos is None:
            self.core_pos = self.tile_cache.canonicalize(controller.get_position(self.entity_id))
            self.current_position = self.core_pos
        fund_construction(controller, self.entity_id)
        self.refresh_fleet(controller)
        self.clear_intruder_spawn_order(controller)
        self.clear_completed_spawn_order(controller)
        if self.defender_order_pad is not None and controller.get_current_round() > self.defender_order_round + 1:
            if self.retire_role_marker(controller, self.defender_order_pad):
                self.defender_order_pad = None
        # Establish forward pressure while the first mining sectors open.
        if not self.intruders_spawned and self.try_spawn_intruder(controller):
            return
        if len(self.economy_builder_ids) >= 2 and self.try_spawn_defender(controller):
            return
        if len(self.economy_builder_ids) >= 2 and self.intruders_spawned == 1:
            if self.try_spawn_intruder(controller):
                return
        # The first four cardinal spawn tiles encode their sectors directly.
        # They do not need the full vision cache or a marker handoff, so start
        # the economy while the comparatively expensive initial scan proceeds
        # on later turns.
        if len(self.initial_spawned_directions) < len(BUILDER_WORK_DIRECTIONS):
            if self.entity_id is None:
                self.entity_id = controller.get_id()
            if self.core_pos is None:
                self.core_pos = self.tile_cache.canonicalize(
                    controller.get_position(self.entity_id),
                )
                self.current_position = self.core_pos
            if self.try_spawn_missing_builder(controller):
                return
        if self.try_spawn_defender(controller):
            return
        broadcast_threat(self, controller, core_threats(self, controller))
        if self._scan_turn(controller):
            return
        self.observe_tiles()
        self.core_pos = self.get_cached_position()
        # The previous cache can predate an approaching builder. Act on the
        # completed observation before spending this turn on fleet expansion.
        if self.try_spawn_defender(controller):
            return
        if not self.sector_marker_pads:
            self.sector_marker_pads, self.spawn_order_pad = self.find_sector_marker_pads(controller)
            self.sector_marker_values = {
                direction: None for direction in self.sector_marker_pads
            }

        self.refresh_sector_targets(controller)
        spawned = self.try_spawn_missing_builder(controller)
        if not spawned:
            spawned = self.try_spawn_intruder(controller)
        if not spawned:
            self.clear_completed_spawn_order(controller)
            # Orders can change after a nearby harvester is built.  One marker
            # write per round is a game rule, so update the board round-robin.
            self.sync_one_changed_sector_marker(controller)


    def observe_tiles(self) -> None:
        """Refresh the core's local terrain and building observations."""
        # BaseBot has already refreshed these shared cache indexes.  This
        # method deliberately keeps the role-level observation boundary while
        # performing no additional Controller queries.
        return

    def find_sector_marker_pads(
            self,
            controller: Controller,
    ) -> tuple[dict[Direction, Position], Position | None]:
        """Choose safe tiles for sector orders and spawn handoff markers."""
        if self.core_pos is None:
            return {}, None

        # Corners of the core action radius do not obstruct the four cardinal
        # exits used by the builders.  The remaining entries are fallbacks for
        # maps where a corner contains a wall or ore.
        preferred_offsets = (
            (-2, -2), (2, -2), (2, 2), (-2, 2),
            (-2, 0), (0, -2), (2, 0), (0, 2),
        )
        offsets = list(preferred_offsets)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                if (
                    dx * dx + dy * dy <= GameConstants.CORE_ACTION_RADIUS_SQ
                    and (abs(dx) == 2 or abs(dy) == 2)
                    and (dx, dy) not in offsets
                ):
                    offsets.append((dx, dy))
        pads: list[Position] = []
        for dx, dy in offsets:
            pos = self.tile_cache.offset(self.core_pos, dx, dy)
            if (pos is None or pos in (self.intruder_order_pad, self.defender_order_pad,
                                       getattr(self, 'threat_report_pad', None))
                    or not controller.can_place_marker(pos)):
                continue
            pads.append(pos)
            if len(pads) == len(BUILDER_WORK_DIRECTIONS) + 1:
                break
        sector_pads = {
            direction: pad
            for direction, pad in zip(BUILDER_WORK_DIRECTIONS, pads[:len(BUILDER_WORK_DIRECTIONS)])
        }
        spawn_order_pad = pads[len(BUILDER_WORK_DIRECTIONS)] if len(pads) > len(BUILDER_WORK_DIRECTIONS) else None
        return sector_pads, spawn_order_pad

    def refresh_sector_targets(self, controller: Controller) -> None:
        """Assign each direction its nearest eligible observed ore deposit."""
        if self.core_pos is None:
            return

        # Ore remains ore beneath buildings. Completed mines and occupied
        # transport cells must leave the order board; roads can be cleared.
        for direction, target in list(self.sector_targets.items()):
            building = self.known_buildings.get(target[0])
            if building is not None and building[0] != EntityType.ROAD:
                del self.sector_targets[direction]

        titanium, _ = controller.get_global_resources()
        used_targets = {target[0] for target in self.sector_targets.values()}
        candidates: dict[Direction, list[tuple[Position, Environment]]] = {
            direction: [] for direction in BUILDER_WORK_DIRECTIONS
        }
        for pos, env in self.known_env.items():
            building = self.known_buildings.get(pos)
            if env not in ORE_TYPES or (building is not None and building[0] != EntityType.ROAD):
                continue
            if env == Environment.ORE_AXIONITE and (
                not AXIONITE_PIPELINE_ENABLED
                or titanium <= AXIONITE_TITANIUM_THRESHOLD
            ):
                continue
            candidates[self.sector_for(pos)].append((pos, env))

        for direction in BUILDER_WORK_DIRECTIONS:
            if direction in self.sector_targets:
                continue
            available = [target for target in candidates[direction] if target[0] not in used_targets]
            if not available:
                continue
            target = min(
                available,
                key=lambda item: (
                    self.core_distance(item[0]),
                    item[0].x,
                    item[0].y,
                ),
            )
            self.sector_targets[direction] = target
            used_targets.add(target[0])

    def sector_for(self, pos: Position) -> Direction:
        """Return the cardinal sector containing ``pos`` relative to the core."""
        if self.core_pos is None:
            return Direction.NORTH
        dx = pos.x - self.core_pos.x
        dy = pos.y - self.core_pos.y
        if abs(dy) >= abs(dx):
            return Direction.NORTH if dy < 0 else Direction.SOUTH
        return Direction.EAST if dx > 0 else Direction.WEST

    def core_distance(self, pos: Position) -> int:
        """Return the Chebyshev distance from the core to ``pos``."""
        if self.core_pos is None:
            return 0
        return max(abs(pos.x - self.core_pos.x), abs(pos.y - self.core_pos.y))

    def is_harvester_on_tile(self, pos: Position) -> bool:
        """Report whether the last observation shows a harvester at ``pos``."""
        building = self.known_buildings.get(pos)
        return building is not None and building[0] == EntityType.HARVESTER


    def desired_sector_marker_value(self, direction: Direction) -> int | None:
        """Encode the current ore order for one sector, if it has one."""
        target = self.sector_targets.get(direction)
        if target is None:
            return None
        pos, env = target
        kind = (
            MARKER_KIND_SECTOR_ORE_TI
            if env == Environment.ORE_TITANIUM
            else MARKER_KIND_SECTOR_ORE_AX
        )
        return encode_marker(kind, pos, BUILDER_DIRECTION_CODES[direction])

    def sync_one_changed_sector_marker(self, controller: Controller) -> None:
        """Synchronize one changed sector marker within the per-turn action limit."""
        directions = tuple(self.sector_marker_pads)
        if not directions:
            return
        for offset in range(len(directions)):
            index = (self.marker_sync_cursor + offset) % len(directions)
            direction = directions[index]
            if self.sector_marker_values.get(direction) == self.desired_sector_marker_value(direction):
                continue
            self.marker_sync_cursor = (index + 1) % len(directions)
            self.sync_sector_marker(controller, direction)
            return

    def sync_sector_marker(self, controller: Controller, direction: Direction) -> None:
        """Create, update, or remove the persistent marker for one sector."""
        pad = self.sector_marker_pads.get(direction)
        if pad is None:
            return
        desired = self.desired_sector_marker_value(direction)
        current = self.sector_marker_values.get(direction)
        if desired == current:
            return

        if desired is None:
            # Destruction is free and removes a completed mine from the order
            # board instead of leaving a stale target for a replacement bot.
            building_id = self.tile_cache.building_id_at(pad)
            building = self.tile_cache.building_at(pad)
            if building_id is not None and building is not None and building[0] == EntityType.MARKER:
                if building[1] == self.team and controller.can_destroy(pad):
                    controller.destroy(pad)
                    self.tile_cache.forget_building(pad)
            self.sector_marker_values[direction] = None
            return

        if controller.can_place_marker(pad):
            marker_id = controller.place_marker(pad, desired)
            self.tile_cache.remember_building(
                pad,
                marker_id,
                EntityType.MARKER,
                self.team,
                marker_value=desired,
            )
            self.sector_marker_values[direction] = desired
