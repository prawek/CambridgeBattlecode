"""Clear blocking roads without buying unnecessary turns toward other roads."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import EntityType, Environment, Position, Team
from finalbot.combat.gunner import GunnerBot
from finalbot.combat.sentinel import SentinelBot


class AmmoBudgetTests(unittest.TestCase):
    def controller(self, kind):
        c = Mock()
        c.get_team.side_effect = lambda entity_id=None: Team.A if entity_id is None else Team.B
        c.get_position.return_value = Position(5, 5)
        c.get_attackable_tiles.return_value = [Position(6, 5)]
        c.get_tile_builder_bot_id.return_value = None
        c.get_tile_building_id.return_value = 42
        c.get_entity_type.return_value = kind
        c.get_action_cooldown.return_value = 0
        c.get_ammo_amount.return_value = 10
        c.can_fire.return_value = True
        return c

    def test_gunner_clears_a_road_that_blocks_its_current_ray(self):
        c = self.controller(EntityType.ROAD)
        bot = GunnerBot(12, 12)
        bot._scan_turn = Mock(return_value=True)
        bot.run(c)
        c.fire.assert_called_once_with(Position(6, 5))
        bot._scan_turn.assert_not_called()

    def test_gunner_does_not_pay_to_rotate_toward_an_unrelated_road(self):
        c = self.controller(EntityType.ROAD)
        c.get_attackable_tiles.return_value = []
        c.get_current_round.return_value = 100
        bot = GunnerBot(12, 12)
        bot.current_position = Position(5, 5)
        bot.entity_id = 1
        road = Position(5, 6)
        bot.tile_cache.environments[road] = Environment.EMPTY
        bot.tile_cache.remember_building(road, 42, EntityType.ROAD, Team.B)
        bot._scan_turn = Mock(return_value=False)
        bot.read_enemy_marker = Mock(return_value=None)
        bot.run(c)
        c.rotate.assert_not_called()

    def test_sentinel_preserves_its_more_expensive_round(self):
        c = self.controller(EntityType.ROAD)
        SentinelBot().run(c)
        c.fire.assert_not_called()

    def test_a_builder_on_the_road_is_still_attacked(self):
        c = self.controller(EntityType.BUILDER_BOT)
        c.get_tile_builder_bot_id.return_value = 42
        SentinelBot().run(c)
        c.fire.assert_called_once_with(Position(6, 5))


if __name__ == '__main__':
    unittest.main()
