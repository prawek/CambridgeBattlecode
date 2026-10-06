"""Shared intelligence, hostile supply and construction financing."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, Position, ResourceType, Team
from finalbot.economy.builder.bot import BuilderBot
from finalbot.core.bot import CoreBot
from finalbot.combat.intruder.bot import IntruderBot
from finalbot.combat.defense import deny_hostile_supply
from finalbot.economy.policy import fund_construction
from finalbot.world.fire_lanes import update_fire_lanes
from finalbot.shared.geometry import encode_marker
from finalbot.shared.intel import broadcast_threat, reported_threats
from finalbot.shared.constants import MARKER_KIND_THREAT
import finalbot.combat.hijack as hijack


def remember(bot, pos, kind, owner, entity_id, facing=Direction.EAST):
    bot.tile_cache.environments[pos] = Environment.EMPTY
    bot.tile_cache.remember_building(pos, entity_id, kind, owner, direction=facing)


class FinancingTests(unittest.TestCase):
    def setUp(self):
        self.c = Mock()
        self.c.get_global_resources.return_value = (10, 100)
        self.c.get_hp.return_value = 500
        self.c.get_builder_bot_cost.return_value = (30, 0)
        self.c.get_harvester_cost.return_value = (20, 0)
        self.c.get_conveyor_cost.return_value = (3, 0)

    def test_surplus_ax_funds_a_worker_and_line_while_retaining_score(self):
        fund_construction(self.c, 1)
        self.c.convert.assert_called_once_with(16)

    def test_healthy_core_preserves_its_last_refined_stacks(self):
        self.c.get_global_resources.return_value = (0, 40)
        fund_construction(self.c, 1)
        self.c.convert.assert_not_called()

    def test_critical_core_can_spend_the_last_stack(self):
        self.c.get_global_resources.return_value = (0, 10)
        self.c.get_hp.return_value = 100
        fund_construction(self.c, 1)
        self.c.convert.assert_called_once_with(10)


class IntelTests(unittest.TestCase):
    def test_first_report_is_written_without_a_previous_pad(self):
        bot = CoreBot(20, 20)
        bot.core_pos = Position(18, 18)
        bot.team = Team.B
        c = Mock()
        c.can_place_marker.return_value = True
        broadcast_threat(bot, c, [(EntityType.SENTINEL, Position(15, 17), Direction.EAST)])
        c.place_marker.assert_called_once()
        self.assertIsNotNone(bot.threat_report_pad)

    def test_invalid_report_coordinates_do_not_interrupt_construction(self):
        bot = BuilderBot(8, 8)
        bot.tile_cache.marker_values[1] = encode_marker(MARKER_KIND_THREAT, Position(99, 99), 1)
        self.assertEqual(reported_threats(bot), [])


class SupplyTests(unittest.TestCase):
    def setUp(self):
        self.bot = BuilderBot(10, 10)
        self.bot.team = Team.A
        self.bot.core_pos = Position(1, 1)
        remember(self.bot, self.bot.core_pos, EntityType.CORE, Team.A, 1)
        self.current, self.ore, self.enemy = Position(3, 3), Position(4, 3), Position(4, 4)
        remember(self.bot, self.ore, EntityType.HARVESTER, Team.A, 10)
        remember(self.bot, self.enemy, EntityType.GUNNER, Team.B, 11)
        self.c = Mock()
        self.c.can_destroy.return_value = True
        self.c.get_hp.return_value = 200
        self.c.can_fire_from.return_value = True

    def test_unsupported_mine_is_retired_before_it_arms_an_enemy(self):
        self.assertTrue(deny_hostile_supply(self.bot, self.c, self.current))
        self.c.destroy.assert_called_once_with(self.ore)

    def test_a_supported_counter_battery_keeps_its_source(self):
        remember(self.bot, Position(5, 3), EntityType.GUNNER, Team.A, 12)
        self.c.can_fire_from.return_value = True
        self.assertFalse(deny_hostile_supply(self.bot, self.c, self.current))
        self.c.destroy.assert_not_called()

    def test_a_healthy_core_keeps_its_productive_mine(self):
        self.c.get_hp.return_value = 500
        self.assertFalse(deny_hostile_supply(self.bot, self.c, self.current))
        self.c.destroy.assert_not_called()

    def test_network_repair_does_not_rebuild_under_continuous_fire(self):
        pos = Position(3, 4)
        self.bot.damaged_network_tiles.add(pos)
        self.bot.network_blueprint[pos] = EntityType.CONVEYOR, Direction.EAST, None
        self.bot.threatened_transport_tiles = {pos}
        self.assertFalse(self.bot.try_repair_nearby_network(self.c, self.current))
        self.c.build_conveyor.assert_not_called()

    def test_visible_destroyed_turret_releases_its_firing_lane(self):
        self.bot.known_hostile_turrets = {Position(6, 6): (EntityType.SENTINEL, Direction.NORTH)}
        self.bot.tile_cache.visible_entity_ids.clear()
        self.bot.tile_cache.visible_tiles = {Position(6, 6)}
        update_fire_lanes(self.bot, self.c)
        self.assertEqual(self.bot.threatened_transport_tiles, set())
        self.c.get_attackable_tiles_from.assert_not_called()


class HijackTests(unittest.TestCase):
    def setUp(self):
        self.bot = IntruderBot(16, 16)
        self.bot.team = Team.A
        self.bot.destination = Position(8, 5)
        self.bot.destination_is_confirmed_core = True
        self.bot.hijack_flow = {}
        self.bot.hijack_rejected = {}
        self.source, self.site = Position(5, 5), Position(6, 5)
        self.bot.tile_cache.visible_tiles = {self.source, self.site}
        remember(self.bot, self.source, EntityType.CONVEYOR, Team.B, 20)
        self.bot.tile_cache.environments[self.site] = Environment.EMPTY
        self.c = Mock()
        self.c.get_stored_resource.return_value = ResourceType.TITANIUM
        self.c.get_global_resources.return_value = (1000, 0)
        self.c.get_gunner_cost.return_value = (10, 0)
        self.c.get_sentinel_cost.return_value = (30, 0)

    def test_loaded_transport_can_supply_a_battery_without_a_new_mine(self):
        hijack.remember_flow(self.bot, self.c, 10)
        self.c.can_fire_from.return_value = True
        plan = hijack.choose(self.bot, self.c, self.source, 10)
        self.assertEqual(plan[:2], (self.site, self.source))
        self.assertEqual(plan[2], EntityType.GUNNER)

    def test_raw_axionite_is_not_mistaken_for_ammunition(self):
        self.c.get_stored_resource.return_value = ResourceType.RAW_AXIONITE
        hijack.remember_flow(self.bot, self.c, 10)
        self.assertEqual(self.bot.hijack_flow, {})

    def test_friendly_transport_is_never_claimed_for_assault(self):
        remember(self.bot, self.source, EntityType.CONVEYOR, Team.A, 20)
        hijack.remember_flow(self.bot, self.c, 10)
        self.assertEqual(self.bot.hijack_flow, {})
        self.c.get_stored_resource.assert_not_called()

    def test_repaired_transport_is_deferred_instead_of_attacked_forever(self):
        remember(self.bot, self.site, EntityType.CONVEYOR, Team.B, 21)
        self.bot.hijack_plan = self.site, self.source, EntityType.GUNNER, Direction.EAST
        self.bot.hijack_started = 10
        self.bot.hijack_last_hp = 20
        self.c.get_current_round.return_value = 20
        self.c.get_hp.return_value = 20
        self.assertFalse(hijack.try_hijack(self.bot, self.c, self.site))
        self.assertIsNone(self.bot.hijack_plan)
        self.c.fire.assert_not_called()


if __name__ == '__main__':
    unittest.main()
