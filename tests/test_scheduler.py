import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


SCHEDULER = Path(__file__).resolve().parents[1] / "Setup" / "netflixwatcher_scheduler.sh"


class SchedulerTest(unittest.TestCase):
    def run_function(self, metrics_file, function):
        environment = os.environ.copy()
        environment.update(
            METRICS_FILE=str(metrics_file),
            NETFLIX_SCHEDULER_TEST_MODE="1",
            NETFLIX_SCHEDULER_SCRIPT=str(SCHEDULER),
        )
        return subprocess.run(
            ["sh", "-c", '. "$NETFLIX_SCHEDULER_SCRIPT"; ' + function],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_write_metrics_publishes_all_scheduler_metrics_atomically(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scheduler.prom"
            self.run_function(path, "write_metrics")
            content = path.read_text(encoding="utf-8")
            self.assertIn("netflix_scheduler_service_up 1", content)
            self.assertIn("netflix_scheduler_restart_success_total 0", content)
            self.assertIn("netflix_scheduler_restart_failure_total 0", content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertFalse(list(path.parent.glob("*.tmp.*")))

    def test_shutdown_publishes_down_state_and_heartbeat(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scheduler.prom"
            self.run_function(path, "shutdown")
            content = path.read_text(encoding="utf-8")
            self.assertIn("netflix_scheduler_service_up 0", content)
            heartbeat = next(
                line for line in content.splitlines()
                if line.startswith("netflix_scheduler_last_heartbeat_timestamp_seconds ")
            )
            self.assertGreater(int(heartbeat.rsplit(" ", 1)[1]), 0)


if __name__ == "__main__":
    unittest.main()
