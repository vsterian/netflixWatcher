import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from metrics import Metrics


def values(path):
    return {
        line.split()[0]: float(line.split()[1])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }


class MetricsTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
