"""Moving a defender must not invalidate its own sensing and repair turn."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, GameError, Position, Team
from finalbot.combat.defender import DefenderBot


class MovingVisionController:
    def __init__(self, *, barriers=True):
        self.current = Position(10, 10)
        self.positions = {1: Position(10, 10), 42: Position(6, 10), 43: Position(14, 10)}
        self.ids = [42, 43]
        self.moved = False
        self.barriers_allowed = barriers
        self.barriers = []
        self.heals = []
        self.reads_after_move = []
        self.direction_error = None
        self.hp = 40

    def readable(self, entity_id):
        if self.moved:
            self.reads_after_move.append(entity_id)
        if entity_id not in self.positions:
            raise GameError('Unknown id')
        if self.current.distance_squared(self.positions[entity_id]) > 20:
            raise GameError('Position out of vision range')

    def get_team(self, entity_id=None):
        if entity_id is None:
            return Team.A
        self.readable(entity_id)
        return Team.A if entity_id == 1 else Team.B

    def get_entity_type(self, entity_id):
        self.readable(entity_id)
        return EntityType.CORE if entity_id == 1 else EntityType.GUNNER

    def get_position(self, entity_id=None):
        if entity_id is None:
            return self.current
        self.readable(entity_id)
        return self.positions[entity_id]

    def get_direction(self, entity_id):
        self.readable(entity_id)
        if entity_id == 43 and self.direction_error is not None:
            raise self.direction_error
        return Direction.EAST if entity_id == 42 else Direction.WEST

    def get_nearby_buildings(self):
        return [1]

    def get_nearby_units(self):
        return self.ids

    def get_hp(self, entity_id=None):
        return self.hp

    def can_move(self, direction):
        return not self.moved and direction == Direction.WEST

    def move(self, direction):
        assert self.can_move(direction)
        self.current = self.current.add(direction)
        self.moved = True

    def get_tile_building_id(self, position):
        return None

    def can_build_barrier(self, position):
        return self.barriers_allowed and self.current.distance_squared(position) <= 2

    def build_barrier(self, position):
        assert self.can_build_barrier(position)
        self.barriers.append(position)

    def can_heal(self, position):
        return self.current.distance_squared(position) <= 2

    def heal(self, position):
        assert self.can_heal(position)
        self.heals.append(position)


class DefenderVisibilityTests(unittest.TestCase):
    def test_shield_uses_new_position_and_snapshot_after_moving(self):
        c = MovingVisionController()
        bot = DefenderBot(20, 20)
        bot.run(c)
        self.assertEqual(c.current, Position(9, 10))
        self.assertEqual(c.barriers, [Position(8, 10)])
        self.assertEqual(c.reads_after_move, [])
        with self.assertRaisesRegex(GameError, 'Position out of vision range'):
            c.get_team(43)

    def test_unavailable_shield_still_allows_healing_after_moving(self):
        c = MovingVisionController(barriers=False)
        DefenderBot(20, 20).run(c)
        self.assertTrue(c.moved)
        self.assertEqual(c.heals, [c.current])
        self.assertEqual(c.reads_after_move, [])

    def test_wounded_defender_heals_its_core_tile_before_building_a_launcher(self):
        c = MovingVisionController(barriers=False)
        c.hp = 18
        bot = DefenderBot(20, 20)
        bot.intercept_raider = Mock(return_value=True)
        bot.run(c)
        self.assertEqual(c.heals, [c.current])
        bot.intercept_raider.assert_not_called()

    def test_missing_id_is_discarded_while_taking_observations(self):
        c = MovingVisionController()
        c.ids.append(99)
        bot = DefenderBot(20, 20)
        bot.run(c)
        self.assertEqual([unit.entity_id for unit in bot.nearby_units], [42, 43])

    def test_entity_leaving_vision_during_sampling_is_discarded(self):
        c = MovingVisionController()
        c.direction_error = GameError('Position out of vision range')
        bot = DefenderBot(20, 20)
        bot.run(c)
        self.assertEqual([unit.entity_id for unit in bot.nearby_units], [42])

    def test_unrelated_engine_errors_are_not_hidden(self):
        c = MovingVisionController()
        c.direction_error = GameError('Invalid direction data')
        with self.assertRaisesRegex(GameError, 'Invalid direction data'):
            DefenderBot(20, 20).run(c)


if __name__ == '__main__':
    unittest.main()
