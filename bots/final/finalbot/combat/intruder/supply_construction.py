"""Execute ammunition transport and restore its damaged components."""

from cambc import Controller, Direction, EntityType, GameConstants, Position
from finalbot.shared.constants import DIRECTIONS
from finalbot.navigation.combat import a_star_to_any
from finalbot.combat.intruder.settings import (
    _CHEAP_ENEMY_BUILDING_MAX_HP,
    _CHEAP_ENEMY_WALKABLE_BUILDINGS,
    _CLEARABLE_WALKABLE_BUILDINGS,
    _SUPPLY_SEARCH_EXPANSIONS,
)


class IntruderSupplyConstruction:
    """Uses state initialized by IntruderBot."""

    def clear_walkable_tile(
            self,
            controller: Controller,
            pos: Position,
            allow_enemy_road: bool = False,
    ) -> bool:
        """Remove a replaceable tile, allowing enemy roads only for supply routes.

        A BuilderBot can attack an enemy building only while standing on it.
        Consequently, an enemy road is never cleared during ordinary
        movement, but a supply branch may clear one after deliberately
        stepping onto that planned route cell.
        """
        building = self.known_buildings.get(pos)
        if building is None:
            return True
        building_type, building_team = building
        if building_type not in _CLEARABLE_WALKABLE_BUILDINGS:
            return False
        if building_team == self.team:
            if self.is_protected_transport(pos):
                return False
            if not controller.can_destroy(pos):
                return False
            controller.destroy(pos)
            self.tile_cache.forget_building(pos)
            return True
        if building_type == EntityType.ROAD and not allow_enemy_road:
            return False
        if pos != self.get_cached_position() or not controller.can_fire(pos):
            return False
        building_id = self.tile_cache.building_id_at(pos)
        if building_id is None:
            return False
        remaining_hp = controller.get_hp(building_id)
        controller.fire(pos)
        if remaining_hp <= GameConstants.BUILDER_BOT_ATTACK_DAMAGE:
            self.tile_cache.forget_building(pos)
        return False

    def clear_cheap_enemy_building(self, controller: Controller, current: Position) -> bool:
        """Fire at a cheap enemy logistics tile underfoot and spend this turn on it.

        BuilderBots cannot fire at an arbitrary adjacent enemy structure: the
        rules permit damage only to the building on their own tile.  Therefore
        this is intentionally limited to enemy walkable logistics buildings,
        never to a Core, Harvester, or armoured conveyor.  A target is cheap
        only when its remaining HP fits in at most two BuilderBot shots.
        """
        building = self.known_buildings.get(current)
        if building is None:
            return False
        building_type, building_team = building
        if (
            building_team == self.team
            or building_type not in _CHEAP_ENEMY_WALKABLE_BUILDINGS
            or not controller.can_fire(current)
        ):
            return False

        building_id = self.tile_cache.building_id_at(current)
        if building_id is None:
            return False
        remaining_hp = controller.get_hp(building_id)
        if remaining_hp > _CHEAP_ENEMY_BUILDING_MAX_HP:
            return False

        controller.fire(current)
        if remaining_hp <= GameConstants.BUILDER_BOT_ATTACK_DAMAGE:
            self.tile_cache.forget_building(current)
        return True

    def supply_gunner(self, controller: Controller, current: Position) -> None:
        """Build one Gunner-to-ore supply route, placing transport as we advance."""
        if self.supply_ore is None:
            if not self.select_supply_plan():
                if self.supply_plan_candidates is not None:
                    # An expensive route search is deliberately spread across
                    # turns.  Do not wander away while the next candidate is
                    # still awaiting its bounded A* attempt.
                    return
                self.search_for_titanium(controller)
                return
        elif not self.supply_path:
            # A committed route is a construction contract.  Do not replace
            # it merely because another deposit becomes visible: doing so
            # leaves its already placed Gunner-side conveyors as an isolated
            # fragment and starts the next route somewhere else.
            self.reconsider_supply_plan()
            if self.a_star_state("supply_route").pending:
                return

        if not self.supply_path:
            plan = self.plan_supply_route(self.supply_ore)
            if plan is None:
                if self.a_star_state("supply_route").pending:
                    return
                self.explore_supply_route(controller, current)
                return
            self.store_supply_plan(self.supply_ore, plan)
        if not self.follow_supply_path(controller, current):
            return
        if not self.ensure_supply_harvester(controller, current):
            return
        self.mode = "complete"

    def ensure_supply_harvester(self, controller: Controller, current: Position) -> bool:
        """Reuse an occupied Ti harvester, or build one from the route endpoint."""
        if self.supply_ore is None:
            return False
        if not self.is_available_supply_ore(self.supply_ore):
            self.reset_supply_plan()
            return False
        building = self.known_buildings.get(self.supply_ore)
        if building is not None and building[0] == EntityType.HARVESTER:
            # Resource stacks are allowed to cross team boundaries, so an
            # enemy harvester can directly feed our adjacent conveyor.
            return True
        if building is not None:
            self.unavailable_titanium.update((self.supply_ore,))
            self.reset_supply_plan()
            return False
        if current.distance_squared(self.supply_ore) > GameConstants.ACTION_RADIUS_SQ:
            return False
        if not controller.can_build_harvester(self.supply_ore):
            return False
        harvester_id = controller.build_harvester(self.supply_ore)
        self.owned_supply_ores.add(self.supply_ore)
        self.tile_cache.remember_building(
            self.supply_ore,
            harvester_id,
            EntityType.HARVESTER,
            self.team,
        )
        return True

    def follow_supply_path(self, controller: Controller, current: Position) -> bool:
        """Advance exactly along the Gunner-to-ore route, building as we go.

        ``True`` means every route tile is now in place and the Intruder is
        standing on the ore-side endpoint.  Any movement, construction,
        launcher crossing, or blocked rejoin consumes this turn and returns
        ``False`` so the next round resumes from the same route state.
        """
        if not self.supply_path:
            return False
        if self.finish_pending_supply_bridge(controller, current):
            return False
        self.advance_supply_index()
        if self.supply_index >= len(self.supply_path):
            if current == self.supply_path[-1]:
                return True
            self.rejoin_supply_path(controller, current, self.supply_path[-1])
            return False
        try:
            index = self.supply_path.index(current)
        except ValueError:
            self.rejoin_supply_path(
                controller,
                current,
                self.supply_path[self.supply_index],
            )
            return False
        if index > self.supply_index:
            # Scouting can cross a far route cell before its Gunner-side
            # prefix exists.  Do not promote the cursor to that position: go
            # back to the first missing tile and resume construction there.
            self.rejoin_supply_path(
                controller,
                current,
                self.supply_path[self.supply_index],
            )
            return False

        if current in self.supply_bridge_targets and not self.supply_tile_complete(current):
            # A Builder cannot create the ore-side Bridge underneath itself.
            # Clear a replaceable foreign transport tile first, then walk one
            # exact route step away and create the Bridge behind it.
            if self.known_buildings.get(current) is not None:
                self.build_supply_tile(controller, current)
                return False
            self.pending_supply_bridge = current
            if index + 1 < len(self.supply_path):
                self.move_to_supply_route_tile(
                    controller,
                    current,
                    self.supply_path[index + 1],
                )
            else:
                self.step_off_supply_bridge(controller)
            return False

        # Lay the final conveyor before moving farther from the Gunner.  Its
        # direction points to the preceding route node, preserving ore-to-
        # Gunner resource flow while the Intruder travels in the opposite way.
        if current in self.supply_directions and not self.supply_tile_complete(current):
            self.build_supply_tile(controller, current)
            return False
        if index + 1 >= len(self.supply_path):
            return True
        next_pos = self.supply_path[index + 1]
        if self.supply_bridge_crossings.get(current) == next_pos:
            direction = current.direction_to(next_pos)
            self.start_launcher_crossing(
                controller,
                current,
                direction,
                next_pos,
                exact_landing=True,
            )
            return False
        self.move_to_supply_route_tile(controller, current, next_pos)
        return False

    def advance_supply_index(self) -> None:
        """Keep the cursor on the first route tile not yet in final form."""
        while (
            self.supply_index < len(self.supply_path)
            and self.supply_tile_complete(self.supply_path[self.supply_index])
        ):
            self.supply_index += 1

    def rejoin_supply_path(
            self,
            controller: Controller,
            current: Position,
            target: Position,
    ) -> None:
        """Walk back to one required route cell without laying a later conveyor."""
        search_state = self.a_star_state("supply_rejoin")
        approach = a_star_to_any(
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
        if approach:
            self.move_to_supply_route_tile(
                controller,
                current,
                approach[0],
                construct_supply_tile=False,
            )

    def finish_pending_supply_bridge(self, controller: Controller, current: Position) -> bool:
        """Build the physical Bridge immediately after crossing its A* jump.

        A Builder cannot build a Bridge on the tile it currently occupies.
        After a Launcher lands on the far endpoint it therefore walks exactly
        one planned step toward the ore, then creates the Bridge behind it.
        This makes the virtual A* jump a real conveyor connection before the
        bot continues toward the Harvester.
        """
        bridge_tile = self.pending_supply_bridge
        if bridge_tile is None:
            return False
        if self.supply_tile_complete(bridge_tile):
            self.pending_supply_bridge = None
            return False
        if current == bridge_tile:
            return False
        if current.distance_squared(bridge_tile) <= GameConstants.ACTION_RADIUS_SQ:
            if self.build_supply_tile(controller, bridge_tile):
                self.pending_supply_bridge = None
            return True
        # This branch is only a safety net for an external displacement.  It
        # returns to the bridge endpoint rather than falling back to the
        # Gunner-side route prefix.
        search_state = self.a_star_state("pending_supply_bridge")
        approach = a_star_to_any(
            None,
            current,
            {bridge_tile},
            lambda _controller, pos: self.is_roadable_position(pos),
            self.tile_cache.neighbor,
            movement_directions=DIRECTIONS,
            max_expansions=_SUPPLY_SEARCH_EXPANSIONS,
            state=search_state,
        )
        if search_state.pending:
            return True
        if approach:
            self.move_to_supply_route_tile(controller, current, approach[0])
        return True

    def move_to_supply_route_tile(
            self,
            controller: Controller,
            current: Position,
            target: Position,
            construct_supply_tile: bool = True,
    ) -> bool:
        """Build a planned conveyor before entering its tile, never a temporary road.

        The generic movement primitive turns an empty cell into a road so a
        BuilderBot can walk onto it.  That is useful while infiltrating, but
        wrong for a supply route: the very same cell would have to be removed
        and rebuilt as a conveyor on the following two turns.  When the next
        step belongs to the saved route, place its final transport building
        first and then use the normal movement check without road creation.
        """
        direction = current.direction_to(target)
        if direction == Direction.CENTRE or current.distance_squared(target) > 2:
            return False
        is_planned_tile = target in self.supply_path
        building = self.known_buildings.get(target)
        if (
            construct_supply_tile
            and is_planned_tile
            and building is not None
            and building[0] in _CLEARABLE_WALKABLE_BUILDINGS
            and building[1] != self.team
        ):
            # Builders can only fire at a building underneath themselves.
            # First enter the usable enemy logistics tile; subsequent turns
            # will remove it and replace it with our conveyor.
            return self.try_move_step(controller, direction, build_road=False)
        if (
            construct_supply_tile
            and is_planned_tile
            and not self.supply_tile_complete(target)
        ):
            if not self.build_supply_tile(controller, target):
                return False
        return self.try_move_step(
            controller,
            direction,
            build_road=not (construct_supply_tile and is_planned_tile),
        )

    def supply_tile_complete(self, tile: Position) -> bool:
        """Return whether the planned friendly conveyor or bridge already occupies ``tile``."""
        building = self.known_buildings.get(tile)
        if building is None:
            return False
        bridge_target = self.supply_bridge_targets.get(tile)
        if bridge_target is not None:
            # Resources may cross team boundaries, so a pre-existing bridge
            # with the exact ore-to-Gunner endpoint is reusable regardless of
            # owner.  A differently aimed bridge never enters this route.
            return (
                building[0] == EntityType.BRIDGE
                and self.known_bridge_targets.get(tile) == bridge_target
            )
        direction = self.supply_directions.get(tile)
        if direction is None:
            return False
        building_id = self.tile_cache.building_id_at(tile)
        return (
            building[0] == EntityType.CONVEYOR
            and building[1] == self.team
            and building_id is not None
            and self.tile_cache.entity_direction(building_id) == direction
        )

    def step_off_supply_bridge(self, controller: Controller) -> bool:
        """Vacate a bridge tile so the Builder can construct that bridge next turn."""
        for direction in DIRECTIONS:
            if controller.can_move(direction):
                controller.move(direction)
                return True
        return False

    def build_supply_tile(self, controller: Controller, tile: Position) -> bool:
        """Replace an obstructing road/conveyor and lay the planned transport tile."""
        building = self.known_buildings.get(tile)
        bridge_target = self.supply_bridge_targets.get(tile)
        wants_bridge = bridge_target is not None
        if self.is_protected_transport(tile):
            self.reset_supply_plan()
            return False
        if self.supply_tile_complete(tile):
            return True
        if building is not None:
            if not self.clear_walkable_tile(
                    controller,
                    tile,
                    allow_enemy_road=True,
            ):
                return False
            # Destroying a road/conveyor consumes the Builder action.  Wait
            # for the next turn before attempting to place its replacement.
            return False
        if wants_bridge:
            if bridge_target is None:
                self.reset_supply_plan()
                return False
            # A conveyor may have been placed on the preceding move, leaving
            # the Builder with one round of action cooldown.  That is not a
            # route error: retain the exact bridge order and retry next turn.
            if not controller.can_build_bridge(tile, bridge_target):
                return False
            bridge_id = controller.build_bridge(tile, bridge_target)
            self.owned_supply_tiles.add(tile)
            self.tile_cache.remember_building(tile, bridge_id, EntityType.BRIDGE, self.team)
            self.known_bridge_targets[tile] = bridge_target
            self.known_bridge_ids[tile] = bridge_id
            return True
        direction = self.supply_directions.get(tile)
        if direction is None:
            self.reset_supply_plan()
            return False
        if not controller.can_build_conveyor(tile, direction):
            return False
        conveyor_id = controller.build_conveyor(tile, direction)
        self.owned_supply_tiles.add(tile)
        self.tile_cache.remember_building(
            tile,
            conveyor_id,
            EntityType.CONVEYOR,
            self.team,
            direction=direction,
        )
        return True
