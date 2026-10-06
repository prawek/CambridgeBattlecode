"""Replay events can update existing entities without constructing them."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_summary import summarize


def integer(value):
    value &= (1 << 64) - 1
    data = bytearray()
    while value >= 128:
        data.append((value & 127) | 128)
        value >>= 7
    data.append(value)
    return bytes(data)


def number(key, value):
    return integer(key << 3) + integer(value)


def message(key, value):
    return integer((key << 3) | 2) + integer(len(value)) + value


class ReplaySummaryTests(unittest.TestCase):
    def test_rotation_is_not_a_second_construction(self):
        pos = message(3, number(1, 5) + number(2, 5))
        core = number(1, 1) + pos
        gun = number(1, 3) + pos
        initial = message(1, message(4, core))
        first = message(3, message(1, message(1, message(1, gun + message(21, number(1, 3))))))
        rotated = message(3, message(1, message(1, message(1, gun + message(21, number(1, 4))))))
        replay = Mock()
        replay.read_bytes.return_value = initial + first + rotated
        result = summarize(replay)
        self.assertEqual(result['teams'][0]['placed']['gunner'], 1)
        self.assertEqual(result['teams'][0]['rotations'], 1)
        self.assertEqual(result['teams'][0]['alive']['gunner'], 1)

    def test_core_hp_accepts_signed_damage_and_repair_deltas(self):
        core = number(1, 1) + message(3, b'')
        initial = message(1, message(4, core))
        hit = message(3, message(1, message(5, number(1, 1) + number(2, -18))))
        heal = message(3, message(1, message(5, number(1, 1) + number(2, 4))))
        replay = Mock()
        replay.read_bytes.return_value = initial + hit + heal
        result = summarize(replay)
        self.assertEqual(result['teams'][0]['core_hp'], 486)


if __name__ == '__main__':
    unittest.main()
