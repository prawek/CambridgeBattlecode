"""Core ore orders must not direct workers to occupied productive transport."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, Position, Team
import finalbot.core.bot as core_module
from finalbot.core.bot import CoreBot


class CoreOreOrderTests(unittest.TestCase):
    def setUp(self):
        self.bot = CoreBot(20, 20)
        self.bot.team = Team.A
        self.bot.core_pos = Position(10, 10)
        self.near, self.far = Position(10, 7), Position(10, 5)
        for pos in (self.near, self.far):
            self.bot.known_env[pos] = Environment.ORE_TITANIUM
        self.c = Mock()
        self.c.get_global_resources.return_value = (500, 0)

    def occupy(self, kind, owner=Team.A):
        self.bot.tile_cache.remember_building(self.near, 42, kind, owner, direction=Direction.SOUTH)

    def test_nearest_productive_conveyor_is_skipped_for_farther_ore(self):
        self.occupy(EntityType.CONVEYOR)
        self.bot.refresh_sector_targets(self.c)
        self.assertEqual(self.bot.sector_targets[Direction.NORTH], (self.far, Environment.ORE_TITANIUM))

    def test_existing_order_on_a_bridge_is_cleared_and_reassigned(self):
        self.bot.sector_targets[Direction.NORTH] = self.near, Environment.ORE_TITANIUM
        self.occupy(EntityType.BRIDGE)
        self.bot.refresh_sector_targets(self.c)
        self.assertEqual(self.bot.sector_targets[Direction.NORTH], (self.far, Environment.ORE_TITANIUM))

    def test_friendly_and_hostile_roads_leave_the_deposit_orderable(self):
        for owner in (Team.A, Team.B):
            with self.subTest(owner=owner):
                self.bot.sector_targets.clear()
                self.occupy(EntityType.ROAD, owner)
                self.bot.refresh_sector_targets(self.c)
                self.assertEqual(self.bot.sector_targets[Direction.NORTH], (self.near, Environment.ORE_TITANIUM))

    def test_a_completed_harvester_clears_the_last_order_in_its_sector(self):
        self.bot.known_env.pop(self.far)
        self.bot.sector_targets[Direction.NORTH] = self.near, Environment.ORE_TITANIUM
        self.occupy(EntityType.HARVESTER, Team.B)
        self.bot.refresh_sector_targets(self.c)
        self.assertNotIn(Direction.NORTH, self.bot.sector_targets)

    def test_a_cached_order_without_a_building_observation_is_retained(self):
        unknown = Position(10, 2)
        self.bot.sector_targets[Direction.NORTH] = unknown, Environment.ORE_TITANIUM
        self.bot.refresh_sector_targets(self.c)
        self.assertEqual(self.bot.sector_targets[Direction.NORTH][0], unknown)
        self.c.get_tile_building_id.assert_not_called()

    def test_distinct_sector_orders_stay_distinct(self):
        for pos in (Position(13, 10), Position(10, 13), Position(7, 10)):
            self.bot.known_env[pos] = Environment.ORE_TITANIUM
        self.occupy(EntityType.CONVEYOR)
        self.bot.refresh_sector_targets(self.c)
        self.assertEqual(set(self.bot.sector_targets), {Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST})
        self.assertEqual(len({target[0] for target in self.bot.sector_targets.values()}), 4)

    def test_axionite_orders_still_require_the_unlock_and_resource_threshold(self):
        ax = Position(13, 10)
        self.bot.known_env[ax] = Environment.ORE_AXIONITE
        threshold = core_module.AXIONITE_TITANIUM_THRESHOLD
        with patch.object(core_module, 'AXIONITE_PIPELINE_ENABLED', False):
            self.c.get_global_resources.return_value = (threshold + 1, 0)
            self.bot.refresh_sector_targets(self.c)
            self.assertNotIn(Direction.EAST, self.bot.sector_targets)
        with patch.object(core_module, 'AXIONITE_PIPELINE_ENABLED', True):
            self.c.get_global_resources.return_value = (threshold, 0)
            self.bot.refresh_sector_targets(self.c)
            self.assertNotIn(Direction.EAST, self.bot.sector_targets)
            self.c.get_global_resources.return_value = (threshold + 1, 0)
            self.bot.refresh_sector_targets(self.c)
            self.assertEqual(self.bot.sector_targets[Direction.EAST], (ax, Environment.ORE_AXIONITE))


if __name__ == '__main__':
    unittest.main()
