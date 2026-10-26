import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from metrics import Metrics


def values(path):
    return {
        line.split()[0]: float(line.split()[1])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


class MetricsTest(unittest.TestCase):
    def test_mutators_publish_and_poll_failure_updates_counters(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "netflix.prom"
            metrics = Metrics(path)
            metrics.publish()
            metrics.set("service_up", 1)
            metrics.increment("netflix_matching_emails_total", 2)
            metrics.update(custom_gauge=3)
            metrics.poll_failure(0.75)

            published = values(path)
            self.assertEqual(published['service_up{product="netflix-watcher"}'], 1)
            self.assertEqual(published["netflix_matching_emails_total"], 2)
            self.assertEqual(published["custom_gauge"], 3)
            self.assertEqual(published["consecutive_failures{product=\"netflix-watcher\"}"], 1)
            self.assertEqual(published["operations_failure_total{product=\"netflix-watcher\"}"], 1)
            self.assertEqual(published["netflix_imap_poll_success"], 0)

    def test_empty_poll_publication_is_throttled_but_pending_poll_is_not(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "netflix.prom"
            metrics = Metrics(path)
            with patch("metrics.time.time", side_effect=[10, 11, 12]), patch(
                "metrics.time.monotonic", side_effect=[100, 101, 102]
            ):
                metrics.poll_success(0, 0.1)
                first = path.read_text(encoding="utf-8")
                metrics.poll_success(0, 0.2)
                self.assertEqual(path.read_text(encoding="utf-8"), first)
                metrics.poll_success(1, 0.3)
            published = values(path)
            self.assertEqual(published["netflix_imap_poll_success_total"], 3)
            self.assertEqual(published["netflix_matching_emails_pending"], 1)

    def test_workflow_success_and_failure(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "netflix.prom"
            metrics = Metrics(path)
            metrics.workflow_finished(True, 1.5)
            metrics.workflow_finished(False, 2.5)
            published = values(path)
            self.assertEqual(published["netflix_workflow_success_total"], 1)
            self.assertEqual(published["netflix_workflow_failure_total"], 1)
            self.assertEqual(published["netflix_workflow_last_success"], 0)
            self.assertEqual(published["netflix_workflow_last_duration_seconds"], 2.5)
            self.assertEqual(published["netflix_workflow_stage"], 6)

    def test_idle_poll_is_success_and_contains_no_sensitive_labels(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "netflix.prom"
            metrics = Metrics(path)
            metrics.update(service_up=1)
            metrics.poll_success(0, 0.25)

            published = values(path)
            self.assertEqual(published["netflix_imap_poll_success"], 1)
            self.assertEqual(published["netflix_matching_emails_pending"], 0)
            self.assertIn('service_up{product="netflix-watcher"} 1', path.read_text(encoding="utf-8"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            content = path.read_text(encoding="utf-8").lower()
            for forbidden in ("email_address", "subject", "url", "password", "token"):
                self.assertNotIn(forbidden, content)

    def test_concurrent_updates_keep_valid_textfile(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "netflix.prom"
            metrics = Metrics(path)
            threads = [
                threading.Thread(target=metrics.increment, args=("netflix_imap_poll_success_total",))
                for _ in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(values(path)["netflix_imap_poll_success_total"], 8)

    def test_metrics_file_environment_override(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "custom.prom"
            with patch.dict("os.environ", {"METRICS_FILE": str(path)}):
                Metrics().set("service_up", 1)
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
