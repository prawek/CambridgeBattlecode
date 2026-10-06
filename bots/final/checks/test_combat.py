"""Regression checks for supplied weapons and bounded siege planning."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, Position, Team
import finalbot.combat.assault as assault
from finalbot.combat.gunner import GunnerBot
from finalbot.combat.intruder.bot import IntruderBot
import finalbot.combat.siege_planner as siege_planner


class CombatRegressionTests(unittest.TestCase):
    def setUp(self):
        self.bot = IntruderBot(16, 16)
        self.bot.team = Team.A
        self.bot.entity_id = 1
        self.bot.current_position = Position(6, 6)
        self.bot.siege_rejected = {}

    def remember(self, pos, kind, owner=Team.A, entity_id=2):
        self.bot.known_env[pos] = Environment.EMPTY
        self.bot.tile_cache.remember_building(pos, entity_id, kind, owner)

    def test_adjacent_enemy_mine_is_preserved_as_ammunition(self):
        bot = GunnerBot(16, 16)
        bot.current_position = Position(6, 6)
        bot._scan_turn = lambda *a, **k: True
        c = Mock()
        c.get_team.side_effect = lambda entity_id=None: Team.A if entity_id is None else Team.B
        c.get_attackable_tiles.return_value = [Position(7, 6)]
        c.get_tile_builder_bot_id.return_value = None
        c.get_tile_building_id.return_value = 8
        c.get_entity_type.return_value = EntityType.HARVESTER
        c.can_fire.return_value = True
        bot.run(c)
        c.fire.assert_not_called()

    def test_guarded_enemy_port_is_not_a_direct_siege_site(self):
        pos = Position(7, 6)
        self.remember(pos, EntityType.CONVEYOR, Team.B)
        self.assertFalse(siege_planner.buildable(self.bot, pos))
        self.remember(pos, EntityType.ROAD, Team.B)
        self.assertTrue(siege_planner.buildable(self.bot, pos))

    def test_launcher_displacement_is_a_counter_battery_target(self):
        ore, launcher = Position(7, 6), Position(8, 6)
        self.bot.destination = Position(10, 10)
        self.bot.destination_is_confirmed_core = False
        self.remember(ore, EntityType.HARVESTER, Team.B, entity_id=30)
        self.remember(launcher, EntityType.LAUNCHER, Team.B, entity_id=31)
        self.bot.known_env[ore] = Environment.ORE_TITANIUM
        for pos in (Position(7, 5), Position(7, 7), Position(6, 6)):
            self.bot.known_env[pos] = Environment.EMPTY
        self.bot.tile_cache.visible_tiles = {ore, launcher}
        search = siege_planner.candidate_search(self.bot, self.bot.current_position, 100)
        while True:
            try:
                next(search)
            except StopIteration as result:
                candidates = result.value
                break
        self.assertTrue(any(candidate[5] == launcher for candidate in candidates))

    def test_sentinel_has_offset_facing_when_target_is_behind_intake(self):
        site, source, target = Position(6, 6), Position(6, 7), Position(6, 10)
        facings = siege_planner.firing_facings(site, target, EntityType.SENTINEL, source)
        self.assertNotIn(Direction.SOUTH, facings)
        self.assertIn(Direction.SOUTHEAST, facings)
        self.assertIn(Direction.SOUTHWEST, facings)

    def test_rotation_does_not_count_as_battery_loss(self):
        pos = Position(7, 6)
        self.remember(pos, EntityType.GUNNER, entity_id=20)
        self.bot.tile_cache.visible_tiles = {pos}
        self.bot.siege_batteries = {pos: (20, 10)}
        self.bot.tile_cache.remember_building(pos, 20, EntityType.GUNNER,
                                              Team.A, direction=Direction.SOUTH)
        assault.update_battery_losses(self.bot, 15)
        self.assertEqual(self.bot.siege_rejected, {})
        self.bot.tile_cache.forget_building(pos)
        assault.update_battery_losses(self.bot, 16)
        self.assertEqual(self.bot.siege_rejected[pos], 112)

    def test_unseen_battery_is_not_counted_as_lost(self):
        self.bot.siege_batteries = {Position(7, 6): (20, 10)}
        assault.update_battery_losses(self.bot, 15)
        self.assertEqual(self.bot.siege_rejected, {})

    def test_failed_known_route_switches_to_new_terrain(self):
        target = Position(9, 6)
        with patch('finalbot.combat.intruder.movement.a_star_to_any', return_value=[]):
            self.bot.advance_towards_unvisited_target = Mock(return_value=True)
            self.assertTrue(self.bot.advance_towards_revisitable_target(Mock(), target))
        self.bot.advance_towards_unvisited_target.assert_called_once_with(unittest.mock.ANY, target)

    def test_launcher_zone_is_removed_only_after_direct_observation(self):
        pos = Position(8, 6)
        self.bot.enemy_launcher_positions = {pos}
        self.bot.refresh_enemy_launchers()
        self.assertTrue(self.bot.in_launcher_zone(Position(7, 6)))
        self.bot.tile_cache.visible_tiles = {pos}
        self.bot.refresh_enemy_launchers()
        self.assertFalse(self.bot.in_launcher_zone(Position(7, 6)))


if __name__ == '__main__':
    unittest.main()
