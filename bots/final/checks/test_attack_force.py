"""A funded economy can replenish its attack without losing the opening bank."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Position
from finalbot.core.bot import CoreBot


class AttackForceTests(unittest.TestCase):
    def setup_force(self, bank, now=500):
        bot = CoreBot(20, 20)
        bot.core_pos = Position(5, 5)
        bot.intruder_ids = [10, 11]
        bot.intruders_spawned = 6
        bot.intruder_spawn_round = 0
        c = Mock()
        c.get_global_resources.return_value = (bank, 0)
        c.get_current_round.return_value = now
        c.get_unit_count.return_value = 10
        c.get_builder_bot_cost.return_value = (30, 0)
        c.get_harvester_cost.return_value = (20, 0)
        c.get_conveyor_cost.return_value = (3, 0)
        c.can_spawn.return_value = True
        c.can_place_marker.return_value = True
        c.spawn_builder.return_value = 42
        return bot, c

    def test_large_bank_reopens_reinforcements_beyond_lifetime_cap(self):
        bot, c = self.setup_force(1200)
        self.assertTrue(bot.try_spawn_intruder(c))
        self.assertEqual(bot.intruder_ids, [10, 11, 42])

    def test_opening_does_not_expand_force_even_with_a_large_bank(self):
        bot, c = self.setup_force(1200, now=50)
        self.assertFalse(bot.try_spawn_intruder(c))
        c.spawn_builder.assert_not_called()

    def test_low_bank_does_not_fund_endless_replacements(self):
        bot, c = self.setup_force(100)
        self.assertFalse(bot.try_spawn_intruder(c))
        c.spawn_builder.assert_not_called()

    def test_live_construction_reserve_blocks_otherwise_affordable_reinforcement(self):
        bot, c = self.setup_force(1200)
        c.get_harvester_cost.return_value = (900, 0)
        c.get_conveyor_cost.return_value = (40, 0)
        self.assertFalse(bot.try_spawn_intruder(c))
        c.spawn_builder.assert_not_called()


if __name__ == '__main__':
    unittest.main()
