import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerTest(unittest.TestCase):
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

            subprocess.run(
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
                check=True,
                capture_output=True,
                text=True,
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
