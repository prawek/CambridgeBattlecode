"""Ore supports roads, transport and weapons; only a mine source is reserved."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, Position, Team
from finalbot.combat.intruder.bot import IntruderBot
from finalbot.combat.siege_planner import buildable
from finalbot.economy.builder.bot import BuilderBot


class OreTerrainTests(unittest.TestCase):
    def worker(self):
        bot = BuilderBot(9, 9)
        bot.team = Team.A
        bot.core_pos = Position(1, 4)
        bot.current_position = Position(5, 4)
        bot.work_direction = Direction.EAST
        for y in range(9):
            for x in range(9):
                bot.known_env[Position(x, y)] = Environment.WALL
        for x in range(7):
            bot.known_env[Position(x, 4)] = Environment.EMPTY
        for y in range(3, 6):
            for x in range(3):
                bot.known_env[Position(x, y)] = Environment.EMPTY
        for x in (3, 4, 6):
            bot.known_env[Position(x, 4)] = Environment.ORE_TITANIUM
        return bot

    def test_conveyor_route_crosses_dense_ore_but_leaves_source_free(self):
        bot = self.worker()
        c = Mock()
        c.get_conveyor_cost.return_value = (3, 0)
        c.get_bridge_cost.return_value = (20, 0)
        source = Position(6, 4)
        plan = bot.connection_plan(c, source)
        self.assertIsNotNone(plan)
        _, tiles, _, bridges, _ = plan
        self.assertIn(Position(3, 4), tiles)
        self.assertIn(Position(4, 4), tiles)
        self.assertNotIn(source, tiles)
        self.assertFalse(bridges)
        self.assertTrue(bot.assign_connection_target(c, bot.current_position, source))

    def test_walk_uses_ore_corridor_without_classifying_it_as_a_wall(self):
        bot = self.worker()
        ore = Position(4, 4)
        path = bot.ore_walk(Position(5, 4), {Position(3, 4)})
        self.assertIn(ore, path)
        bot.mark_staticly_blocked(ore)
        self.assertNotIn(ore, bot.permanently_blocked)
        self.assertFalse(bot.traversable_for_planning(None, Position(4, 3)))

    def test_search_cache_keeps_the_reserved_source_in_its_identity(self):
        bot = self.worker()
        network = bot.known_connected_network()
        args = ([Position(5, 4)], {Position(2, 4)}, network, 3, 20, {Position(3, 4)}, {})
        first = bot.transport_flow_augmentation(*args, source_ore=Position(6, 4))
        self.assertIn(Position(4, 4), first[0])
        second = bot.transport_flow_augmentation(*args, source_ore=Position(4, 4))
        self.assertIsNotNone(second)
        self.assertNotIn(Position(4, 4), second[0])

    def test_productive_transport_on_ore_is_not_selected_as_a_new_mine(self):
        bot = self.worker()
        tile = Position(4, 4)
        bot.tile_cache.remember_building(tile, 42, EntityType.CONVEYOR, Team.A, Direction.WEST)
        self.assertNotIn(tile, bot.mineable_ores())
        self.assertIn(Position(6, 4), bot.mineable_ores())

    def test_intruder_and_weapon_planner_accept_ore_terrain(self):
        bot = IntruderBot(9, 9)
        bot.team = Team.A
        ore = Position(4, 4)
        bot.known_env[ore] = Environment.ORE_TITANIUM
        self.assertTrue(bot.is_roadable_position(ore))
        self.assertTrue(bot.is_supply_tile(ore))
        self.assertTrue(bot.is_gunner_site_locally_viable(ore))
        self.assertTrue(buildable(bot, ore))
        bot.tile_cache.remember_building(ore, 42, EntityType.HARVESTER, Team.A)
        self.assertFalse(bot.is_roadable_position(ore))
        self.assertFalse(buildable(bot, ore))

    def test_an_ore_exit_does_not_make_the_intruder_backtrack(self):
        bot = IntruderBot(9, 9)
        bot.team = Team.A
        current = Position(4, 4)
        for direction in Direction:
            tile = bot.tile_cache.neighbor(current, direction)
            bot.known_env[tile] = Environment.WALL
        bot.known_env[Position(5, 4)] = Environment.ORE_TITANIUM
        bot.left_wall_directions = lambda heading: (Direction.EAST,)
        self.assertTrue(bot.has_unvisited_exploration_exit(current))
        self.assertTrue(bot.has_unvisited_exploration_wall_exit(current, Position(4, 1), 'left'))
        self.assertTrue(bot.return_path_traversable(Position(5, 4)))


if __name__ == '__main__':
    unittest.main()
