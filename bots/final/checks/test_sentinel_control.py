"""Sentinel stun denies repairs while a gunner supplies sustained damage."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, Position, Team
from finalbot.combat.local import defend_with_battery
from finalbot.combat.sentinel import SentinelBot
from finalbot.economy.builder.bot import BuilderBot


class SentinelTargetTests(unittest.TestCase):
    def controller(self, *, core_hp=None, only_supply=False, repairer=True):
        c = Mock()
        c.get_action_cooldown.return_value = 0
        c.get_ammo_amount.return_value = 10
        c.get_position.return_value = Position(5, 5)
        c.get_team.side_effect = lambda entity_id=None: Team.A if entity_id is None else Team.B
        c.can_fire.return_value = True
        kinds = {42: EntityType.GUNNER, 43: EntityType.BUILDER_BOT, 44: EntityType.CORE,
                 45: EntityType.HARVESTER, 46: EntityType.ROAD}
        c.get_entity_type.side_effect = kinds.__getitem__
        if only_supply:
            buildings = {Position(6, 5): 45, Position(7, 5): 46}
            builders = {}
            tiles = list(buildings)
        else:
            buildings = {Position(7, 5): 42}
            builders = {Position(7, 6) if repairer else Position(8, 7): 43}
            tiles = list(buildings) + list(builders)
            if core_hp is not None:
                buildings[Position(8, 5)] = 44
                tiles.append(Position(8, 5))
        c.get_attackable_tiles.return_value = tiles
        c.get_tile_builder_bot_id.side_effect = builders.get
        c.get_tile_building_id.side_effect = buildings.get
        c.get_hp.return_value = core_hp
        return c

    def test_repairing_builder_is_targeted_before_enemy_gunner(self):
        c = self.controller()
        SentinelBot().run(c)
        c.fire.assert_called_once_with(Position(7, 6))

    def test_unrelated_scout_does_not_distract_from_enemy_gunner(self):
        c = self.controller(repairer=False)
        SentinelBot().run(c)
        c.fire.assert_called_once_with(Position(7, 5))

    def test_core_finish_uses_full_sentinel_damage_instead_of_gunner_threshold(self):
        c = self.controller(core_hp=18)
        SentinelBot().run(c)
        c.fire.assert_called_once_with(Position(8, 5))
        c.get_hp.assert_called_once_with(44)

    def test_core_footprint_uses_one_entity_and_health_snapshot(self):
        c = self.controller(core_hp=18)
        c.get_attackable_tiles.return_value = [Position(8, 5), Position(8, 6)]
        c.get_tile_builder_bot_id.return_value = None
        c.get_tile_builder_bot_id.side_effect = None
        c.get_tile_building_id.side_effect = None
        c.get_tile_building_id.return_value = 44
        SentinelBot().run(c)
        c.get_entity_type.assert_called_once_with(44)
        c.get_hp.assert_called_once_with(44)
        self.assertEqual(c.get_team.call_count, 2)

    def test_nonlethal_core_shot_does_not_displace_builder_control(self):
        c = self.controller(core_hp=19)
        SentinelBot().run(c)
        c.fire.assert_called_once_with(Position(7, 6))

    def test_adjacent_ammunition_mine_and_empty_road_are_preserved(self):
        c = self.controller(only_supply=True)
        SentinelBot().run(c)
        c.fire.assert_not_called()


class SentinelConstructionTests(unittest.TestCase):
    def attempt(self, enemy, *, repairer=False, second_weapon=False, protected_lane=False):
        bot = BuilderBot(16, 16)
        bot.team = Team.A
        bot.defense_cooldowns = {}
        ore, gun, site, west = Position(5, 5), Position(6, 5), Position(5, 4), Position(4, 5)
        for pos in (ore, gun, site, enemy, west):
            bot.known_env[pos] = Environment.EMPTY
        bot.known_env[ore] = Environment.ORE_TITANIUM
        bot.tile_cache.visible_tiles = {ore}
        bot.tile_cache.remember_building(ore, 1, EntityType.HARVESTER, Team.A)
        bot.tile_cache.remember_building(gun, 2, EntityType.GUNNER, Team.A, Direction.EAST)
        bot.tile_cache.remember_building(enemy, 3, EntityType.BUILDER_BOT, Team.B)
        bot.tile_cache.remember_building(west, 5, EntityType.CONVEYOR, Team.A, Direction.NORTH)
        if repairer:
            enemy_gun = Position(enemy.x + 1, enemy.y)
            bot.known_env[enemy_gun] = Environment.EMPTY
            bot.tile_cache.remember_building(enemy_gun, 6, EntityType.GUNNER, Team.B, Direction.WEST)
        if second_weapon:
            bot.tile_cache.remember_building(site, 4, EntityType.SENTINEL, Team.A, Direction.EAST)
        if protected_lane:
            bot.tile_cache.remember_building(site, 4, EntityType.CONVEYOR, Team.A, Direction.NORTH)
        c = Mock()
        c.get_current_round.return_value = 30
        c.get_cpu_time_elapsed.return_value = 0
        c.can_fire_from.return_value = True
        c.can_build.return_value = True
        c.build.return_value = 42
        c.get_global_resources.return_value = (1000, 0)
        c.get_gunner_cost.return_value = (10, 0)
        c.get_sentinel_cost.return_value = (30, 0)
        result = defend_with_battery(bot, c, Position(4, 4))
        return result, c, bot, site

    def test_nearby_repairer_gets_control_beside_existing_gunner(self):
        built, c, _, site = self.attempt(Position(8, 4), repairer=True)
        self.assertTrue(built)
        self.assertEqual(c.build.call_args.args[:2], (EntityType.SENTINEL, site))

    def test_mobile_scout_alone_uses_the_cheaper_gunner(self):
        built, c, _, site = self.attempt(Position(8, 4))
        self.assertTrue(built)
        self.assertEqual(c.build.call_args.args[:2], (EntityType.GUNNER, site))

    def test_distant_builder_does_not_trigger_control_purchase(self):
        built, c, _, _ = self.attempt(Position(10, 4), repairer=True)
        self.assertFalse(built)
        c.build.assert_not_called()

    def test_existing_two_weapon_cap_is_preserved(self):
        built, c, _, _ = self.attempt(Position(8, 4), repairer=True, second_weapon=True)
        self.assertFalse(built)
        c.build.assert_not_called()

    def test_productive_conveyor_is_not_removed_for_control_weapon(self):
        built, c, bot, site = self.attempt(Position(8, 4), repairer=True, protected_lane=True)
        self.assertFalse(built)
        c.destroy.assert_not_called()
        self.assertEqual(bot.tile_cache.building_at(site), (EntityType.CONVEYOR, Team.A))

    def test_sentinel_can_counter_a_close_gun_across_the_supplying_mine(self):
        bot = BuilderBot(16, 16)
        bot.team = Team.A
        bot.defense_cooldowns = {}
        ore, site, enemy, west = Position(5, 5), Position(5, 4), Position(5, 6), Position(4, 5)
        for pos in (ore, site, enemy, west):
            bot.known_env[pos] = Environment.EMPTY
        bot.known_env[ore] = Environment.ORE_TITANIUM
        bot.tile_cache.visible_tiles = {ore}
        bot.tile_cache.remember_building(ore, 1, EntityType.HARVESTER, Team.A)
        bot.tile_cache.remember_building(enemy, 2, EntityType.GUNNER, Team.B, Direction.SOUTH)
        bot.tile_cache.remember_building(west, 3, EntityType.CONVEYOR, Team.A, Direction.NORTH)
        c = Mock()
        c.get_current_round.return_value = 30
        c.get_cpu_time_elapsed.return_value = 0
        c.can_fire_from.side_effect = lambda _site, _facing, kind, target: (
            kind == EntityType.SENTINEL and target == enemy)
        c.can_build.return_value = True
        c.build.return_value = 42
        self.assertTrue(defend_with_battery(bot, c, Position(4, 4)))
        self.assertEqual(c.build.call_args.args[:2], (EntityType.SENTINEL, site))
        c.destroy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
