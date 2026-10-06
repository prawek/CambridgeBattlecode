"""Cheap blocked gunner rays must not hide a usable sentinel plan."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import EntityType, Environment, Position, Team
from finalbot.combat.intruder.bot import IntruderBot
from finalbot.combat.siege_planner import next_plan


class SiegeAlternativesTests(unittest.TestCase):
    def test_dense_ore_cluster_still_validates_a_different_weapon(self):
        bot = IntruderBot(24, 24)
        bot.team = Team.A
        bot.current_position = Position(10, 11)
        bot.destination = Position(10, 15)
        bot.destination_is_confirmed_core = True
        bot.siege_rejected = {}
        for y in range(24):
            for x in range(24):
                bot.known_env[Position(x, y)] = Environment.EMPTY
        for x in (9, 10, 11):
            bot.known_env[Position(x, 9)] = Environment.ORE_TITANIUM
        bot.tile_cache.visible_tiles = set(bot.known_env)
        bot.tile_cache.remember_building(bot.destination, 50, EntityType.CORE, Team.B)
        c = Mock()
        c.get_cpu_time_elapsed.return_value = 0
        c.can_fire_from.side_effect = lambda site, facing, kind, goal: kind == EntityType.SENTINEL
        for turn in range(100, 140):
            pending, plan = next_plan(bot, c, bot.current_position, turn)
            if plan is not None:
                self.assertEqual(plan[2], EntityType.SENTINEL)
                break
            if not pending:
                self.fail('all slots were consumed by blocked gunner rays')
        else:
            self.fail('geometry search did not finish')


if __name__ == '__main__':
    unittest.main()
