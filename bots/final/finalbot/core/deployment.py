"""Core deployment and short-lived, addressed role assignments.

The core owns strategic priorities; this module handles unit quotas, live
construction reserves, safe spawn tiles and marker handoffs.
"""

from cambc import Controller, Direction, EntityType, Environment, GameConstants, Position

from finalbot.shared.constants import (
    BUILDER_DIRECTION_CODES,
    BUILDER_WORK_DIRECTIONS,
    ECONOMY_EXPANSION_INTERVAL_ROUNDS,
    ECONOMY_EXPANSION_START_ROUND,
    MARKER_KIND_SPAWN_DIRECTION,
    MAX_ADDITIONAL_BUILDER_SPAWNS,
    MAX_ECONOMY_BUILDERS,
    MARKER_KIND_SPAWN_INTRUDER,
    MARKER_KIND_SPAWN_DEFENDER,
    MAX_INTRUDER_SPAWNS,
    INTRUDER_REPLACEMENT_INTERVAL,
)
from finalbot.combat.defense import core_defender_demand
from finalbot.economy.policy import attack_force_budget, desired_builder_count
from finalbot.core.fleet import unit_is_alive
from finalbot.shared.geometry import encode_marker
from finalbot.economy.orders import spawn_needs_handoff

MARKER_OFFSETS = (
    (-2, -2), (2, -2), (2, 2), (-2, 2),
    (-2, 0), (0, -2), (2, 0), (0, 2),
    (-2, -1), (-2, 1), (2, -1), (2, 1),
    (-1, -2), (1, -2), (-1, 2), (1, 2),
)


