"""Refinery planning must not fixate on the closest sealed-off mine."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cambc import Direction, EntityType, Environment, Position, Team
from finalbot.economy.builder.bot import BuilderBot
from finalbot.economy.refinery import plans


class RefinerySourceChoiceTests(unittest.TestCase):
    def test_farther_source_is_used_when_the_nearest_mine_has_no_free_port(self):
        bot = BuilderBot(21, 21)
        bot.team = Team.A
        bot.core_pos = Position(10, 10)
        bot.current_position = Position(8, 10)
        for y in range(21):
            for x in range(21):
                tile = Position(x, y)
                bot.known_env[tile] = Environment.EMPTY
                bot.observed_tiles.add(tile)
        nearest, farther, ax = Position(8, 12), Position(2, 2), Position(8, 17)
        bot.known_env[nearest] = Environment.ORE_TITANIUM
        bot.known_env[farther] = Environment.ORE_TITANIUM
        bot.known_env[ax] = Environment.ORE_AXIONITE
        bot.tile_cache.remember_building(nearest, 40, EntityType.HARVESTER, Team.A)
        for entity_id, direction in enumerate((Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST), 41):
            port = bot.tile_cache.neighbor(nearest, direction)
            bot.tile_cache.remember_building(port, entity_id, EntityType.GUNNER, Team.A, direction)

        search = plans(bot, bot.current_position)
        for _ in range(5000):
            try:
                next(search)
            except StopIteration as result:
                plan = result.value
                break
        else:
            self.fail('bounded refinery search never completed')
        self.assertIsNotNone(plan)
        source = next(tile for tile, _, _, role in plan if role == 'titanium_source')
        self.assertEqual(source, farther)
        self.assertEqual(plan[-1], (ax, EntityType.HARVESTER, None, 'mine'))
        self.assertIn(plan[0][2], bot.known_connected_network())


if __name__ == '__main__':
    unittest.main()
