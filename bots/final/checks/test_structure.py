"""Contracts for the runtime layout and the distributable archive."""

import ast
import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

BOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT))

from package_bot import package
from runtime_files import runtime_files
from finalbot.player import Player
from finalbot.economy.builder.bot import BuilderBot
from finalbot.combat.intruder.bot import IntruderBot
from florent.main import Player as FlorentPlayer


class StructureTests(unittest.TestCase):
    def test_engine_entrypoint_exposes_the_role_dispatcher(self):
        spec = importlib.util.spec_from_file_location('final_engine_entry_test', BOT / 'main.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        controller = object()
        bot = module.Player()
        with patch.object(Player, 'run') as run:
            bot.run(controller)
            run.assert_called_once_with(controller)
        self.assertIsInstance(bot.bot, Player)

        class FlorentController:
            def read_store(self, slot):
                return 0

        controller = FlorentController()
        bot = module.Player()
        with patch.object(FlorentPlayer, 'run') as run:
            bot.run(controller)
            run.assert_called_once_with(controller)
        self.assertIsInstance(bot.bot, FlorentPlayer)

    def test_every_packaged_module_can_be_imported(self):
        for path in runtime_files(BOT):
            if path.name == 'main.py':
                continue
            name = '.'.join(path.relative_to(BOT).with_suffix('').parts).removesuffix('.__init__')
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_archive_contains_the_runtime_package_without_local_tools(self):
        with tempfile.TemporaryDirectory(prefix='final_package_test_') as folder:
            target = Path(folder) / 'final.zip'
            package(target)
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
        self.assertIn('main.py', names)
        self.assertIn('finalbot/player.py', names)
        self.assertIn('finalbot/economy/builder/routing.py', names)
        self.assertIn('finalbot/combat/intruder/supply_construction.py', names)
        self.assertIn('florent/main.py', names)
        self.assertFalse(any(name.startswith('checks/') for name in names))

    def test_role_components_do_not_shadow_each_other_or_initialize_state(self):
        for role in (BuilderBot, IntruderBot):
            package_name = role.__module__.rsplit('.', 1)[0]
            owners = {}
            for component in role.__mro__[1:]:
                if not component.__module__.startswith(package_name + '.'):
                    continue
                self.assertNotIn('__init__', component.__dict__)
                for name, value in component.__dict__.items():
                    if callable(value) or isinstance(value, (staticmethod, classmethod)):
                        self.assertNotIn(name, owners, (role.__name__, name, owners.get(name), component))
                        owners[name] = component

    def test_coordinate_allocations_remain_in_the_canonical_tile_pool(self):
        violations = []
        for path in (BOT / 'finalbot').rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf8'))
            parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'Position'):
                    continue
                owner = parents.get(node)
                while owner is not None and not isinstance(owner, ast.FunctionDef):
                    owner = parents.get(owner)
                if path.name != 'tile_cache.py' or getattr(owner, 'name', None) != '__init__':
                    violations.append(f'{path.relative_to(BOT)}:{node.lineno}')
        self.assertEqual(violations, [])


if __name__ == '__main__':
    unittest.main()
