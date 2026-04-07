#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pylint>=3.0"]
# ///
"""Primary evaluator: measures pylint code quality score on the application source files.

Runs pylint on app/application.py and app/logger.py, averages the two scores,
and normalises the result from pylint's 0–10 range to [0.0, 1.0].
Higher is better.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
FILES = ["app/application.py", "app/logger.py"]


def run_pylint(filepath: str) -> float:
    """Run pylint on a single file and return its score (0.0–10.0)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pylint",
            filepath,
            "--score=yes",
            "--output-format=text",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    # pylint exits with non-zero even when it produces a score (warnings found)
    output = result.stdout + result.stderr
    print(f"pylint {filepath}:", file=sys.stderr)
    # Show the rating line on stderr for visibility
    for line in output.splitlines():
        if "rated at" in line or "Your code" in line:
            print(f"  {line.strip()}", file=sys.stderr)

    match = re.search(r"Your code has been rated at\s+([-\d.]+)/10", output)
    if match:
        raw = float(match.group(1))
        # Clamp to [0, 10] – pylint can produce negative scores
        return max(0.0, min(10.0, raw))

    print(f"  WARNING: could not parse pylint score for {filepath}", file=sys.stderr)
    return 0.0


def main() -> None:
    scores = []
    for rel_path in FILES:
        abs_path = REPO / rel_path
        if not abs_path.exists():
            print(f"  SKIP: {rel_path} not found", file=sys.stderr)
            continue
        score = run_pylint(rel_path)
        scores.append(score)
        print(f"  {rel_path}: {score:.2f}/10  → {score / 10:.4f}", file=sys.stderr)

    if not scores:
        print(json.dumps({"name": "code_quality", "score": 0.0,
                          "details": {"error": "no source files found"}}))
        return

    avg_raw = sum(scores) / len(scores)
    normalized = round(avg_raw / 10.0, 6)

    print(json.dumps({
        "name": "code_quality",
        "score": normalized,
        "details": {
            "pylint_scores": {FILES[i]: scores[i] for i in range(len(scores))},
            "average_pylint_score": round(avg_raw, 4),
            "normalized_score": normalized,
        },
    }))


if __name__ == "__main__":
    main()
