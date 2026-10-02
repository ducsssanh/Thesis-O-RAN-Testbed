#!/usr/bin/env python3
"""Exercise launcher detachment without real sudo or radio processes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / 'scripts/legacy/compose'

class BackgroundTests(unittest.TestCase):
    def test_elevate_before_detaching_and_keep_paths(self):
        for component in ('gnb', 'ue', 'flexric'):
            with self.subTest(component=component), tempfile.TemporaryDirectory(prefix='oran background ') as temp:
                work = Path(temp)
                scripts = work / 'scripts'
                (scripts / 'lib').mkdir(parents=True)
                for name in ('env.sh', 'lib/common.sh', 'lib/start-background.sh', 'lib/launch-detached.sh'):
                    shutil.copy(LEGACY / name, scripts / name)
                commands = work / 'commands.jsonl'
                marker = work / 'started.json'
                bindir = work / 'bin'
                bindir.mkdir()
                def executable(path, body):
                    path.write_text(body)
                    path.chmod(0o755)
                executable(scripts / f'start-{component}.sh', '''#!/usr/bin/env python3
import json, os, pathlib, sys, time
pathlib.Path(os.environ['MARKER']).write_text(json.dumps({
 'elevated': os.environ.get('MOCK_ELEVATED'), 'sid': os.getsid(0),
 'config': os.environ['CONFIG_ROOT'], 'log': os.environ['LOG_ROOT'], 'args': sys.argv[1:]}))
time.sleep(1)
''')
                executable(scripts / 'lib/ue-status.sh', '''#!/bin/bash
if [[ -f "$MARKER" ]]; then echo 'User Equipment: RUNNING (ue2)'; else echo 'User Equipment: NOT_RUNNING'; fi
''')
                executable(bindir / 'pgrep', '''#!/bin/bash
[[ -f "$MARKER" ]] && echo 123
''')
                executable(bindir / 'sudo', '''#!/usr/bin/env python3
import json, os, sys
# Model a terminal-scoped sudo timestamp: detached sudo must fail.
assert os.getsid(0) == int(os.environ['CALLER_SID']), 'sudo invoked after detachment'
with open(os.environ['COMMANDS'], 'a') as f: f.write(json.dumps(sys.argv[1:]) + '\\n')
args = sys.argv[1:]
if args == ['-v']: sys.exit(0)
assert args.pop(0) == '-n'
if args[0] == '--': args.pop(0)
os.environ['MOCK_ELEVATED'] = 'yes'
os.execvp(args[0], args)
''')
                env = os.environ.copy()
                env.update(PATH=f'{bindir}:{env["PATH"]}', MARKER=str(marker), COMMANDS=str(commands),
                           CALLER_SID=str(os.getsid(0)), CODEBASE_ROOT=str(work),
                           CONFIG_ROOT=str(work / 'custom configs'), LOG_ROOT=str(work / 'custom logs'))
                env.pop('MOCK_ELEVATED', None)
                args = ['2'] if component == 'ue' else []
                result = subprocess.run(['bash', str(scripts / 'lib/start-background.sh'), component, *args],
                                        env=env, capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                info = json.loads(marker.read_text())
                self.assertNotEqual(info['sid'], os.getsid(0))
                self.assertEqual(info['config'], env['CONFIG_ROOT'])
                self.assertEqual(info['log'], env['LOG_ROOT'])
                self.assertEqual(info['args'], args)
                self.assertEqual(info['elevated'], None if component == 'flexric' else 'yes')
                if component == 'flexric': self.assertFalse(commands.exists())
                else:
                    calls = [json.loads(line) for line in commands.read_text().splitlines()]
                    self.assertEqual(calls[0], ['-v'])
                    self.assertEqual(calls[1][:3], ['-n', '--', 'env'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
