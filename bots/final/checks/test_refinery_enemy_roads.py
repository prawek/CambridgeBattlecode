"""Refinery construction can reclaim roads without fighting over live lanes."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, GameConstants, Position, Team
from finalbot.economy.builder.bot import BuilderBot
from finalbot.economy.refinery import available, construction_reserve, plans, try_refinery
from finalbot.economy.refinery_routes import input_route


class RoadController:
    def __init__(self, bot, target, *, current=None, heal=False):
        self.bot, self.target = bot, target
        self.current = current or Position(target.x - 1, target.y)
        self.round = 200
        self.hp = GameConstants.ROAD_MAX_HP
        self.heal = heal
        self.events = []
        self.next_id = 100

    def get_current_round(self):
        return self.round

    def get_hp(self, entity_id):
        assert entity_id == 42
        return self.hp

    def can_move(self, direction):
        tile = self.current.add(direction)
        building = self.bot.tile_cache.building_at(tile)
        return building is None or building[0] in (EntityType.ROAD, EntityType.CONVEYOR)

    def move(self, direction):
        assert self.can_move(direction)
        self.current = self.current.add(direction)
        self.events.append(('move', self.current))

    def can_build_road(self, tile):
        return self.bot.tile_cache.building_at(tile) is None

    def build_road(self, tile):
        self.next_id += 1
        self.events.append(('road', tile))
        return self.next_id

    def can_fire(self, tile):
        return tile == self.current == self.target and self.hp > 0

    def fire(self, tile):
        assert self.can_fire(tile), 'a builder can attack the road only from its tile'
        self.hp -= GameConstants.BUILDER_BOT_ATTACK_DAMAGE
        self.events.append(('fire', tile))

    def can_build(self, kind, tile, extra):
        return (self.bot.tile_cache.building_at(tile) is None
                and (kind == EntityType.CONVEYOR or tile != self.current)
                and self.current.distance_squared(tile) <= 2)

    def build(self, kind, tile, extra):
        assert self.can_build(kind, tile, extra)
        self.next_id += 1
        self.events.append(('build', kind, tile))
        return self.next_id

    def destroy(self, tile):
        raise AssertionError('hostile roads must be attacked, not freely destroyed')

    def turn(self):
        if self.heal:
            self.hp = GameConstants.ROAD_MAX_HP
        self.bot.current_position = self.current
        result = try_refinery(self.bot, self, self.current)
        self.round += 1
        return result


class RefineryEnemyRoadTests(unittest.TestCase):
    def worker(self):
        bot = BuilderBot(12, 12)
        bot.team = Team.A
        bot.core_pos = Position(1, 1)
        bot.current_position = Position(4, 4)
        bot.rounds_alive = 20
        for y in range(12):
            for x in range(12):
                tile = Position(x, y)
                bot.known_env[tile] = Environment.EMPTY
                bot.observed_tiles.add(tile)
        return bot

    def finish(self, search):
        for _ in range(5000):
            try:
                next(search)
            except StopIteration as result:
                return result.value
        self.fail('refinery search never completed')

    def road_project(self, kind=EntityType.CONVEYOR, *, heal=False):
        bot = self.worker()
        target = Position(5, 4)
        role = 'titanium_source' if kind == EntityType.HARVESTER else 'titanium'
        extra = Position(8, 4) if kind == EntityType.BRIDGE else Direction.EAST if kind == EntityType.CONVEYOR else None
        if kind == EntityType.HARVESTER:
            bot.known_env[target] = Environment.ORE_TITANIUM
        bot.tile_cache.remember_building(target, 42, EntityType.ROAD, Team.B)
        bot.tile_cache.visible_tiles = {target}
        project = [(target, kind, extra, role)]
        bot.refinery_project = project
        bot.refinery_index = 0
        bot.refinery_progress = 200
        c = RoadController(bot, target, current=target if heal else None, heal=heal)
        return bot, c, project

    def test_enemy_roads_are_available_and_can_cover_both_recipe_sources(self):
        bot = self.worker()
        ti, ax = Position(4, 2), Position(4, 5)
        bot.known_env[ti] = Environment.ORE_TITANIUM
        bot.known_env[ax] = Environment.ORE_AXIONITE
        bot.tile_cache.remember_building(ti, 42, EntityType.ROAD, Team.B)
        bot.tile_cache.remember_building(ax, 43, EntityType.ROAD, Team.B)
        self.assertTrue(available(bot, ti))
        plan = self.finish(plans(bot, bot.current_position))
        self.assertIsNotNone(plan)
        self.assertIn((ti, EntityType.HARVESTER, None, 'titanium_source'), plan)
        self.assertEqual(plan[-1], (ax, EntityType.HARVESTER, None, 'mine'))
        bot.tile_cache.remember_building(ti, 42, EntityType.CONVEYOR, Team.B, Direction.EAST)
        self.assertFalse(available(bot, ti, ax))

    def test_road_is_entered_then_shot_and_the_saved_conveyor_is_built(self):
        bot, c, project = self.road_project()
        self.assertTrue(c.turn())
        self.assertEqual(c.events, [('move', c.target)])
        self.assertIs(bot.refinery_project, project)
        self.assertTrue(c.turn())
        self.assertTrue(c.turn())
        self.assertIsNone(bot.tile_cache.building_at(c.target))
        self.assertEqual(bot.refinery_index, 0)
        self.assertTrue(c.turn())
        self.assertEqual(c.events[-1], ('build', EntityType.CONVEYOR, c.target))
        self.assertEqual(bot.refinery_index, 1)
        self.assertIs(bot.refinery_project, project)

    def test_nonpassable_recipe_components_are_built_after_vacating_the_road(self):
        for kind in (EntityType.FOUNDRY, EntityType.HARVESTER, EntityType.BRIDGE):
            with self.subTest(kind=kind):
                bot, c, project = self.road_project(kind)
                for _ in range(3):
                    self.assertTrue(c.turn())
                self.assertEqual(c.current, c.target)
                self.assertTrue(c.turn())
                self.assertNotEqual(c.current, c.target)
                self.assertFalse(any(event[0] == 'build' for event in c.events))
                self.assertTrue(c.turn())
                self.assertEqual(c.events[-1], ('build', kind, c.target))

    def test_healed_road_stops_after_four_shots_and_recovery_respects_cooldown(self):
        bot, c, project = self.road_project(heal=True)
        bot.refinery_recipe = project
        for _ in range(4):
            self.assertTrue(c.turn())
        self.assertFalse(c.turn())
        retry = c.round - 1 + 64
        self.assertIsNone(bot.refinery_project)
        self.assertEqual(bot.refinery_retry, retry)
        self.assertEqual(sum(event[0] == 'fire' for event in c.events), 4)
        for now in (c.round, retry - 1):
            c.round = now
            self.assertFalse(c.turn())
            self.assertIsNone(bot.refinery_project)
        self.assertEqual(sum(event[0] == 'fire' for event in c.events), 4)
        c.round = retry
        self.assertTrue(c.turn())
        self.assertIs(bot.refinery_project, project)
        self.assertEqual(bot.refinery_road_attacks[c.target], 1)

    def test_preflight_includes_the_attack_budget(self):
        bot, _, project = self.road_project()
        c = Mock()
        c.get_conveyor_cost.return_value = (3, 0)
        c.get_builder_bot_cost.return_value = (30, 0)
        occupied = construction_reserve(bot, c, project)
        bot.tile_cache.forget_building(project[0][0])
        empty = construction_reserve(bot, c, project)
        self.assertGreaterEqual(occupied - empty, 2 * GameConstants.BUILDER_BOT_ATTACK_COST[0])

    def test_stalled_clearance_also_delays_recovery_when_no_shot_was_possible(self):
        bot, c, project = self.road_project(heal=True)
        bot.refinery_recipe = project
        bot.refinery_progress = 120
        c.can_fire = lambda tile: False
        self.assertTrue(c.turn())  # 80 rounds since the last construction action.
        self.assertFalse(c.turn())
        retry = c.round - 1 + 64
        self.assertEqual(bot.refinery_road_retry, retry)
        self.assertIsNone(bot.refinery_project)
        self.assertIsNone(bot.refinery_road_project)
        self.assertFalse(bot.refinery_road_attacks)
        self.assertFalse(any(event[0] == 'fire' for event in c.events))
        c.round = retry - 1
        self.assertFalse(c.turn())
        self.assertIsNone(bot.refinery_project)
        c.round = retry
        self.assertTrue(c.turn())
        self.assertIs(bot.refinery_project, project)

    def test_route_prefers_an_equally_short_clear_port_to_a_hostile_road(self):
        bot = self.worker()
        ore, factory = Position(3, 3), Position(5, 5)
        hostile, free = Position(4, 3), Position(3, 4)
        bot.tile_cache.remember_building(hostile, 42, EntityType.ROAD, Team.B)
        plan = self.finish(input_route(bot.tile_cache, ore, factory,
                                      lambda p: p in {hostile, free}, set(), team=Team.A))
        self.assertIsNotNone(plan)
        self.assertEqual(plan[0][0], free)


if __name__ == '__main__':
    unittest.main()
