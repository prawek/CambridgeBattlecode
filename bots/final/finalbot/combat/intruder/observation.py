"""Core hypotheses and observed enemy displacement zones."""

from cambc import EntityType, Position


class IntruderObservation:
    """Uses state initialized by IntruderBot."""

    def find_friendly_core(self) -> Position | None:
        """Locate the allied core solely from the tile-cache entity index."""
        for entity_id in self.tile_cache.visible_entity_ids:
            if (
                self.tile_cache.entity_type(entity_id) == EntityType.CORE
                and self.tile_cache.entity_team(entity_id) == self.team
            ):
                return self.tile_cache.entity_position(entity_id)
        return None

    def update_enemy_knowledge(self) -> None:
        """Read the observed or symmetry-inferred opposing Core from the cache."""
        for entity_id in self.tile_cache.visible_entity_ids:
            if (
                self.tile_cache.entity_type(entity_id) == EntityType.CORE
                and self.tile_cache.entity_team(entity_id) != self.team
            ):
                self.set_confirmed_enemy_destination(
                    self.tile_cache.entity_position(entity_id),
                )
                return

        inferred_core = self.tile_cache.enemy_core_position(self.team)
        if inferred_core is not None:
            self.set_confirmed_enemy_destination(inferred_core)
            return

        if self.destination is None:
            # The first hypothesis is the 180-degree counterpart.  It is
            # replaced immediately once TileCache confirms the real symmetry.
            self.destination = self.tile_cache.mirrored_position(
                self.core_pos,
                "rotational",
            )

    def set_confirmed_enemy_destination(self, destination: Position) -> None:
        """Update the Core goal without discarding a stable wall-follow state."""
        destination_changed = self.destination != destination
        newly_confirmed = not self.destination_is_confirmed_core
        if destination_changed:
            self.clear_exploration_branch_state()
        self.destination = destination
        self.destination_is_confirmed_core = True
        if destination_changed or newly_confirmed:
            self.wall_following = False
            self.stop_exploration_wall_following()

    def refresh_enemy_launchers(self) -> None:
        """Retain displacement zones until their launcher is visibly gone."""
        cache = self.tile_cache
        self.enemy_launcher_positions = {
            pos for pos in self.enemy_launcher_positions
            if pos not in cache.visible_tiles
            or (cache.building_at(pos) is not None
                and cache.building_at(pos)[0] == EntityType.LAUNCHER
                and cache.building_at(pos)[1] != self.team)
        }
        for entity_id in cache.visible_entity_ids:
            if (cache.entity_type(entity_id) == EntityType.LAUNCHER
                    and cache.entity_team(entity_id) != self.team):
                self.enemy_launcher_positions.add(cache.entity_position(entity_id))

    def in_launcher_zone(self, pos: Position) -> bool:
        return any(pos.distance_squared(launcher) <= 2
                   for launcher in self.enemy_launcher_positions)
