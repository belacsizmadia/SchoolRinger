import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LinuxInstallerTests(unittest.TestCase):
    def test_shell_scripts_have_valid_syntax(self):
        subprocess.run(
            [
                "bash",
                "-n",
                str(ROOT / "install.sh"),
                str(ROOT / "scripts" / "run-service.sh"),
            ],
            check=True,
        )

    def test_installer_help_does_not_require_root(self):
        result = subprocess.run(
            [str(ROOT / "install.sh"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("SchoolRinger Linux telepítő", result.stdout)

    def test_service_runner_passes_network_and_data_arguments(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            data_dir = root / "data"
            python = app_dir / ".venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
            python.chmod(0o755)
            environment = {
                **os.environ,
                "SCHOOLRINGER_APP_DIR": str(app_dir),
                "SCHOOLRINGER_DATA_DIR": str(data_dir),
                "SCHOOLRINGER_WEB_HOST": "0.0.0.0",
                "SCHOOLRINGER_WEB_PORT": "5001",
                "SCHOOLRINGER_MEDIA_PORT": "8081",
                "SCHOOLRINGER_HOST_IP": "192.168.1.20",
            }

            result = subprocess.run(
                [str(ROOT / "scripts" / "run-service.sh")],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )

            arguments = result.stdout.splitlines()
            self.assertEqual(arguments[0], str(app_dir / "scheduler_app.py"))
            self.assertIn(str(data_dir / "media"), arguments)
            self.assertIn(str(data_dir / "data" / "schedules.json"), arguments)
            self.assertIn("192.168.1.20", arguments)
            self.assertIn("8081", arguments)


if __name__ == "__main__":
    unittest.main()
