import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerTest(unittest.TestCase):
    def test_hook_runtime_bootstraps_venv_without_uv(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            fake_python = bin_dir / "python3"
            call_log = temp / "python-calls.txt"
            deps_marker = temp / "deps-installed"
            fake_python.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                'printf "%s|%s\\n" "$0" "$*" >> "$FAKE_PYTHON_CALL_LOG"\n'
                'if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then\n'
                '  mkdir -p "$3/bin"\n'
                '  cp "$0" "$3/bin/python3"\n'
                '  chmod +x "$3/bin/python3"\n'
                "  exit 0\n"
                "fi\n"
                'if [ "${1:-}" = "-" ]; then\n'
                '  [ -f "$FAKE_DEPS_MARKER" ]\n'
                "  exit\n"
                "fi\n"
                'if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then\n'
                '  touch "$FAKE_DEPS_MARKER"\n'
                "  exit 0\n"
                "fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            home = temp / "home"
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
                "CLAUDE_PLUGIN_ROOT": str(ROOT),
                "FAKE_PYTHON_CALL_LOG": str(call_log),
                "FAKE_DEPS_MARKER": str(deps_marker),
            }

            subprocess.run(
                ["/bin/sh", str(ROOT / "hooks" / "run_hook.sh")],
                cwd=ROOT,
                env=env,
                input="{}\n",
                check=True,
                capture_output=True,
                text=True,
            )

            runtime_python = home / ".claude" / "state" / "claude-otel-plugin-runtime" / "venv" / "bin" / "python3"
            self.assertTrue(runtime_python.exists())
            self.assertFalse((runtime_python.parents[2] / "bootstrap.lock").exists())
            calls = call_log.read_text(encoding="utf-8")
            self.assertIn("-m venv", calls)
            self.assertIn("-m pip install", calls)
            self.assertIn(str(ROOT / "hooks" / "claude_otel_hook.py"), calls)

    def test_shell_installer_persists_temporary_marketplace_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            source = temp / "claude-otel-plugin-package-123"
            (source / ".claude-plugin").mkdir(parents=True)
            (source / ".claude-plugin" / "marketplace.json").write_text(
                '{"name":"claude-otel-plugin","plugins":[{"name":"claude-otel-plugin","source":"./"}]}\n',
                encoding="utf-8",
            )
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            call_log = temp / "claude-calls.txt"
            fake_claude = bin_dir / "claude"
            fake_claude.write_text(
                "#!/bin/sh\n"
                'printf \'%s\\n\' "$*" >> "$FAKE_CLAUDE_CALL_LOG"\n'
                'if [ "$*" = "plugin list --json" ]; then printf \'[]\\n\'; fi\n'
                "exit 0\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(temp / "home"),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "FAKE_CLAUDE_CALL_LOG": str(call_log),
            }

            subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "install.sh"),
                    str(source),
                    "--no-config",
                ],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            persisted = temp / "home" / ".claude" / "marketplaces" / "claude-otel-plugin-release"
            self.assertTrue((persisted / ".claude-plugin" / "marketplace.json").exists())
            calls = call_log.read_text(encoding="utf-8")
            self.assertIn(f"plugin marketplace add {persisted.resolve()}", calls)

    def test_shell_installer_allows_python3_without_uv(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            call_log = temp / "claude-calls.txt"
            fake_claude = bin_dir / "claude"
            fake_claude.write_text(
                "#!/bin/sh\n"
                'printf \'%s\\n\' "$*" >> "$FAKE_CLAUDE_CALL_LOG"\n'
                'if [ "$*" = "plugin list --json" ]; then printf \'[]\\n\'; fi\n'
                "exit 0\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)
            config_file = temp / "home" / ".claude" / "gtrace.json"
            env = {
                **os.environ,
                "HOME": str(temp / "home"),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "FAKE_CLAUDE_CALL_LOG": str(call_log),
            }

            subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "install.sh"),
                    str(ROOT),
                    "--endpoint",
                    "http://localhost:4318",
                    "--config-file",
                    str(config_file),
                ],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            config = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(config["endpoint"], "http://localhost:4318")
            calls = call_log.read_text(encoding="utf-8")
            self.assertIn("plugin install --scope user", calls)

    def test_shell_installer_writes_explicit_disabled_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            call_log = temp / "claude-calls.txt"
            fake_claude = bin_dir / "claude"
            fake_claude.write_text(
                "#!/bin/sh\n"
                'printf \'%s\\n\' "$*" >> "$FAKE_CLAUDE_CALL_LOG"\n'
                'if [ "$*" = "plugin list --json" ]; then printf \'[]\\n\'; fi\n'
                "exit 0\n",
                encoding="utf-8",
            )
            fake_claude.chmod(0o755)
            fake_uv = bin_dir / "uv"
            fake_uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_uv.chmod(0o755)
            config_file = temp / "home" / ".claude" / "gtrace.json"
            env = {
                **os.environ,
                "HOME": str(temp / "home"),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "FAKE_CLAUDE_CALL_LOG": str(call_log),
            }

            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "install.sh"),
                    str(ROOT),
                    "--enabled",
                    "false",
                    "--config-file",
                    str(config_file),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )

            self.assertFalse(json.loads(config_file.read_text(encoding="utf-8"))["enabled"])
            calls = call_log.read_text(encoding="utf-8")
            self.assertIn("--config CLAUDE_OTEL_ENABLED=false", calls)

    def test_shell_installer_preserves_existing_disabled_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            for name in ("claude", "uv"):
                executable = bin_dir / name
                executable.write_text(
                    "#!/bin/sh\n"
                    'if [ "$*" = "plugin list --json" ]; then printf \'[]\\n\'; fi\n'
                    "exit 0\n",
                    encoding="utf-8",
                )
                executable.chmod(0o755)
            config_file = temp / "gtrace.json"
            config_file.write_text('{"enabled": false}\n', encoding="utf-8")
            env = {
                **os.environ,
                "HOME": str(temp / "home"),
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            }

            subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "install.sh"),
                    str(ROOT),
                    "--endpoint",
                    "http://localhost:4318",
                    "--config-file",
                    str(config_file),
                ],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertFalse(json.loads(config_file.read_text(encoding="utf-8"))["enabled"])


if __name__ == "__main__":
    unittest.main()
