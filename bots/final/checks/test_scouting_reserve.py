"""Uncommitted exploration must not spend the shared construction reserve."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, Position, Team
from finalbot.economy.policy import exploration_is_funded
from finalbot.economy.builder.bot import BuilderBot
from finalbot.combat.intruder.bot import IntruderBot


class ScoutingReserveTests(unittest.TestCase):
    def test_reserve_uses_current_scaled_worker_mine_and_outlet_prices(self):
        c = Mock()
        c.get_builder_bot_cost.return_value = (75, 0)
        c.get_harvester_cost.return_value = (50, 0)
        c.get_conveyor_cost.return_value = (10, 0)
        c.get_road_cost.return_value = (3, 0)
        c.get_global_resources.return_value = (167, 0)
        self.assertFalse(exploration_is_funded(c))
        c.get_global_resources.return_value = (168, 0)
        self.assertTrue(exploration_is_funded(c))

    def test_worker_waits_to_pave_scouting_ground_but_can_finish_a_mine_approach(self):
        bot = BuilderBot(12, 12)
        bot.team = Team.A
        bot.scouting_funded = False
        target = Position(5, 5)
        bot.known_env[target] = Environment.EMPTY
        c = Mock()
        c.can_build_road.return_value = True
        c.build_road.return_value = 42
        bot.try_prepare_tile(c, target)
        c.build_road.assert_not_called()
        self.assertNotIn(target, bot.permanently_blocked)
        bot.target_ore = Position(6, 6)
        bot.try_prepare_tile(c, target)
        c.build_road.assert_called_once_with(target)

    def test_existing_road_movement_remains_available_to_an_unfunded_intruder(self):
        bot = IntruderBot(12, 12)
        bot.team = Team.A
        bot.current_position = Position(5, 5)
        bot.scouting_funded = False
        target = Position(6, 5)
        bot.known_env[target] = Environment.EMPTY
        bot.tile_cache.remember_building(target, 42, EntityType.ROAD, Team.A)
        c = Mock()
        c.can_move.return_value = True
        self.assertTrue(bot.try_move_step(c, Direction.EAST))
        c.move.assert_called_once_with(Direction.EAST)
        c.build_road.assert_not_called()

    def test_unfunded_intruder_does_not_pave_empty_scouting_ground(self):
        bot = IntruderBot(12, 12)
        bot.team = Team.A
        bot.current_position = Position(5, 5)
        bot.scouting_funded = False
        bot.known_env[Position(6, 5)] = Environment.EMPTY
        c = Mock()
        c.can_build_road.return_value = True
        self.assertFalse(bot.try_move_step(c, Direction.EAST))
        c.build_road.assert_not_called()


if __name__ == '__main__':
    unittest.main()
