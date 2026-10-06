"""Separated ore fields need longer, non-overlapping refinery input lanes."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, Position, Team
from finalbot.economy.builder.bot import BuilderBot
from finalbot.economy.refinery import available, plans


class RefineryRouteTests(unittest.TestCase):
    def finish(self, search):
        for _ in range(5000):
            try:
                next(search)
            except StopIteration as result:
                return result.value
        self.fail('refinery planning never completed')

    def setUp(self):
        self.bot = BuilderBot(21, 21)
        self.bot.team = Team.A
        self.bot.core_pos = Position(7, 8)
        self.bot.current_position = Position(5, 8)
        for y in range(21):
            for x in range(21):
                pos = Position(x, y)
                self.bot.known_env[pos] = Environment.EMPTY
                self.bot.observed_tiles.add(pos)
        self.ti, self.ax = Position(2, 2), Position(2, 17)
        self.bot.known_env[self.ti] = Environment.ORE_TITANIUM
        self.bot.known_env[self.ax] = Environment.ORE_AXIONITE

    def test_distant_sources_get_disjoint_inputs_and_a_connected_output(self):
        plan = self.finish(plans(self.bot, self.bot.current_position))
        self.assertIsNotNone(plan)
        self.assertEqual(plan[0][3], 'output')
        self.assertIn(plan[0][2], self.bot.known_connected_network())
        ti_lane = {p for p, _, _, role in plan if role == 'titanium'}
        ax_lane = {p for p, _, _, role in plan if role == 'axionite'}
        self.assertFalse(ti_lane & ax_lane)
        self.assertNotIn(plan[0][0], ti_lane | ax_lane)
        self.assertFalse({self.ax, self.ti} & (ti_lane | ax_lane))
        self.assertGreater(plan[0][0].distance_squared(self.ax), 1)
        self.assertEqual(plan[-1], (self.ax, EntityType.HARVESTER, None, 'mine'))

    def test_visible_ore_inside_a_sealed_wall_ring_is_not_a_factory_source(self):
        isolated = Position(8, 14)
        self.bot.known_env[isolated] = Environment.ORE_TITANIUM
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    self.bot.known_env[Position(isolated.x + dx, isolated.y + dy)] = Environment.WALL
        plan = self.finish(plans(self.bot, self.bot.current_position))
        self.assertIsNotNone(plan)
        source = next(p for p, _, _, role in plan if role == 'titanium_source')
        self.assertEqual(source, self.ti)

    def test_unused_port_seal_can_be_reused_for_the_factory(self):
        port = Position(3, 2)
        self.bot.tile_cache.remember_building(port, 42, EntityType.CONVEYOR, Team.A, Direction.WEST)
        self.assertTrue(available(self.bot, port, self.ti))
        self.bot.tile_cache.remember_building(port, 42, EntityType.CONVEYOR, Team.A, Direction.EAST)
        self.assertFalse(available(self.bot, port, self.ti))

    def test_a_distant_conveyor_facing_the_source_is_still_protected(self):
        pos = Position(10, 2)
        self.bot.tile_cache.remember_building(pos, 42, EntityType.CONVEYOR, Team.A, Direction.WEST)
        self.assertFalse(available(self.bot, pos, self.ti))

    def test_multi_hop_factory_input_is_not_reconnected_to_core(self):
        feed, relay, factory = Position(3, 2), Position(5, 2), Position(7, 2)
        for entity_id, (pos, target) in enumerate(((feed, relay), (relay, factory)), 40):
            self.bot.tile_cache.remember_building(pos, entity_id, EntityType.BRIDGE, Team.A)
            self.bot.known_bridge_targets[pos] = target
        self.bot.tile_cache.remember_building(factory, 42, EntityType.FOUNDRY, Team.A)
        self.assertFalse(self.bot.ore_network_needs_work(self.ti))


if __name__ == '__main__':
    unittest.main()
