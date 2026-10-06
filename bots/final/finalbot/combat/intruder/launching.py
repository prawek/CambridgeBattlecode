"""Addressed launcher crossings and their marker handoffs."""

from cambc import Controller, Direction, EntityType, Environment, GameConstants, Position
from finalbot.shared.constants import DIRECTIONS, LAUNCH_WAIT_ROUNDS, MARKER_KIND_INTRUDER_LAUNCH
from finalbot.shared.geometry import encode_marker


class IntruderLaunching:
    """Uses state initialized by IntruderBot."""

    def wait_for_launcher(self, controller: Controller, current: Position) -> bool:
        """Wait for the launcher to finish scanning and throw this bot."""
        if self.waiting_launcher_origin is None or self.waiting_launcher_round is None:
            return False
        if current != self.waiting_launcher_origin:
            self.waiting_launcher_origin = None
            self.waiting_launcher_round = None
            self.waiting_launch_marker = None
            self.wall_following = False
            return False
        # A newborn launcher needs several turns to finish its terrain scan.
        if controller.get_current_round() <= self.waiting_launcher_round + LAUNCH_WAIT_ROUNDS:
            return True
        # The launcher acts after this older builder on the requested turn.
        # If it still could not throw us, stop waiting and bypass the wall.
        self.waiting_launcher_origin = None
        self.waiting_launcher_round = None
        if self.waiting_launch_marker is not None and controller.can_destroy(self.waiting_launch_marker):
            controller.destroy(self.waiting_launch_marker)
            self.tile_cache.forget_building(self.waiting_launch_marker)
        self.waiting_launch_marker = None
        self.wall_following = True
        return False

    def start_launcher_crossing(
            self,
            controller: Controller,
            current: Position,
            direction: Direction,
            destination: Position,
            exact_landing: bool = False,
    ) -> bool:
        """Build a launcher for a known landing tile beyond a blocking wall.

        Supply-route crossings use an exact A* bridge endpoint.  Letting the
        generic exploration launcher choose a farther visible cell would put
        the Intruder outside its saved path and make it rejoin from the wrong
        side of the barrier.
        """
        landing = (
            destination
            if exact_landing and self.is_cached_tile_passable(destination)
            else self.find_launcher_landing(current, direction, destination)
        )
        if exact_landing and landing != destination:
            return False
        if landing is None:
            return False
        for launcher_pos in self.launcher_build_sites(current, landing):
            marker_pos = self.find_launch_marker_site(current, launcher_pos)
            if marker_pos is None:
                continue
            if not controller.can_place_marker(marker_pos):
                continue
            if not controller.can_build_launcher(launcher_pos):
                continue
            # Address the throw to the intruder's tile; an economic worker may
            # also be adjacent and must not be launched away from its mine.
            source_code = DIRECTIONS.index(launcher_pos.direction_to(current)) + 1
            marker_value = encode_marker(MARKER_KIND_INTRUDER_LAUNCH, landing, source_code)
            marker_id = controller.place_marker(marker_pos, marker_value)
            self.tile_cache.remember_building(
                marker_pos,
                marker_id,
                EntityType.MARKER,
                self.team,
                marker_value=marker_value,
            )
            launcher_id = controller.build_launcher(launcher_pos)
            self.tile_cache.remember_building(
                launcher_pos,
                launcher_id,
                EntityType.LAUNCHER,
                self.team,
            )
            self.waiting_launcher_origin = current
            self.waiting_launcher_round = controller.get_current_round()
            self.waiting_launch_marker = marker_pos
            return True
        return False

    def find_launcher_landing(
            self,
            current: Position,
            direction: Direction,
            destination: Position,
    ) -> Position | None:
        """Choose a visible passable landing tile strictly beyond the blocking wall.

        A positive dot product is not enough for a diagonal heading: it would
        accept a tile south-east of a south-west wall merely because it also
        has a southern component.  Every non-zero axis of the heading must
        advance by at least two tiles, putting the landing on the far side of
        the adjacent wall rather than beside it or in another direction.
        """
        dx, dy = direction.delta()
        candidates: list[tuple[int, int, Position]] = []
        for pos in self.tile_cache.visible_tiles:
            if pos in self.visited_tiles:
                continue
            if not self.is_cached_tile_passable(pos):
                continue
            horizontal_progress = (pos.x - current.x) * dx
            vertical_progress = (pos.y - current.y) * dy
            axis_progress = []
            if dx != 0:
                axis_progress.append(horizontal_progress)
            if dy != 0:
                axis_progress.append(vertical_progress)
            if not axis_progress or min(axis_progress) <= 1:
                continue
            forward_progress = min(axis_progress)
            candidates.append((forward_progress, -pos.distance_squared(destination), pos))
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (item[0], item[1], item[2].x, item[2].y),
            reverse=True,
        )
        # Launcher range is measured from its eventual adjacent build site;
        # keep a conservative one-tile allowance while choosing the landing.
        for _, _, landing in candidates:
            if current.distance_squared(landing) <= GameConstants.LAUNCHER_VISION_RADIUS_SQ + 10:
                return landing
        return None

    def launcher_build_sites(self, current: Position, landing: Position) -> list[Position]:
        """Return empty action-radius tiles where a launcher could reach ``landing``."""
        sites = []
        for direction in DIRECTIONS:
            pos = self.tile_cache.neighbor(current, direction)
            if pos is None:
                continue
            env = self.known_env.get(pos)
            if (
                env is None
                or env == Environment.WALL
                or self.known_buildings.get(pos) is not None
                or self.tile_cache.builder_id_at(pos) is not None
                or pos.distance_squared(landing) > GameConstants.LAUNCHER_VISION_RADIUS_SQ
            ):
                continue
            sites.append(pos)
        sites.sort(key=lambda pos: pos.distance_squared(landing))
        return sites

    def find_launch_marker_site(self, current: Position, launcher_pos: Position) -> Position | None:
        """Find an empty nearby cell visible to both the intruder and its launcher."""
        for direction in DIRECTIONS:
            pos = self.tile_cache.neighbor(current, direction)
            if pos is None:
                continue
            if pos == launcher_pos:
                continue
            env = self.known_env.get(pos)
            if (
                env is not None
                and env != Environment.WALL
                and self.known_buildings.get(pos) is None
                and self.tile_cache.builder_id_at(pos) is None
                and launcher_pos.distance_squared(pos) <= GameConstants.LAUNCHER_VISION_RADIUS_SQ
            ):
                return pos
        return None
