"""Core survival on crowded maps, before and after receiving damage."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Position, Team
from finalbot.core.bot import CoreBot
from finalbot.combat.defense import core_defender_demand


class DeploymentTests(unittest.TestCase):
    def test_late_casualties_can_be_replaced_after_the_lifetime_spawn_cap(self):
        bot = CoreBot(20, 20)
        bot.core_pos = Position(10, 10)
        bot.initial_spawned_directions = {Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST}
        bot.economy_builder_ids = [10, 11]
        bot.replacement_builders_spawned = 12
        bot.last_builder_spawn_round = 1000
        c = Mock()
        c.get_unit_count.return_value = 4
        c.get_global_resources.return_value = (1000, 0)
        c.get_current_round.return_value = 1500
        c.get_builder_bot_cost.return_value = (30, 0)
        c.get_harvester_cost.return_value = (20, 0)
        c.get_conveyor_cost.return_value = (3, 0)
        c.can_spawn.return_value = True
        c.spawn_builder.return_value = 42
        self.assertTrue(bot.try_spawn_missing_builder(c))
        self.assertIn(42, bot.economy_builder_ids)

    def setUp(self):
        self.bot = CoreBot(20, 20)
        self.bot.core_pos = Position(18, 18)
        self.bot.entity_id = 1
        self.bot.team = Team.B
        self.c = Mock()
        self.c.get_hp.return_value = 500
        self.c.get_current_round.return_value = 100
        self.c.get_nearby_units.return_value = [42]
        self.c.get_team.return_value = Team.A
        self.c.get_position.return_value = Position(16, 17)
        self.c.get_direction.return_value = Direction.SOUTH

    def test_approaching_raider_triggers_defense_before_core_damage(self):
        self.c.get_entity_type.return_value = EntityType.BUILDER_BOT
        self.assertEqual(core_defender_demand(self.bot, self.c), 1)
        self.assertFalse(self.bot.tile_cache.visible_entity_ids)

    def test_two_sentinels_need_four_healers(self):
        self.c.get_nearby_units.return_value = [42, 43]
        self.c.get_entity_type.return_value = EntityType.SENTINEL
        self.c.can_fire_from.return_value = True
        self.assertEqual(core_defender_demand(self.bot, self.c), 4)

    def test_blocked_guns_do_not_consume_worker_budget(self):
        self.c.get_entity_type.return_value = EntityType.GUNNER
        self.c.can_fire_from.return_value = False
        self.assertEqual(core_defender_demand(self.bot, self.c), 1)

    def test_boundary_core_uses_free_knight_offset(self):
        free = Position(16, 19)
        self.c.can_place_marker.side_effect = lambda pos: pos == free
        self.assertEqual(self.bot.find_defender_order_pad(self.c), free)

    def test_defense_can_reclaim_a_sector_report(self):
        free = Position(16, 19)
        self.bot.sector_marker_pads = {Direction.WEST: free}
        self.bot.sector_marker_values = {Direction.WEST: 123}
        self.c.can_place_marker.side_effect = lambda pos: pos == free
        self.assertEqual(self.bot.find_defender_order_pad(self.c), free)
        self.assertNotIn(Direction.WEST, self.bot.sector_marker_pads)

    def test_active_intruder_handoff_cannot_be_reassigned(self):
        only_free = Position(16, 19)
        self.bot.intruder_order_pad = only_free
        self.bot.intruder_order_active = True
        self.c.can_place_marker.side_effect = lambda pos: pos == only_free
        self.assertIsNone(self.bot.find_defender_order_pad(self.c))

    def test_retiring_overbuilt_marker_preserves_the_conveyor(self):
        self.c.get_tile_building_id.return_value = 42
        self.c.get_entity_type.return_value = EntityType.CONVEYOR
        self.assertTrue(self.bot.retire_role_marker(self.c, Position(16, 19)))
        self.c.destroy.assert_not_called()




if __name__ == '__main__':
    unittest.main()
