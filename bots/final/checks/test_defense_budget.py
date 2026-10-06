"""Reserve fixed long-range weapons for targets that cannot just walk away."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import EntityType, Environment, Position, Team
from finalbot.combat.local import defend_with_battery
from finalbot.economy.builder.bot import BuilderBot


class DefenseBudgetTests(unittest.TestCase):
    def attempt(self, enemy_kind):
        bot = BuilderBot(16, 16)
        bot.team = Team.A
        bot.defense_cooldowns = {}
        ore, enemy = Position(5, 5), Position(10, 4)
        bot.tile_cache.visible_tiles = {ore}
        bot.known_env[ore] = Environment.ORE_TITANIUM
        bot.known_env[enemy] = Environment.EMPTY
        bot.tile_cache.remember_building(ore, 1, EntityType.HARVESTER, Team.A)
        bot.tile_cache.remember_building(enemy, 2, enemy_kind, Team.B)
        c = Mock()
        c.get_current_round.return_value = 20
        c.get_cpu_time_elapsed.return_value = 0
        c.can_fire_from.return_value = True
        c.can_build.return_value = True
        c.build.return_value = 42
        result = defend_with_battery(bot, c, Position(4, 4))
        return result, c

    def test_distant_mobile_builder_does_not_trigger_a_sentinel_purchase(self):
        built, c = self.attempt(EntityType.BUILDER_BOT)
        self.assertFalse(built)
        c.build.assert_not_called()

    def test_distant_stationary_gun_still_gets_a_counter_battery(self):
        built, c = self.attempt(EntityType.GUNNER)
        self.assertTrue(built)
        self.assertEqual(c.build.call_args.args[0], EntityType.SENTINEL)


if __name__ == '__main__':
    unittest.main()
