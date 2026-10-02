#!/usr/bin/env python3
"""Port regression tests. No real sudo, Docker, network changes, builds or RF processes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / 'scripts/legacy/compose'


class PortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='oran port ')
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.bin = self.work / 'bin'
        self.bin.mkdir()
        self.calls = self.work / 'calls.jsonl'
        self.env = os.environ.copy()
        self.env.update(CONFIG_ROOT=str(self.work / 'configs'), ARTIFACT_ROOT=str(self.work / 'artifacts'),
                        CORE_COMPOSE_DIR=str(self.work / 'compose/core'), LOG_ROOT=str(self.work / 'artifacts/logs'),
                        EXPERIMENT_ROOT=str(self.work / 'artifacts/experiments'),
                        CORE_OPTIONS=str(self.work / 'configs/core/options.yaml'),
                        PATH=f'{self.bin}:{os.environ["PATH"]}', CALLS=str(self.calls))
        cfg = self.work / 'configs/core'
        cfg.mkdir(parents=True)
        shutil.copy(ROOT / 'configs/core/options.yaml', cfg / 'options.yaml')
        self.stub('sudo', 'raise SystemExit("Unexpected privileged command: " + repr(sys.argv))')
        self.stub('docker', 'raise SystemExit("Unexpected Docker command: " + repr(sys.argv))')
        self.stub('pgrep', 'sys.exit(1)')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text('#!/usr/bin/env python3\nimport sys, os, json, pathlib, signal, time\n'
                        'with open(os.environ["CALLS"], "a") as f: f.write(json.dumps([pathlib.Path(sys.argv[0]).name, *sys.argv[1:]]) + "\\n")\n'
                        + body + '\n')
        path.chmod(0o755)
        return path

    def run_script(self, name, *args, success=True, env=None, script_root=None):
        result = subprocess.run(['bash', str((script_root or LEGACY) / name), *args],
                                cwd='/tmp', env=env or self.env, text=True, capture_output=True, timeout=35)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def commands(self):
        return [json.loads(s) for s in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def config(self, expr):
        subprocess.run(['yq', '-i', expr, self.env['CORE_OPTIONS']], check=True)

    def test_syntax_and_help(self):
        for path in LEGACY.rglob('*.sh'):
            subprocess.run(['bash', '-n', str(path)], check=True)
        for path in LEGACY.glob('*.sh'):
            if path.name != 'env.sh':
                self.run_script(path.name, '--help')
        self.assertFalse(self.commands())

    def test_configuration_generation_with_spaces(self):
        core = self.work / 'configs/core'
        (core / 'get_amf_address.txt').write_text('192.168.62.11\n192.168.63.1\n192.168.62.1\n')
        self.run_script('configure-flexric.sh')
        self.run_script('configure-gnb.sh')
        self.run_script('configure-ue.sh')
        gnb = (self.work / 'configs/gnb/gnb.conf').read_text()
        self.assertIn('192.168.62.11', gnb)
        self.assertIn(str(ROOT / 'src/flexric/build/flexric_libraries/lib/flexric'), gnb)
        self.assertNotIn('O-RAN-Testbed-Automation', gnb)
        self.assertTrue((self.work / 'configs/gnb/split_du3.conf').exists())
        ue = (self.work / 'configs/ue/ue2.conf').read_text()
        self.assertIn('001010123456790', ue)
        self.assertIn('nist-dnn', ue)
        self.assertIn('rfsimu_channel_ue2', (self.work / 'configs/ue/channelmod_rfsimu.conf').read_text())
        self.assertFalse(any(c[0] in ('sudo', 'docker') for c in self.commands()))

    def test_upf_explicit_false_and_snapshot_build(self):
        self.config('.oai_upf.build_local_image = false | .oai_upf.enable_usage_reporting = false | .oai_upf.datapath = "simple-switch"')
        self.run_script('lib/oai-upf-profile.sh', 'validate')
        self.run_script('build-upf.sh')
        self.assertFalse(self.commands())
        self.config('.oai_upf.build_local_image = true')
        self.stub('docker', 'sys.exit(0)')
        self.run_script('build-upf.sh')
        build = next(c for c in self.commands() if c[:2] == ['docker', 'build'])
        self.assertEqual(build[-1], str(ROOT / 'src/oai-upf'))
        self.assertIn('GIT_COMMIT=snapshot', build)
        self.assertIn('oai-upf-research:local', build)
        self.config('.oai_upf.enable_usage_reporting = true')
        self.run_script('lib/oai-upf-profile.sh', 'validate', success=False)

    def fake_sources(self):
        ran = self.work / 'ran'
        build = ran / 'cmake_targets/ran_build/build'
        build.mkdir(parents=True)
        flex = self.work / 'flex'
        for relative in ('build/examples/ric/nearRT-RIC', 'build/examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv'):
            p = flex / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('#!/bin/bash\nprintf "%s\\n" "$@" >"$CALLS.binary"\n')
            p.chmod(0o755)
        for name in ('nr-softmodem', 'nr-uesoftmodem'):
            p = build / name
            p.write_text('#!/bin/bash\nexit 0\n')
            p.chmod(0o755)
        for component, names in [('gnb', ['gnb.conf']), ('ue', ['ue1.conf']), ('flexric', ['flexric.conf'])]:
            d = self.work / 'configs' / component
            d.mkdir(exist_ok=True)
            for n in names:
                (d / n).write_text('')
            (d / 'get_rfsim_server_address.txt').write_text('127.0.0.1\n')
        self.env.update(RAN_SRC=str(ran), FLEXRIC_SRC=str(flex))
        return ran, flex

    def test_launch_arguments_and_xapp(self):
        ran, flex = self.fake_sources()
        self.stub('script', 'sys.exit(0)')
        # sudo only delegates the terminal recorder; namespace operations are recorded mocks.
        self.stub('sudo', '''
if sys.argv[1] == 'script': os.execvp('script', sys.argv[1:])
if sys.argv[1:4] == ['ip', 'netns', 'delete']: sys.exit(0)
if 'iptables' in sys.argv: sys.exit(0)
sys.exit(0)''')
        self.stub('ip', "print('default via 192.0.2.1 dev eth0')")
        self.run_script('start-gnb.sh')
        self.run_script('start-ue.sh', '1')
        calls = [c for c in self.commands() if c[0] == 'script']
        self.assertEqual(len(calls), 2)
        self.assertIn(str(self.work / 'configs/gnb/gnb.conf'), calls[0][4])
        self.assertIn(str(self.work / 'configs/ue/ue1.conf'), calls[1][4])
        self.assertIn('--numerology 1 --band 78 -C 3619200000', calls[1][4])
        self.assertNotIn('../../../../', calls[1][4])
        self.run_script('start-flexric.sh')
        binary_args = Path(str(self.calls) + '.binary').read_text().splitlines()
        self.assertEqual(binary_args[:2], ['-c', str(self.work / 'configs/flexric/flexric.conf')])
        self.run_script('start-xapp.sh', '500')
        binary_args = Path(str(self.calls) + '.binary').read_text().splitlines()
        self.assertEqual(binary_args[1], '500')
        self.assertEqual(binary_args[2:4], ['-c', str(self.work / 'configs/flexric/flexric.conf')])
        self.assertIn('/artifacts/logs/flexric/KPI_Metrics.csv', binary_args[0])

    def test_core_start_stop(self):
        ctx = Path(self.env['CORE_COMPOSE_DIR'])
        ctx.mkdir(parents=True)
        compose = ctx / 'compose.sh'
        compose.write_text('#!/bin/bash\necho "$1" >>"$CALLS.compose"\n')
        compose.chmod(0o755)
        (ctx / 'core_upf_used.txt').write_text('5gdeploy-oai\n5gdeploy-oai\n')
        self.stub('docker', 'sys.exit(0)')
        self.run_script('start-core.sh')
        self.run_script('stop-core.sh')
        self.assertEqual(Path(str(self.calls) + '.compose').read_text().splitlines(), ['up', 'down'])
        (ctx / 'core_upf_used.txt').write_text('5gdeploy-free5gc\n5gdeploy-free5gc\n')
        self.run_script('start-core.sh', success=False)

    def test_namespace_address_mapping_and_rejection(self):
        self.stub('ip', "print('default via 192.0.2.1 dev eth0')")
        self.stub('sudo', 'sys.exit(0)')
        self.run_script('setup-ue-network.sh', '2')
        calls = self.commands()
        self.assertIn(['sudo', 'ip', 'addr', 'add', '10.201.0.9/30', 'dev', 'v-eth2'], calls)
        self.assertIn(['sudo', 'ip', 'netns', 'exec', 'ue2', 'ip', 'addr', 'add', '10.201.0.10/30', 'dev', 'v-ue2'], calls)
        self.calls.unlink()
        for value in ('0', '-1', 'abc', '16384'):
            self.run_script('setup-ue-network.sh', value, success=False)
        self.assertFalse(self.commands())

    def test_runner_dry_run_and_validation(self):
        result = self.run_script('run-experiment.sh', '--dry-run', '--smoke', '--ue', '2')
        self.assertIn(str(self.work / 'artifacts/experiments'), result.stdout)
        self.assertIn('UE=2', result.stdout)
        self.assertFalse((self.work / 'artifacts').exists())
        for args in [('--run-id', '..'), ('--ue', '0'), ('--period-ms', '0'), ('--dl-rate', 'bad')]:
            self.run_script('run-experiment.sh', '--dry-run', *args, success=False)
        self.assertFalse(self.commands())

    def test_core_configuration_pipeline(self):
        deploy = self.work / 'deploy'
        for folder in ('scenario/20230817', 'scenario/common', 'compose', 'virt', 'node_modules/.bin'):
            (deploy / folder).mkdir(parents=True, exist_ok=True)
        for file in ('scenario.ts', 'sonic-dl.ts', 'sonic-ul.ts'):
            (deploy / 'scenario/20230817' / file).write_text('01000000 20230817')
        (deploy / 'scenario/common/phones-vehicles.ts').write_text('plmn: "001-01", tac: "000007"')
        self.env['DEPLOY_SRC'] = str(deploy)
        tsx = deploy / 'node_modules/.bin/tsx'
        tsx.write_text('#!/bin/bash\necho "{}"\n')
        tsx.chmod(0o755)
        self.stub('docker', 'sys.exit(0)')
        self.stub('sudo', 'sys.exit(0)')
        self.stub('corepack', r'''
args = sys.argv[1:]
if '--out' not in ' '.join(args): sys.exit(0)
out = pathlib.Path(next(a.split('=', 1)[1] for a in args if a.startswith('--out=')))
(out / 'cp-cfg').mkdir()
(out / 'up-cfg').mkdir()
(out / 'cp-cfg/config.yaml').write_text('smf:\n  upfs:\n    - config:\n        enable_usage_reporting: false\n')
(out / 'up-cfg/upf1.yaml').write_text('upf:\n  support_features:\n    enable_bpf_datapath: false\n    enable_urr: false\n')
(out / 'compose.yml').write_text(
    'services:\n'
    '  upf1:\n'
    '    image: example/oai-upf:old\n'
    '    cap_add: [NET_ADMIN, BPF, SYS_ADMIN, SYS_RESOURCE]\n')
(out / 'compose.sh').write_text('#!/bin/bash\nexit 0\n')
(out / 'compose.sh').chmod(0o755)
''')
        ctx = Path(self.env['CORE_COMPOSE_DIR'])
        ctx.mkdir(parents=True)
        (ctx / 'old.txt').write_text('preserve me')
        self.run_script('configure-core.sh')
        self.assertEqual(len((deploy / 'sims.tsv').read_text().splitlines()), 11)
        self.assertIn('image=oai-upf-research:local', (ctx / 'oai_upf_profile.env').read_text())
        self.assertIn('enable_urr: true', (ctx / 'up-cfg/upf1.yaml').read_text())
        self.assertEqual((self.work / 'configs/core/get_amf_address.txt').read_text(),
                         '192.168.62.11\n192.168.63.1\n192.168.62.1\n')
        self.assertTrue((self.work / 'configs/core/netdef.json').resolve().is_file())
        backups = list(ctx.parent.glob('core.previous.*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'old.txt').read_text(), 'preserve me')
        command = next(c for c in self.commands() if c[0] == 'corepack')
        self.assertIn('--cp=oai', command)
        self.assertIn('--up=oai', command)
        self.assertIn('--ip-fixed=amf,n2,192.168.62.11', command)

    def test_embedded_agent_preserves_different_xapp(self):
        tree = self.work / 'embedded-flexric'
        (tree / 'src/util').mkdir(parents=True)
        (tree / 'CMakeLists.txt').write_text('')
        header = tree / 'src/util/conf_file.h'
        header.write_text('#define FR_CONF_FILE_LEN 128\n')
        xapp = tree / 'examples/xApp/c/monitor/xapp_kpm_moni_write_to_csv.c'
        xapp.parent.mkdir(parents=True)
        xapp.write_text('/* deliberately different embedded xApp */\n')
        self.run_script('lib/apply-patches.sh', 'flexric-agent', str(tree))
        self.run_script('lib/apply-patches.sh', 'flexric-agent', str(tree))
        self.assertEqual(xapp.read_text(), '/* deliberately different embedded xApp */\n')
        self.assertEqual(header.read_text(), '#define FR_CONF_FILE_LEN 1024\n')
        self.assertFalse((tree / 'examples/xApp/c/metrics_factory.c').exists())

    def test_build_flags(self):
        ran, flex = self.fake_sources()
        for base in (ran / 'openair2/E2AP/flexric', flex):
            agent = base / 'src/agent/e2_agent_api.c'
            agent.parent.mkdir(parents=True)
            agent.write_text('e2ap_server_port = 36421;')
            (base / 'CMakeLists.txt').write_text('')
        (ran / 'oaienv').write_text('true\n')
        build = ran / 'cmake_targets/build_oai'
        build.write_text('#!/usr/bin/env python3\nimport os, sys, json\nwith open(os.environ["CALLS"], "a") as f: f.write(json.dumps(["build_oai", *sys.argv[1:]]) + "\\n")\n')
        build.chmod(0o755)
        (flex / 'flexric.conf').write_text('[XAPP]\nDB_NAME = old\n')
        self.env.update(APPLY_PATCHES='false', CLEAN_INSTALL='true', DEBUG_SYMBOLS='true')
        for command in ('gcc', 'g++', 'cmake', 'make', 'swig', 'ninja'):
            self.stub(command, 'sys.exit(0)')
        self.run_script('build-ran.sh')
        builds = [c for c in self.commands() if c[0] == 'build_oai']
        self.assertEqual(len(builds), 2)
        self.assertIn('--nrUE', builds[0])
        self.assertIn('-C', builds[0])
        self.assertNotIn('-C', builds[1])
        for flag in ('--gNB', '--build-e2', '-DE2AP_VERSION=E2AP_V3', '-DKPM_VERSION=KPM_V3_00', 'telnetsrv', 'SIMU', '-g'):
            self.assertIn(flag, builds[1])
        self.run_script('build-flexric.sh')
        cmake = next(c for c in self.commands() if c[0] == 'cmake')
        for flag in ('-DXAPP_DB=NONE_XAPP', '-DE2AP_VERSION=E2AP_V3', '-DKPM_VERSION=KPM_V3_00', '-DCMAKE_BUILD_TYPE=Debug'):
            self.assertIn(flag, cmake)

    def test_runner_complete_lifecycle_with_mock_stack(self):
        self.config('.oai_upf.enable_usage_reporting = false')
        script_root = self.work / 'runner/scripts'
        script_root.mkdir(parents=True)
        shutil.copy(LEGACY / 'run-experiment.sh', script_root)
        shutil.copy(LEGACY / 'env.sh', script_root)
        self.env['STATE'] = str(self.work / 'stack-started')
        def executable(relative, body):
            path = script_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#!/usr/bin/env bash\nset -e\n' + body + '\n')
            path.chmod(0o755)
        executable('start-core.sh', 'touch "$STATE"')
        executable('start-flexric.sh', 'mkdir -p "$LOG_ROOT/flexric"; echo E2 SETUP-REQUEST >"$LOG_ROOT/flexric/flexric_stdout.txt"')
        executable('start-gnb.sh', 'mkdir -p "$CONFIG_ROOT/gnb" "$CONFIG_ROOT/ue"; echo 127.0.0.1 >"$CONFIG_ROOT/gnb/get_rfsim_server_address.txt"')
        executable('start-ue.sh', 'mkdir -p "$LOG_ROOT/ue"; printf "NR_RRC_CONNECTED\\nReceived PDU Session Establishment Accept, UE IPv4: 10.0.0.2\\n" >"$LOG_ROOT/ue/ue1_stdout.txt"')
        executable('stop-stack.sh', 'echo stopped >"$STATE.stopped"')
        for name in ('traffic-dl.sh', 'traffic-ul.sh'):
            executable(name, 'exit 0')
        for name in ('core-status', 'gnb-status', 'ue-status', 'flexric-status'):
            executable('lib/' + name + '.sh', 'echo RUNNING')
        executable('lib/core-ready.sh', 'echo true')
        xapp = script_root / 'start-xapp.sh'
        xapp.write_text('#!/usr/bin/env python3\nimport os, pathlib, time, signal, sys\nsignal.signal(signal.SIGINT, lambda *_: sys.exit(0))\npathlib.Path(os.environ["OUTPUT_CSV_PATH"]).write_text("timestamp,value\\n1,2\\n")\nwhile True: time.sleep(1)\n')
        xapp.chmod(0o755)
        self.stub('sudo', "args=sys.argv[1:]; args=[a for a in args if a != '-n']; sys.exit(0) if args == ['-v'] else os.execvp(args[0], args)")
        self.stub('pgrep', "sys.exit(1) if not pathlib.Path(os.environ['STATE']).exists() else print('12345')")
        self.stub('docker', "print('amf\\nsmf\\nupf1') if sys.argv[1]=='ps' and pathlib.Path(os.environ['STATE']).exists() else print('PFCP association') if sys.argv[1]=='logs' else None")
        for command in ('systemctl', 'capinfos', 'tshark', 'rsync', 'ip', 'iperf'):
            self.stub(command, 'sys.exit(0)')
        self.stub('dumpcap', "signal.signal(signal.SIGINT, lambda *_: sys.exit(0))\nsys.stdout.write('mock pcap'); sys.stdout.flush()\nwhile True: time.sleep(0.1)")
        result = self.run_script('run-experiment.sh', '--run-id', 'lifecycle', '--no-dl', '--no-ul',
                                '--baseline', '0', '--between', '0', '--post-wait', '0',
                                '--capture-interface', 'lo', script_root=script_root)
        result_file = self.work / 'artifacts/experiments/lifecycle/metadata/result.env'
        self.assertIn('status=complete', result_file.read_text(), result.stdout)
        self.assertTrue(Path(self.env['STATE'] + '.stopped').exists())
        self.assertTrue((self.work / 'artifacts/experiments/lifecycle/kpm/KPI_Metrics.csv').exists())
        self.assertTrue((self.work / 'artifacts/experiments/lifecycle/capture/pfcp_messages.csv').exists())

    def test_traffic_directions_use_latest_pdu_ip(self):
        cfg = self.work / 'configs/ue'
        cfg.mkdir()
        (cfg / 'ue1.conf').write_text('')
        logs = self.work / 'artifacts/logs/ue'
        logs.mkdir(parents=True)
        (logs / 'ue1_stdout.txt').write_text('Received PDU Session Establishment Accept, UE IPv4: 10.0.0.2\nReceived PDU Session Establishment Accept, UE IPv4: 10.0.0.3\n')
        self.stub('sudo', 'os.execvp(sys.argv[1], sys.argv[1:])')
        self.stub('docker', "print('dn_internet') if sys.argv[1] == 'ps' else None")
        self.stub('ip', r'''
args=sys.argv[1:]
if args == ['netns', 'list']: print('ue1')
elif args[:3] == ['netns', 'exec', 'ue1']:
    if args[3:] == ['ip', 'route']: print('10.0.0.0/24 dev oaitun_ue1')
    else: os.execvp(args[3], args[3:])
''')
        self.stub('iperf', "if '-s' in sys.argv:\n    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n    while True: time.sleep(0.1)")
        self.run_script('traffic-dl.sh', '1', '2M', '1', '5101')
        self.run_script('traffic-ul.sh', '1', '3M', '1', '5102')
        commands = self.commands()
        dl = next(c for c in commands if c[:5] == ['docker', 'exec', 'dn_internet', 'iperf', '-c'])
        self.assertEqual(dl[5], '10.0.0.3')
        self.assertIn('2M', dl)
        ul = next(c for c in commands if c[:2] == ['iperf', '-c'])
        self.assertEqual(ul[2], '10.0.0.1')
        self.assertIn('3M', ul)
        self.assertIn('5102', ul)
        self.assertTrue((logs / 'iperf_dl_server_ue1.log').exists())
        self.assertTrue((logs / 'iperf_ul_server_ue1.log').exists())

    def test_stop_process_matches_exact_configuration(self):
        # Two harmless processes with the radio process name; only the chosen config may stop.
        (self.bin / 'pgrep').unlink()
        self.stub('sudo', 'os.execvp(sys.argv[1], sys.argv[1:])')
        code = 'import ctypes,time; ctypes.CDLL(None).prctl(15,b"nr-uesoftmodem",0,0,0); time.sleep(30)'
        processes = []
        for number in (1, 2):
            process = subprocess.Popen(['python3', '-c', code, str(self.work / f'configs/ue/ue{number}.conf')])
            processes.append(process)
            self.addCleanup(lambda p=process: p.kill() if p.poll() is None else None)
        import time
        time.sleep(0.15)
        self.run_script('lib/stop-process.sh', 'ue', '1')
        self.assertIsNotNone(processes[0].poll())
        self.assertIsNone(processes[1].poll())
        processes[1].terminate()
        for process in processes:
            process.wait(timeout=3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
