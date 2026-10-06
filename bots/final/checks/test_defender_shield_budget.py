"""Replacing road cover must wait until the scaled barrier price is funded."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, GameError, Position, Team
from finalbot.combat.defender import DefenderBot, UnitObservation


class RoadShieldController:
    def __init__(self, titanium):
        self.titanium = titanium
        self.road = Position(8, 10)
        self.road_present = True
        self.destroyed = []
        self.barriers = []
        self.price_error = None

    def get_team(self, entity_id=None):
        return Team.A

    def get_tile_building_id(self, pos):
        return 77 if pos == self.road and self.road_present else None

    def get_entity_type(self, entity_id):
        assert entity_id == 77
        return EntityType.ROAD

    def can_destroy(self, pos):
        return pos == self.road and self.road_present

    def get_global_resources(self):
        return self.titanium, 0

    def get_barrier_cost(self):
        if self.price_error is not None:
            raise self.price_error
        return 9, 0

    def destroy(self, pos):
        assert self.can_destroy(pos)
        self.road_present = False
        self.destroyed.append(pos)

    def can_build_barrier(self, pos):
        return pos == self.road and not self.road_present and self.titanium >= 9

    def build_barrier(self, pos):
        assert self.can_build_barrier(pos)
        self.barriers.append(pos)


class DefenderShieldBudgetTests(unittest.TestCase):
    def defender(self):
        bot = DefenderBot(20, 20)
        bot.core = Position(10, 10)
        bot.nearby_units = [UnitObservation(
            42, EntityType.GUNNER, Team.B, Position(6, 10), Direction.EAST,
        )]
        return bot

    def test_existing_road_stays_when_bank_covers_base_cost_but_not_scaled_cost(self):
        c = RoadShieldController(titanium=8)
        self.assertFalse(self.defender().shield_core(c, Position(9, 10)))
        self.assertTrue(c.road_present)
        self.assertEqual(c.destroyed, [])
        self.assertEqual(c.barriers, [])

    def test_funded_replacement_destroys_road_and_builds_barrier(self):
        c = RoadShieldController(titanium=9)
        self.assertTrue(self.defender().shield_core(c, Position(9, 10)))
        self.assertEqual(c.destroyed, [c.road])
        self.assertEqual(c.barriers, [c.road])

    def test_engine_price_failure_is_propagated_before_road_is_removed(self):
        c = RoadShieldController(titanium=9)
        c.price_error = GameError('Resource ledger unavailable')
        with self.assertRaisesRegex(GameError, 'Resource ledger unavailable'):
            self.defender().shield_core(c, Position(9, 10))
        self.assertTrue(c.road_present)
        self.assertEqual(c.destroyed, [])


if __name__ == '__main__':
    unittest.main()
