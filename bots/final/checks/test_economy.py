"""Source activation and refinery recovery contracts for final."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, Position, Team
from finalbot.economy.builder.bot import BuilderBot
import finalbot.economy.refinery as refinery


class SourceActivationTests(unittest.TestCase):
    def setUp(self):
        self.bot = BuilderBot(8, 8)
        self.bot.team = Team.A
        self.bot.core_pos = Position(1, 1)
        self.current, self.ore = Position(3, 3), Position(4, 3)
        self.bot.current_position = self.current
        for x in range(8):
            for y in range(8):
                self.bot.known_env[Position(x, y)] = Environment.EMPTY
        self.bot.known_env[self.ore] = Environment.ORE_TITANIUM
        self.bot.observed_tiles.add(self.ore)
        self.c = Mock()
        self.c.can_build_harvester.return_value = True
        self.c.build_harvester.return_value = 100

    def test_discovered_mine_waits_for_its_productive_outlet(self):
        self.bot.assign_connection_target = Mock(return_value=True)
        self.bot.harvester_is_connected = Mock(return_value=False)
        self.assertTrue(self.bot.try_build_nearby_harvester(self.c, self.current))
        self.bot.assign_connection_target.assert_called_once_with(self.c, self.current, self.ore)
        self.c.build_harvester.assert_not_called()

    def test_connection_is_retained_until_source_is_activated(self):
        self.bot.target_ore = self.ore
        self.bot.target_is_connection = True
        self.bot.harvester_is_connected = Mock(return_value=True)
        self.bot.ore_needs_capacity_relief = Mock(return_value=False)
        self.assertFalse(self.bot.release_connected_ore_target())
        self.assertEqual(self.bot.target_ore, self.ore)

    def test_finished_outlet_activates_source_at_end_of_construction(self):
        self.bot.target_ore = self.ore
        self.bot.target_is_connection = True
        self.bot.harvester_is_connected = Mock(return_value=True)
        self.bot.follow_path_and_build(self.c)
        self.c.build_harvester.assert_called_once_with(self.ore)
        self.assertEqual(self.bot.tile_cache.building_at(self.ore), (EntityType.HARVESTER, Team.A))

    def test_enemy_owned_source_still_consumes_allied_lane_capacity(self):
        lane = Position(4, 2)
        self.bot.tile_cache.remember_building(lane, 10, EntityType.CONVEYOR, Team.A,
                                             direction=Direction.WEST)
        self.bot.tile_cache.remember_building(Position(3, 2), 13, EntityType.CONVEYOR, Team.A,
                                             direction=Direction.WEST)
        for entity_id, (ore, team) in enumerate(((Position(4, 1), Team.A), (Position(4, 3), Team.B)), 11):
            self.bot.known_env[ore] = Environment.ORE_TITANIUM
            self.bot.tile_cache.remember_building(ore, entity_id, EntityType.HARVESTER, team)
        loads = self.bot.known_network_loads(self.bot.known_connected_network())
        self.assertEqual(loads[lane], 2)


class RefineryRecoveryTests(unittest.TestCase):
    def test_an_enemy_harvester_remains_a_valid_recipe_source(self):
        bot = BuilderBot(8, 8)
        bot.team = Team.A
        ore = Position(4, 4)
        bot.known_env[ore] = Environment.ORE_TITANIUM
        bot.tile_cache.remember_building(ore, 42, EntityType.HARVESTER, Team.B)
        self.assertTrue(refinery.step_matches(bot, (ore, EntityType.HARVESTER, None, 'titanium_source')))

    def setUp(self):
        self.bot = BuilderBot(9, 9)
        self.bot.team = Team.A
        self.bot.core_pos = Position(1, 1)
        self.bot.current_position = Position(4, 4)
        self.out, self.factory = Position(3, 3), Position(4, 3)
        self.feed, self.ore = Position(4, 4), Position(4, 5)
        self.recipe = [
            (self.out, EntityType.BRIDGE, Position(2, 2), 'output'),
            (self.factory, EntityType.FOUNDRY, None, 'foundry'),
            (self.feed, EntityType.CONVEYOR, Direction.NORTH, 'axionite'),
            (self.ore, EntityType.HARVESTER, None, 'mine'),
        ]
        for x in range(9):
            for y in range(9):
                self.bot.known_env[Position(x, y)] = Environment.EMPTY
        self.bot.known_env[self.ore] = Environment.ORE_AXIONITE
        for entity_id, (pos, kind, extra, _) in enumerate(self.recipe[:-1], 100):
            self.bot.tile_cache.remember_building(pos, entity_id, kind, Team.A,
                                                direction=extra if kind == EntityType.CONVEYOR else None)
        self.bot.known_bridge_targets[self.out] = Position(2, 2)
        self.bot.refinery_project = self.recipe
        self.bot.refinery_index = 3
        self.bot.refinery_progress = 200
        self.c = Mock()
        self.c.get_current_round.return_value = 200

    def test_destroyed_mixer_is_restored_before_raw_source_activation(self):
        self.bot.tile_cache.forget_building(self.factory)
        self.assertTrue(refinery.try_refinery(self.bot, self.c, self.bot.current_position))
        self.assertEqual(self.bot.refinery_index, 1)
        self.c.build.assert_not_called()

    def test_completed_recipe_recovers_a_visible_missing_component(self):
        self.bot.refinery_recipe = self.recipe
        self.bot.refinery_project = None
        self.bot.tile_cache.visible_tiles = {self.factory}
        self.bot.tile_cache.forget_building(self.factory)
        refinery.recover_recipe(self.bot, 300)
        self.assertIs(self.bot.refinery_project, self.recipe)
        self.assertEqual(self.bot.refinery_index, 0)

    def test_fog_alone_does_not_restart_a_completed_recipe(self):
        self.bot.refinery_recipe = self.recipe
        self.bot.refinery_project = None
        self.bot.tile_cache.visible_tiles = set()
        self.bot.tile_cache.forget_building(self.factory)
        refinery.recover_recipe(self.bot, 300)
        self.assertIsNone(self.bot.refinery_project)


if __name__ == '__main__':
    unittest.main()