class CoreDeployment:
    def retire_role_marker(self, controller, pad):
        """A handoff replaced by construction has already been retired."""
        read_id = getattr(controller, 'get_tile_building_id', None)
        if read_id is not None:
            entity_id = read_id(pad)
            if (entity_id is None or controller.get_entity_type(entity_id) != EntityType.MARKER
                    or controller.get_team(entity_id) != self.team):
                return True
        if not controller.can_destroy(pad):
            return False
        controller.destroy(pad)
        self.tile_cache.forget_building(pad)
        return True

    def refresh_fleet(self, controller: Controller) -> None:
        """Check one spawned unit per turn, keeping API work bounded."""
        roster = list(self.economy_builder_ids)
        roster.extend(self.defender_ids)
        roster.extend(self.intruder_ids)
        if self.intruder_id is not None and self.intruder_id not in roster:
            roster.append(self.intruder_id)
        if not roster:
            return
        entity_id = roster[self.fleet_check_cursor % len(roster)]
        self.fleet_check_cursor += 1
        if unit_is_alive(controller, entity_id):
            return
        if entity_id in self.intruder_ids or entity_id == self.intruder_id:
            if entity_id in self.intruder_ids:
                self.intruder_ids.remove(entity_id)
            if entity_id == self.intruder_id:
                self.intruder_id = None
        elif entity_id in self.defender_ids:
            self.defender_ids.remove(entity_id)
        else:
            self.economy_builder_ids.remove(entity_id)

    def clear_intruder_spawn_order(self, controller: Controller) -> None:
        """Retire the role handoff before another newborn can use its tile."""
        if not self.intruder_order_active:
            return
        if controller.get_current_round() <= self.intruder_spawn_round + 1:
            return
        if self.retire_role_marker(controller, self.intruder_order_pad):
            self.intruder_order_active = False

    def try_spawn_missing_builder(self, controller: Controller) -> bool:
        """Spawn one missing directional builder, with a safe fallback tile."""
        if self.core_pos is None or controller.get_unit_count() >= GameConstants.MAX_TEAM_UNITS:
            return False
        # Turrets and intruders must never occupy the economy's worker quota.
        # The roster is checked incrementally even after workers leave vision.
        living_builders = len(self.economy_builder_ids)
        # Two profitable sectors finance expansion. Four simultaneous scouts
        # otherwise spend the opening bank before either conveyor is complete.
        if living_builders >= 2:
            money = controller.get_global_resources()[0]
            reserve = controller.get_builder_bot_cost()[0] + controller.get_harvester_cost()[0] + 4 * controller.get_conveyor_cost()[0]
            expansion_round = 30 + 30 * (living_builders - 2)
            if money < 500 and (controller.get_current_round() < expansion_round or money < reserve):
                return False
        desired_builders = desired_builder_count(
            controller.get_current_round(),
            len(BUILDER_WORK_DIRECTIONS),
            MAX_ECONOMY_BUILDERS,
            ECONOMY_EXPANSION_START_ROUND,
            ECONOMY_EXPANSION_INTERVAL_ROUNDS,
        )
        if living_builders >= desired_builders:
            return False

        if len(self.initial_spawned_directions) < len(BUILDER_WORK_DIRECTIONS):
            if self.opening_directions is None:
                distances = {d: self.map_width + self.map_height for d in BUILDER_WORK_DIRECTIONS}
                for pos in controller.get_nearby_tiles():
                    if controller.get_tile_env(pos) == Environment.ORE_TITANIUM:
                        d = self.sector_for(pos)
                        distances[d] = min(distances[d], self.core_distance(pos))
                self.opening_directions = sorted(BUILDER_WORK_DIRECTIONS, key=lambda d: distances[d])
            directions = [
                direction
                for direction in self.opening_directions
                if direction not in self.initial_spawned_directions
            ]
        else:
            if self.replacement_builders_spawned >= MAX_ADDITIONAL_BUILDER_SPAWNS:
                # The normal cap limits recycling, but must not leave the core
                # without any worker for the rest of the match.
                if controller.get_current_round() - self.last_builder_spawn_round < 128:
                    return False
            direction = BUILDER_WORK_DIRECTIONS[
                self.replacement_direction_index % len(BUILDER_WORK_DIRECTIONS)
            ]
            directions = [direction]

        fallback_positions = [
            pos
            for dx, dy in (
                (0, 0), (1, -1), (1, 1), (-1, 1), (-1, -1),
                (0, -1), (1, 0), (0, 1), (-1, 0),
            )
            if (pos := self.tile_cache.offset(self.core_pos, dx, dy)) is not None
        ]
        for direction in directions:
            preferred = self.tile_cache.neighbor(self.core_pos, direction)
            if preferred is None:
                continue
            positions = [preferred]
            if self.spawn_order_pad is not None:
                positions.extend(pos for pos in fallback_positions if pos != preferred)
            for spawn_pos in positions:
                if self.intruder_order_active and spawn_pos == self.intruder_spawn_pos:
                    continue
                if self.spawn_order_active and spawn_pos == self.spawn_order_position:
                    continue
                if not controller.can_spawn(spawn_pos):
                    continue
                needs_handoff = spawn_needs_handoff(spawn_pos, preferred)
                # Only a fallback tile is ambiguous.  Cardinal spawns derive
                # their sector from their position and must not pay a marker
                # action or leave a temporary building beside the Core.
                if needs_handoff and not self.write_spawn_order(
                    controller,
                    direction,
                    spawn_pos,
                ):
                    continue
                builder_id = controller.spawn_builder(spawn_pos)
                self.economy_builder_ids.append(builder_id)
                self.last_builder_spawn_round = controller.get_current_round()
                if len(self.initial_spawned_directions) < len(BUILDER_WORK_DIRECTIONS):
                    self.initial_spawned_directions.add(direction)
                else:
                    self.replacement_direction_index = (
                        self.replacement_direction_index + 1
                    ) % len(BUILDER_WORK_DIRECTIONS)
                    self.replacement_builders_spawned += 1
                return True
        return False

    def write_spawn_order(
            self,
            controller: Controller,
            direction: Direction,
            spawn_pos: Position,
    ) -> bool:
        """Write the sector only when a fallback spawn tile is ambiguous."""
        if self.spawn_order_pad is None:
            return False
        if self.spawn_order_pad == self.defender_order_pad or (
                self.intruder_order_active and self.spawn_order_pad == self.intruder_order_pad):
            return False
        value = encode_marker(
            MARKER_KIND_SPAWN_DIRECTION,
            spawn_pos,
            BUILDER_DIRECTION_CODES[direction],
        )
        if not controller.can_place_marker(self.spawn_order_pad):
            return False
        marker_id = controller.place_marker(self.spawn_order_pad, value)
        self.tile_cache.remember_building(
            self.spawn_order_pad,
            marker_id,
            EntityType.MARKER,
            self.team,
            marker_value=value,
        )
        self.spawn_order_active = True
        self.spawn_order_round = controller.get_current_round()
        self.spawn_order_position = spawn_pos
        return True

    def clear_completed_spawn_order(self, controller: Controller) -> None:
        """Remove the temporary fallback handoff after the newborn has read it."""
        if self.spawn_order_pad is None or not self.spawn_order_active:
            return
        if controller.get_current_round() <= self.spawn_order_round + 1:
            return
        if self.retire_role_marker(controller, self.spawn_order_pad):
            self.spawn_order_active = False

    def find_first_intruder_order_pad(self, controller: Controller) -> Position | None:
        """Pick one usable marker pad without scanning terrain or entities."""
        if self.core_pos is None:
            return None
        for dx, dy in MARKER_OFFSETS:
            pad = self.tile_cache.offset(self.core_pos, dx, dy)
            if pad in (self.spawn_order_pad, self.defender_order_pad) or pad in self.sector_marker_pads.values():
                continue
            if pad is not None and controller.can_place_marker(pad):
                return pad
        return None

    def find_defender_order_pad(self, controller):
        """Use the complete action ring and reclaim an idle board if crowded."""
        active = {self.defender_order_pad}
        if self.intruder_order_active:
            active.add(self.intruder_order_pad)
        if self.spawn_order_active:
            active.add(self.spawn_order_pad)
        boards = set(self.sector_marker_pads.values())
        candidates = [pad for dx, dy in MARKER_OFFSETS
                      if (pad := self.tile_cache.offset(self.core_pos, dx, dy)) is not None
                      and pad not in active]
        candidates.sort(key=lambda pad: pad in boards)
        for pad in candidates:
            if not controller.can_place_marker(pad):
                continue
            # Sector reports are hints; a live role assignment takes priority
            # when terrain leaves too few pads to maintain a full order board.
            for direction, board in list(self.sector_marker_pads.items()):
                if board == pad:
                    del self.sector_marker_pads[direction]
                    self.sector_marker_values.pop(direction, None)
            return pad
        return None

    def try_spawn_defender(self, controller):
        """Reserve repairs before a short-range battery can burn through 500 HP."""
        hp = controller.get_hp(self.entity_id)
        desired = core_defender_demand(self, controller)
        if len(self.defender_ids) >= desired or self.defender_order_pad is not None:
            return False
        reserve = 60 if hp >= 490 else 4
        if controller.get_global_resources()[0] < controller.get_builder_bot_cost()[0] + reserve and hp > 160:
            return False
        if controller.get_unit_count() >= GameConstants.MAX_TEAM_UNITS:
            return False
        pad = self.find_defender_order_pad(controller)
        if pad is None:
            return False
        for dx, dy in ((0, 0), (-1, -1), (1, 1), (-1, 1), (1, -1), (0, -1), (0, 1), (-1, 0), (1, 0)):
            pos = self.tile_cache.offset(self.core_pos, dx, dy)
            if pos is not None and controller.can_spawn(pos):
                controller.place_marker(pad, encode_marker(MARKER_KIND_SPAWN_DEFENDER, pos))
                self.defender_ids.append(controller.spawn_builder(pos))
                self.defender_order_pad = pad
                self.defender_order_round = controller.get_current_round()
                return True
        return False

    def core_receiver_positions(self):
        return [self.tile_cache.offset(self.core_pos, dx, dy)
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if self.tile_cache.offset(self.core_pos, dx, dy) is not None]

    def try_spawn_intruder(self, controller: Controller) -> bool:
        """Spawn the first non-Core unit as an infiltrator with an identifying marker."""
        now = controller.get_current_round()
        titanium, _ = controller.get_global_resources()
        desired, replacement_interval, funded_reinforcements = attack_force_budget(
            now, titanium, INTRUDER_REPLACEMENT_INTERVAL,
        )
        if (
            self.core_pos is None
            or len(self.intruder_ids) >= desired
            or self.intruder_order_active
            or (self.intruders_spawned >= MAX_INTRUDER_SPAWNS and not funded_reinforcements)
            or controller.get_unit_count() >= GameConstants.MAX_TEAM_UNITS
        ):
            return False

        if self.intruders_spawned:
            opening_partner = self.intruders_spawned == 1 and bool(self.intruder_ids)
            # Keep the opening construction bank for profitable mine outlets
            # and the core crew; a second expedition needs established income.
            interval = (3 if titanium >= 750 else 64) if opening_partner else replacement_interval
            if now - self.intruder_spawn_round < interval:
                return False
            reserve = controller.get_harvester_cost()[0] + 8 * controller.get_conveyor_cost()[0]
            if titanium < controller.get_builder_bot_cost()[0] + reserve:
                return False
        if self.intruder_order_pad is None or self.intruder_order_pad == self.defender_order_pad or not controller.can_place_marker(self.intruder_order_pad):
            self.intruder_order_pad = self.find_first_intruder_order_pad(controller)
        if self.intruder_order_pad is None:
            return False
        target = self.tile_cache.position_at(
            self.map_width - 1 - self.core_pos.x,
            self.map_height - 1 - self.core_pos.y,
        )
        if target is None:
            return False
        preferred_direction = self.core_pos.direction_to(target)
        fallback_positions = [
            pos
            for dx, dy in (
                (0, 0), (1, -1), (1, 1), (-1, 1), (-1, -1),
                (0, -1), (1, 0), (0, 1), (-1, 0),
            )
            if (pos := self.tile_cache.offset(self.core_pos, dx, dy)) is not None
        ]
        preferred = self.tile_cache.neighbor(self.core_pos, preferred_direction)
        positions = (
            [] if preferred is None else [preferred]
        ) + [pos for pos in fallback_positions if pos != preferred]
        for spawn_pos in positions:
            if not controller.can_spawn(spawn_pos):
                continue
            if not self.write_intruder_spawn_order(controller, spawn_pos):
                return False
            self.intruder_id = controller.spawn_builder(spawn_pos)
            self.intruder_ids.append(self.intruder_id)
            self.intruders_spawned += 1
            self.intruder_order_active = True
            self.intruder_spawn_pos = spawn_pos
            self.intruder_spawn_round = controller.get_current_round()
            return True
        return False

    def write_intruder_spawn_order(self, controller: Controller, spawn_pos: Position) -> bool:
        """Mark ``spawn_pos`` so its newborn BuilderBot selects IntruderBot logic."""
        if self.intruder_order_pad is None or not controller.can_place_marker(self.intruder_order_pad):
            return False
        value = encode_marker(MARKER_KIND_SPAWN_INTRUDER, spawn_pos)
        marker_id = controller.place_marker(self.intruder_order_pad, value)
        # The forced first-turn spawn deliberately happens before terrain has
        # entered the cache.  The marker will be indexed by the later normal
        # scan; do not fabricate an environment just to cache it now.
        if self.tile_cache.environment_at(self.intruder_order_pad) is not None:
            self.tile_cache.remember_building(
                self.intruder_order_pad,
                marker_id,
                EntityType.MARKER,
                self.team,
                marker_value=value,
            )
        return True

