"""Build, repair and retire the transport owned by this worker."""

from cambc import Controller, Direction, EntityType, GameConstants, Position
from finalbot.shared.constants import DIRECTIONS


class BuilderConstruction:
    """Uses state initialized by BuilderBot."""

    def clear_ore_road(self, controller: Controller, current: Position) -> bool:
        """Reclaim a road-covered deposit instead of waiting for a legal mine.

        Builders can attack hostile roads only from the road itself. Once it
        is gone, leave the deposit so a harvester can occupy the tile.
        """
        ore = self.target_ore
        if ore is None or current.distance_squared(ore) > GameConstants.ACTION_RADIUS_SQ:
            return False
        building = self.tile_cache.building_at(ore)
        if building is not None:
            if building[0] != EntityType.ROAD:
                return False
            if building[1] == self.team:
                if controller.can_destroy(ore):
                    controller.destroy(ore)
                    self.tile_cache.forget_building(ore)
            elif current != ore:
                direction = current.direction_to(ore)
                if controller.can_move(direction):
                    controller.move(direction)
                    return True
                return False
            else:
                if controller.can_fire(ore):
                    road_id = self.tile_cache.building_id_at(ore)
                    hp = controller.get_hp(road_id)
                    controller.fire(ore)
                    if hp <= GameConstants.BUILDER_BOT_ATTACK_DAMAGE:
                        self.tile_cache.forget_building(ore)
                    self.last_progress_round = self.rounds_alive
                return True
        if current == ore:
            for direction in DIRECTIONS:
                tile = self.tile_cache.neighbor(current, direction)
                if tile is not None and self.is_cached_tile_passable(tile) and controller.can_move(direction):
                    controller.move(direction)
                    return True
            return True
        return False

    def try_repair_nearby_network(self, controller: Controller, current: Position) -> bool:
        """Restore a visible broken transport tile before extending the network.

        Empty or friendly-road damage is repaired immediately.  Hostile
        conveyors are deliberately not fought for ten turns here: the
        connection planner treats them as blocks and may bridge around them.
        """
        candidates = sorted(
            (
                pos for pos in self.damaged_network_tiles
                if current.distance_squared(pos) <= GameConstants.ACTION_RADIUS_SQ
                and pos not in getattr(self, 'threatened_transport_tiles', ())
            ),
            key=lambda pos: (self.core_distance(pos), pos.x, pos.y),
        )
        for pos in candidates:
            expected = self.network_blueprint.get(pos)
            if expected is None:
                self.damaged_network_tiles.discard(pos)
                continue
            building = self.known_buildings.get(pos)
            if building is not None:
                if (
                    building[0] == EntityType.ROAD
                    and building[1] == self.team
                    and controller.can_destroy(pos)
                ):
                    controller.destroy(pos)
                    self.tile_cache.forget_building(pos)
                    self.connected_network_cache = None
                    return True
                # An enemy rewrite or incompatible allied transport is fed
                # back to the capacity planner as an obstacle; a detour/bridge
                # is cheaper and faster than repeatedly firing at it.
                continue

            entity_type, direction, bridge_target = expected
            if entity_type == EntityType.BRIDGE and bridge_target is not None:
                if not controller.can_build_bridge(pos, bridge_target):
                    continue
                entity_id = controller.build_bridge(pos, bridge_target)
                self.tile_cache.remember_building(
                    pos,
                    entity_id,
                    EntityType.BRIDGE,
                    self.team,
                )
                self.known_bridge_targets[pos] = bridge_target
                self.known_bridge_ids[pos] = entity_id
            elif (
                entity_type in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
                and direction is not None
                and controller.can_build_conveyor(pos, direction)
            ):
                entity_id = controller.build_conveyor(pos, direction)
                self.tile_cache.remember_building(
                    pos,
                    entity_id,
                    EntityType.CONVEYOR,
                    self.team,
                    direction=direction,
                )
                # Armoured tiles are restored as ordinary conveyors when
                # titanium is available but axionite is not; continuity wins.
                self.network_memory.remember(pos, EntityType.CONVEYOR, direction)
            else:
                continue
            self.damaged_network_tiles.discard(pos)
            self.connected_network_cache = None
            self.last_progress_round = self.rounds_alive
            return True
        return False

    def cleanup_abandoned_network(self, controller: Controller, current: Position) -> None:
        """Destroy only this builder's obsolete, disconnected branch tiles.

        Allied destruction is free and has no action cooldown.  Cleanup may
        therefore run before ordinary work without delaying a build or move.
        Connected tiles and tiles adopted by a fresh plan are rescued first.
        """
        candidates = self.network_memory.actionable_abandoned_tiles(
            self.known_connected_network(),
            self.conveyor_path_tiles,
        )
        for pos in sorted(candidates, key=lambda tile: (tile.x, tile.y)):
            if (
                pos not in self.tile_cache.visible_tiles
                or current.distance_squared(pos) > GameConstants.ACTION_RADIUS_SQ
            ):
                continue
            building = self.known_buildings.get(pos)
            if (
                building is None
                or building[1] != self.team
                or building[0] not in {
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                    EntityType.BRIDGE,
                }
            ):
                self.network_memory.forget(pos)
                self.owned_network_tiles.discard(pos)
                self.active_line_tiles.discard(pos)
                continue
            if not controller.can_destroy(pos):
                continue
            controller.destroy(pos)
            self.network_memory.forget(pos)
            self.tile_cache.forget_building(pos)
            self.known_bridge_targets.pop(pos, None)
            self.known_bridge_ids.pop(pos, None)
            self.owned_network_tiles.discard(pos)
            self.active_line_tiles.discard(pos)
            self.connected_network_cache = None

    def follow_path_and_build(self, controller: Controller) -> None:
        """Advance along the active path, constructing branch conveyors when required."""
        current = self.get_cached_position()
        if self.scout_target is not None and self.scout_target_direct:
            self.follow_direct_scout_target(controller, current)
            return
        # The current tile may itself be part of the committed outlet. Build
        # it before consuming the path node, so source activation at the end
        # cannot leave a missing first conveyor beside the ore.
        if (
            self.target_is_connection
            and current in self.conveyor_path_tiles
            and not self.bridge_build_is_deferred(current)
        ):
            if self.ensure_tree_conveyor(controller, current):
                return
            if not self.has_expected_tree_conveyor(controller, current):
                self.replan_or_wait_for_connection_tile(controller, current)
                return
        while self.path_index < len(self.path) and current == self.path[self.path_index]:
            self.path_index += 1
        if self.path_index >= len(self.path):
            if self.scout_target is not None:
                if current == self.scout_target:
                    self.scout_target = None
                else:
                    self.reject_scout_target(self.scout_target)
                    self.select_new_target(controller)
            elif self.target_ore is not None:
                if self.target_is_connection:
                    if not self.is_harvester_on_tile(self.target_ore):
                        if self.harvester_is_connected(self.target_ore) and controller.can_build_harvester(self.target_ore):
                            entity_id = controller.build_harvester(self.target_ore)
                            self.record_harvester_built(self.target_ore, entity_id)
                        else:
                            self.replan_after_yield = True
                        return
                    if not self.harvester_is_connected(self.target_ore):
                        if self.replan_active_ore_target(controller):
                            return
                        self.replan_after_yield = True
                        return
                    else:
                        self.pending_network_ores.discard(self.target_ore)
                        if (
                            self.connection_anchor is not None
                            and self.is_core_receiver_tile(self.connection_anchor)
                        ):
                            self.dedicated_line_committed = True
                        self.network_memory.complete_owned_branch()
                self.clear_ore_target()
                self.select_new_target(controller)
            return

        next_pos = self.path[self.path_index]
        direction = current.direction_to(next_pos)
        if direction == Direction.CENTRE:
            self.path_index += 1
            return
        if current.distance_squared(next_pos) > 2:
            if self.target_is_connection:
                self.schedule_replan_after_yield()
                return
            self.select_new_target(controller)
            return
        if (
            self.target_is_connection
            and next_pos in self.conveyor_path_tiles
            and not self.bridge_build_is_deferred(next_pos)
        ):
            if self.is_enemy_road(next_pos):
                if controller.can_move(direction):
                    controller.move(direction)
                return
            if self.ensure_tree_conveyor(controller, next_pos):
                return
            if not self.has_expected_tree_conveyor(controller, next_pos):
                self.replan_or_wait_for_connection_tile(controller, next_pos)
                return
        if not self.is_cached_tile_passable(next_pos):
            self.try_prepare_tile(controller, next_pos)
        if controller.can_move(direction):
            controller.move(direction)
        elif not self.is_cached_tile_passable(next_pos):
            self.replan_after_blocked_step(controller, next_pos)

    def bridge_build_is_deferred(self, pos: Position) -> bool:
        """Leave planned transport inactive until its downstream path is live."""
        if pos in self.conveyor_path_tiles:
            receiver = self.bridge_targets.get(pos)
            if receiver is None:
                direction = self.conveyor_directions.get(pos)
                receiver = None if direction is None else self.tile_cache.neighbor(pos, direction)
            if receiver not in self.known_connected_network():
                return True
        return (
            pos in self.deferred_bridge_sources
            and self.path_index < self.bridge_activation_path_index
        )

    def ensure_tree_conveyor(self, controller: Controller, target: Position) -> bool:
        """Build or safely reuse the planned conveyor or bridge at a branch tile."""
        planned_bridge_target = self.bridge_targets.get(target)
        conveyor_direction = self.get_conveyor_direction(target)
        building_id = self.tile_cache.building_id_at(target)
        building = self.tile_cache.building_at(target)
        if building_id is not None and building is not None:
            if (
                planned_bridge_target is not None
                and building[0] == EntityType.BRIDGE
                and building[1] == self.team
                and self.known_bridge_targets.get(target) == planned_bridge_target
            ):
                return False
            building_type, building_team = building
            if (
                planned_bridge_target is None
                and building_type in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
                and building_team == self.team
                and self.tile_cache.entity_direction(building_id) == conveyor_direction
            ):
                self.known_conveyor_directions[target] = conveyor_direction
                return False
            if building_type == EntityType.ROAD and building_team != self.team:
                # Enemy logistics can be attacked only from the occupied tile.
                # The movement branch below deliberately steps onto the road;
                # spend as many actions as its remaining HP requires, then lay
                # the saved conveyor direction without abandoning the route.
                if target != self.get_cached_position() or not controller.can_fire(target):
                    return False
                remaining_hp = controller.get_hp(building_id)
                controller.fire(target)
                if remaining_hp <= GameConstants.BUILDER_BOT_ATTACK_DAMAGE:
                    self.tile_cache.forget_building(target)
                self.last_progress_round = self.rounds_alive
                return True
            if building_type == EntityType.MARKER:
                # Order-board markers are deliberately reserved cells.
                self.permanently_blocked.add(target)
                return False
            if (
                building_type == EntityType.ROAD
                and building_team == self.team
                and controller.can_destroy(target)
            ):
                controller.destroy(target)
                self.tile_cache.forget_building(target)
                self.connected_network_cache = None
                building = None
            elif (
                building_type in {
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                    EntityType.BRIDGE,
                }
                and building_team == self.team
                and target in self.unfinished_branch_tiles
                and target not in self.known_connected_network()
                and controller.can_destroy(target)
            ):
                # This tile is being deliberately repointed by the active
                # connection plan.  Remove the stale direction first so the
                # repair pass cannot recreate it on the following turn.
                self.network_memory.forget(target)
                controller.destroy(target)
                self.tile_cache.forget_building(target)
                self.connected_network_cache = None
                building = None
            if building is not None:
                return False

        if planned_bridge_target is not None:
            # Bridges cannot be erected under a builder.  Normally they are
            # built from the preceding path tile; this fallback steps aside if
            # a replan starts while already standing on the bridge source.
            if self.get_cached_position() == target:
                for direction in DIRECTIONS:
                    if controller.can_move(direction):
                        controller.move(direction)
                        return True
                return False
            if not controller.can_build_bridge(target, planned_bridge_target):
                return False
            bridge_id = controller.build_bridge(target, planned_bridge_target)
            self.tile_cache.remember_building(
                target,
                bridge_id,
                EntityType.BRIDGE,
                self.team,
            )
            self.known_bridge_targets[target] = planned_bridge_target
            self.known_bridge_ids[target] = bridge_id
            self.network_blueprint[target] = (
                EntityType.BRIDGE,
                None,
                planned_bridge_target,
            )
            self.owned_network_tiles.add(target)
            self.active_line_tiles.add(target)
            self.network_memory.record_unfinished_owned_tile(target)
            self.connected_network_cache = None
            self.last_progress_round = self.rounds_alive
            return True

        if controller.can_build_conveyor(target, conveyor_direction):
            conveyor_id = controller.build_conveyor(target, conveyor_direction)
            self.tile_cache.remember_building(
                target,
                conveyor_id,
                EntityType.CONVEYOR,
                self.team,
                direction=conveyor_direction,
            )
            self.network_blueprint[target] = (
                EntityType.CONVEYOR,
                conveyor_direction,
                None,
            )
            self.owned_network_tiles.add(target)
            self.active_line_tiles.add(target)
            self.network_memory.record_unfinished_owned_tile(target)
            self.connected_network_cache = None
            self.last_progress_round = self.rounds_alive
            return True
        return False

    def has_expected_tree_conveyor(self, controller: Controller, target: Position) -> bool:
        """Check that ``target`` contains the allied transport required by the plan."""
        building_id = self.tile_cache.building_id_at(target)
        building = self.tile_cache.building_at(target)
        if building_id is None or building is None or building[1] != self.team:
            return False
        planned_bridge_target = self.bridge_targets.get(target)
        if planned_bridge_target is not None:
            return (
                building[0] == EntityType.BRIDGE
                and self.known_bridge_targets.get(target) == planned_bridge_target
            )
        if building[0] not in {
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
        }:
            return False
        return self.tile_cache.entity_direction(building_id) == self.get_conveyor_direction(target)

    def replan_or_wait_for_connection_tile(self, controller: Controller, target: Position) -> None:
        """Never step past a branch tile that was not successfully built."""
        if target not in self.bridge_targets and self.get_conveyor_direction(target) == Direction.CENTRE:
            self.schedule_replan_after_yield()
            return
        if self.tile_cache.building_id_at(target) is None:
            # Usually an action cooldown or a temporary resource shortage.
            # Stay on the branch and try the exact same tile next turn.
            return
        if self.is_enemy_road(target) and target == self.get_cached_position():
            # Firing has action cooldown; retain the exact branch while the
            # builder waits for its next attack or replacement build.
            return
        # A foreign/indestructible building occupies the planned branch tile.
        # Exclude it from the next A* search instead of walking through it and
        # falsely declaring the harvester connected.
        self.permanently_blocked.add(target)
        self.schedule_replan_after_yield()

    def is_enemy_road(self, pos: Position) -> bool:
        """Return whether ``pos`` contains a walkable rival road."""
        building = self.known_buildings.get(pos)
        return (
            building is not None
            and building[0] == EntityType.ROAD
            and building[1] != self.team
        )
