"""Roads on ore must not wedge a worker beside a completed mine outlet."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, GameConstants, Team
from finalbot.economy.builder.bot import BuilderBot


class OreObstructionTests(unittest.TestCase):
    def setUp(self):
        self.bot = BuilderBot(20, 20)
        self.bot.team = Team.A
        self.ore = self.bot.tile_cache.position_at(7, 0)
        self.approach = self.bot.tile_cache.position_at(7, 1)
        self.bot.tile_cache.environments[self.ore] = Environment.ORE_TITANIUM
        self.bot.target_ore = self.ore
        self.bot.rounds_alive = 80
        self.c = Mock()
        self.c.can_move.return_value = True
        self.c.can_fire.return_value = True
        self.c.get_hp.return_value = GameConstants.BUILDER_BOT_ATTACK_DAMAGE

    def road(self, owner):
        self.bot.tile_cache.remember_building(self.ore, 42, EntityType.ROAD, owner)

    def test_hostile_road_is_entered_before_attacking(self):
        self.road(Team.B)
        self.assertTrue(self.bot.clear_ore_road(self.c, self.approach))
        self.c.move.assert_called_once_with(Direction.NORTH)
        self.c.fire.assert_not_called()

    def test_road_is_attacked_from_its_tile_and_dead_road_leaves_cache(self):
        self.road(Team.B)
        self.assertTrue(self.bot.clear_ore_road(self.c, self.ore))
        self.c.fire.assert_called_once_with(self.ore)
        self.c.move.assert_not_called()
        self.assertIsNone(self.bot.tile_cache.building_at(self.ore))
        self.assertEqual(self.bot.last_progress_round, 80)

    def test_worker_leaves_cleared_ore_to_make_room_for_harvester(self):
        self.bot.is_cached_tile_passable = lambda tile: tile == self.approach
        self.assertTrue(self.bot.clear_ore_road(self.c, self.ore))
        self.c.move.assert_called_once_with(Direction.SOUTH)

    def test_friendly_road_is_removed_without_spending_an_attack(self):
        self.road(Team.A)
        self.assertFalse(self.bot.clear_ore_road(self.c, self.approach))
        self.c.destroy.assert_called_once_with(self.ore)
        self.c.fire.assert_not_called()
        self.assertIsNone(self.bot.tile_cache.building_at(self.ore))

    def test_existing_mine_is_preserved(self):
        self.bot.tile_cache.remember_building(self.ore, 42, EntityType.HARVESTER, Team.A)
        self.assertFalse(self.bot.clear_ore_road(self.c, self.approach))
        self.c.destroy.assert_not_called()
        self.c.fire.assert_not_called()


if __name__ == '__main__':
    unittest.main()
