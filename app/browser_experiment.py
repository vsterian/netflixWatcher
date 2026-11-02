"""Durable, secret-free results for the seven-day browser comparison."""
import argparse
import json
import math
import sqlite3
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ENGINES = ("selenium", "playwright")
EXCLUDED = {"already_success", "mail_error", "interrupted"}


class Experiment:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        self.db = sqlite3.connect(self.path)
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS trial (started REAL NOT NULL)")
            if not self.db.execute("SELECT started FROM trial").fetchone():
                self.db.execute("INSERT INTO trial VALUES (?)", (time.time(),))
            self.db.execute("""CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, engine TEXT NOT NULL, started REAL NOT NULL,
                finished REAL, outcome TEXT, duration REAL, navigation REAL, warm INTEGER
            )""")
        self.started = self.db.execute("SELECT started FROM trial").fetchone()[0]
        self.ends = self.started + 7 * 86400

    def begin(self, engine):
        if engine not in ENGINES:
            raise ValueError("Unknown browser engine")
        run_id = uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO runs(run_id, engine, started) VALUES (?, ?, ?)",
                            (run_id, engine, time.time()))
        return run_id

    def finish(self, run_id, outcome, duration, navigation, warm):
        allowed = EXCLUDED | {"success", "timeout", "invalid_link", "login_failed",
                              "empty_body", "link_not_found", "browser_error"}
        if outcome not in allowed:
            raise ValueError("Unknown browser outcome")
        with self.db:
            self.db.execute("""UPDATE runs SET finished=?, outcome=?, duration=?, navigation=?, warm=?
                WHERE run_id=? AND finished IS NULL""",
                (time.time(), outcome, duration, navigation, int(warm), run_id))

    def recover(self):
        """Only the watcher startup calls this; readers never interrupt live runs."""
        with self.db:
            self.db.execute("UPDATE runs SET finished=?, outcome='interrupted' WHERE finished IS NULL",
                            (time.time(),))

    def report(self):
        rows = self.db.execute("""SELECT engine, outcome, duration, navigation, warm FROM runs
            WHERE started >= ? AND started < ? ORDER BY started""", (self.started, self.ends)).fetchall()
        report = {"started_utc": datetime.fromtimestamp(self.started, timezone.utc).isoformat(),
                  "review_utc": datetime.fromtimestamp(self.ends, timezone.utc).isoformat(),
                  "review_due": time.time() >= self.ends, "automatic_switch": False, "engines": {}}
        for engine in ENGINES:
            runs = [row for row in rows if row[0] == engine]
            outcomes = Counter(row[1] or "pending" for row in runs)
            successful = [row for row in runs if row[1] == "success"]
            durations = sorted(row[2] for row in successful)
            completed = sum(n for outcome, n in outcomes.items() if outcome not in EXCLUDED | {"pending"})
            report["engines"][engine] = {
                "assigned": len(runs), "completed": completed, "successes": len(successful),
                "failures": completed - len(successful), "excluded": sum(outcomes[x] for x in EXCLUDED),
                "pending": outcomes["pending"], "outcomes": dict(outcomes),
                "success_rate": len(successful) / completed if completed else None,
                "median_success_seconds": statistics.median(durations) if durations else None,
                "p95_success_seconds": durations[math.ceil(len(durations) * .95) - 1] if durations else None,
                "warm_successes": sum(row[4] == 1 for row in successful),
                "cold_successes": sum(row[4] == 0 for row in successful),
                "warm_median_seconds": statistics.median([row[2] for row in successful if row[4] == 1])
                    if any(row[4] == 1 for row in successful) else None,
                "cold_median_seconds": statistics.median([row[2] for row in successful if row[4] == 0])
                    if any(row[4] == 0 for row in successful) else None,
            }
        return report

    def publish(self, metrics):
        values = {"netflix_ab_started_timestamp_seconds": self.started,
                  "netflix_ab_review_timestamp_seconds": self.ends}
        for engine, result in self.report()["engines"].items():
            for field in ("assigned", "completed", "successes", "failures", "excluded", "pending",
                          "success_rate", "median_success_seconds", "p95_success_seconds",
                          "warm_successes", "cold_successes", "warm_median_seconds", "cold_median_seconds"):
                values[f"netflix_ab_{engine}_{field}"] = result[field] or 0
        metrics.update(**values)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("Experiment database does not exist")
    print(json.dumps(Experiment(args.database).report(), indent=2))
