"""A clean replay does not mean the engine wrote no exception to stderr."""

from pathlib import Path
import tempfile
import unittest

from runtime_health import merge_log_errors


class RuntimeHealthTests(unittest.TestCase):
    def inspect(self, text):
        with tempfile.TemporaryDirectory(prefix='final_log_test_') as folder:
            root = Path(folder)
            path = root / 'match.log'
            path.write_text(text.replace('CANDIDATE', str(root / 'candidate').replace('/', '\\')),
                            encoding='utf8')
            runtime = [dict(errors=0, error_samples=[]), dict(errors=0, error_samples=[])]
            unknown = merge_log_errors(runtime, path, [root / 'opponent', root / 'candidate'])
            return runtime, unknown

    def test_stderr_error_is_attributed_when_replay_has_no_error(self):
        runtime, unknown = self.inspect(
            'Completed turn 300\nTraceback (most recent call last):\n'
            '  File "CANDIDATE\\finalbot\\combat\\defender.py", line 125, in shield_core\n'
            '    controller.get_team(entity_id)\n'
            'cambc._types.GameError: Position out of vision range\n'
            'Winner: sota\n')
        self.assertEqual(runtime[0]['errors'], 0)
        self.assertEqual(runtime[1]['errors'], 1)
        self.assertEqual(runtime[1]['stderr_errors'], 1)
        self.assertEqual(runtime[1]['replay_errors'], 0)
        self.assertEqual(unknown['errors'], 0)
        self.assertNotIn('Winner:', runtime[1]['error_samples'][0])

    def test_repeated_tracebacks_are_all_recorded(self):
        block = ('Traceback (most recent call last):\n'
                 '  File "CANDIDATE\\main.py", line 1, in run\n'
                 'ValueError: broken\n')
        runtime, unknown = self.inspect(block + block)
        self.assertEqual(runtime[1]['errors'], 2)

    def test_unattributed_engine_error_is_preserved(self):
        _, unknown = self.inspect('Traceback (most recent call last):\nRuntimeError: engine failed\n')
        self.assertEqual(unknown['errors'], 1)

    def test_normal_progress_output_is_not_an_exception(self):
        runtime, unknown = self.inspect('Completed turn 300\nReplay written\n')
        self.assertEqual([team['errors'] for team in runtime], [0, 0])
        self.assertEqual(unknown['errors'], 0)


if __name__ == '__main__':
    unittest.main()
