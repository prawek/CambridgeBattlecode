"""Quiet mine ports should be sealed without spending the expansion bank."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, GameConstants, Position, Team
from finalbot.economy.builder.bot import BuilderBot


class MinePortTests(unittest.TestCase):
    def setUp(self):
        self.bot = BuilderBot(12, 12)
        self.bot.team = Team.A
        self.bot.target_ore = Position(4, 4)
        self.bot.target_is_connection = True
        self.bot.rounds_alive = 20
        self.bot.harvester_is_connected = Mock(return_value=True)
        self.guard = Position(3, 4)
        self.bot.harvester_guard_tiles = {self.guard}
        for x in range(2, 8):
            for y in range(2, 7):
                self.bot.known_env[Position(x, y)] = Environment.EMPTY
        self.bot.known_env[self.bot.target_ore] = Environment.ORE_TITANIUM
        self.c = Mock()
        self.c.get_conveyor_cost.return_value = (3, 0)
        self.c.get_gunner_cost.return_value = (10, 0)
        self.c.get_harvester_cost.return_value = (20, 0)
        self.c.get_global_resources.return_value = (30, 0)
        self.c.build_conveyor.return_value = 42

    def test_quiet_port_uses_a_walkable_seal_without_buying_a_gunner(self):
        self.assertTrue(self.bot.try_build_harvester_guard(self.c, Position(3, 3)))
        self.c.build_conveyor.assert_called_once_with(self.guard, Direction.EAST)
        self.c.build_gunner.assert_not_called()
        self.assertFalse(self.bot.harvester_guard_tiles)

    def test_a_vulnerable_mine_can_get_a_second_cross_covering_gun(self):
        self.bot.core_pos = Position(4, 6)
        other_port = Position(5, 4)
        self.bot.tile_cache.remember_building(other_port, 41, EntityType.GUNNER, Team.A, Direction.EAST)
        enemy = Position(1, 4)
        self.bot.known_env[enemy] = Environment.EMPTY
        self.bot.tile_cache.remember_building(enemy, 90, EntityType.BUILDER_BOT, Team.B)
        self.c.get_global_resources.return_value = (1000, 0)
        self.c.get_unit_count.return_value = 5
        self.c.build_gunner.return_value = 42
        self.assertTrue(self.bot.try_build_harvester_guard(self.c, Position(3, 3)))
        self.c.build_gunner.assert_called_once_with(self.guard, Direction.WEST)

    def test_quiet_mine_with_one_gun_can_cover_the_opposite_port(self):
        self.bot.core_pos = Position(4, 6)
        self.bot.tile_cache.remember_building(Position(5, 4), 41, EntityType.GUNNER, Team.A, Direction.EAST)
        self.c.get_global_resources.return_value = (1000, 0)
        self.c.get_unit_count.return_value = 5
        self.assertTrue(self.bot.try_build_harvester_guard(self.c, Position(3, 3)))
        self.c.build_gunner.assert_called_once_with(self.guard, Direction.WEST)
        self.c.build_conveyor.assert_not_called()

    def test_garrison_reserves_unit_slots_for_workers_and_core_repairs(self):
        self.bot.core_pos = Position(4, 6)
        self.c.get_global_resources.return_value = (1000, 0)
        self.c.get_unit_count.return_value = GameConstants.MAX_TEAM_UNITS - 10
        self.assertTrue(self.bot.try_build_harvester_guard(self.c, Position(3, 3)))
        self.c.build_gunner.assert_not_called()
        self.c.build_conveyor.assert_called_once()

    def test_remote_blocked_enemy_does_not_trigger_a_gunner_with_no_shot(self):
        enemy = Position(1, 4)
        self.bot.known_env[enemy] = Environment.EMPTY
        self.bot.tile_cache.remember_building(enemy, 90, EntityType.BUILDER_BOT, Team.B)
        self.c.get_global_resources.return_value = (1000, 0)
        self.c.get_unit_count.return_value = 5
        self.c.can_fire_from.return_value = False
        self.assertTrue(self.bot.try_build_harvester_guard(self.c, Position(3, 3)))
        self.c.build_gunner.assert_not_called()
        self.c.build_conveyor.assert_called_once_with(self.guard, Direction.EAST)

    def test_off_axis_scout_does_not_cancel_the_home_mine_garrison(self):
        self.bot.core_pos = Position(4, 6)
        enemy = Position(1, 4)
        self.bot.tile_cache.remember_building(enemy, 90, EntityType.BUILDER_BOT, Team.B)
        self.c.get_global_resources.return_value = (1000, 0)
        self.c.get_unit_count.return_value = 5
        self.c.can_fire_from.return_value = False
        self.assertTrue(self.bot.try_build_harvester_guard(self.c, Position(3, 3)))
        self.c.build_gunner.assert_called_once_with(self.guard, Direction.WEST)


if __name__ == '__main__':
    unittest.main()
