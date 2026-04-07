# netflixWatcher — Improvement Program

## 1. Setup

At the start of every improvement session:

1. Create branch: `git checkout -b autoimprove/$(date +%b%d | tr '[:upper:]' '[:lower:]')`
2. Read these files:
   - `app/application.py` — Main daemon (email polling, Selenium, Netflix login)
   - `app/logger.py` — Custom JSON logger
   - `.autoimprove/analysis.md` — Repo analysis and known issues
   - `.autoimprove/baselines/baseline.json` — Baseline evaluation scores
3. Verify the baseline: `uv run .autoimprove/eval_harness.py | grep composite_score`  
   Expected: `"composite_score": 0.6775`
4. Confirm and go.

---

## 2. Scope

### What you CAN modify
| File | What it contains | What is fair game |
|---|---|---|
| `app/application.py` | Email polling, Selenium automation, Netflix login | Fix pylint violations: trailing whitespace, long lines, bare except, broad exceptions, nested blocks, inconsistent returns, too-many-branches/statements, redundant else-after-return/continue. Add type annotations. |
| `app/logger.py` | Custom JSON formatter and logger factory | Fix trailing whitespace, missing final newline. Add type annotations. |

### What you CANNOT modify
| Path | Reason |
|---|---|
| `.autoimprove/` | The entire evaluation harness — modifying it invalidates all scores |
| `dockerfile` | Infrastructure |
| `docker-compose.yml` | Infrastructure |
| `Setup/` | Deployment scripts |

---

## 3. Evaluation

### Run evaluation
```bash
uv run .autoimprove/eval_harness.py
```
Completes in ~3 seconds (well within the 300-second budget).

### Output format (baseline)
```json
{
  "composite_score": 0.6775,
  "elapsed_seconds": 2.1,
  "evaluators": [
    {
      "name": "code_quality",
      "score": 0.6775,
      "details": {
        "pylint_scores": {
          "app/application.py": 5.4,
          "app/logger.py": 8.15
        },
        "average_pylint_score": 6.775,
        "normalized_score": 0.6775
      },
      "weight": 5.0
    }
  ]
}
```

### Evaluator details
| Evaluator | Measures | Weight | Baseline score |
|---|---|---|---|
| `code_quality` | Pylint score on both source files, normalized to [0,1] | 5.0 (100%) | **0.6775** |

**Primary metric**: `code_quality` — the only evaluator, so it IS the composite score.  
- `app/application.py` baseline: **5.40/10**  
- `app/logger.py` baseline: **8.15/10**

### Extract composite score quickly
```bash
uv run .autoimprove/eval_harness.py | python3 -c "import sys,json; print(json.load(sys.stdin)['composite_score'])"
```

---

## 4. The Experiment Loop

```
LOOP FOREVER:
1. Pick ONE specific pylint violation (or related group) to fix
2. Edit app/application.py or app/logger.py
3. git add -p && git commit -m "experiment: <description>"
4. Run: uv run .autoimprove/eval_harness.py
5. Read: cat .autoimprove/run.log
6. If crashed: fix or abandon
7. Log to .autoimprove/results.tsv
8. If composite_score improved: keep commit, update baseline
9. If not improved: git reset --hard HEAD~1
10. GOTO 1

Time budget: 300 seconds per evaluation run (actual runs take ~3 seconds).
```

### Example pylint violations in application.py (ordered by impact on score)

1. **E0401 import-error** (10 violations) — pylint can't import selenium/dotenv without the venv.  
   Fix: add a `# pylint: disable=import-error` block at the top of the file — these are runtime dependencies not available in the lint environment.

2. **C0303 trailing-whitespace** (15+ violations) — trailing spaces throughout.  
   Fix: strip trailing whitespace from all lines.

3. **C0301 line-too-long** (9 violations) — lines exceeding 100 chars.  
   Fix: wrap long lines.

4. **R1710 inconsistent-return-statements** — `open_link_with_selenium` returns a tuple on error but `None` on success.  
   Fix: always return a tuple or None consistently.

5. **R0912 too-many-branches** / **R0915 too-many-statements** — `open_link_with_selenium` and `fetch_last_unseen_email` are too complex.  
   Fix: extract helper functions.

6. **W0702 bare-except** — `except:` without exception type in `finally` block.  
   Fix: `except Exception:` or `except (imaplib.IMAP4.error, OSError):`.

7. **W0718 broad-exception-caught** — catching `Exception` instead of specific types.  
   Fix: narrow the exception types where possible.

8. **R1702 too-many-nested-blocks** — deeply nested try/for/try structure.  
   Fix: extract inner logic into helper function.

9. **R1705 no-else-return** and **R1724 no-else-continue** — unnecessary else after return/continue.  
   Fix: de-indent the else bodies.

### Example pylint violations in logger.py (low-hanging fruit)

1. **C0303 trailing-whitespace** (4 violations)
2. **C0304 missing-final-newline** (1 violation)

---

## 5. Logging

Format: tab-separated (NOT comma-separated).  
File: `.autoimprove/results.tsv`

Columns: `commit`, `composite_score`, `status`, `description`

```
baseline	0.6775	keep	baseline — initial state
abc1234	0.6900	keep	experiment: disable import-error warnings, fix trailing whitespace in logger.py
def5678	0.7050	keep	experiment: fix trailing whitespace in application.py
ghi9012	0.7200	keep	experiment: fix no-else-return, no-else-continue, bare-except
```

---

## 6. Strategy

**Start with the easiest, highest-impact fixes first:**

1. **logger.py** (quick wins): 4 trailing-whitespace violations + 1 missing-final-newline. These are trivial to fix and will push `logger.py` from 8.15 → ~10.0, moving the composite score meaningfully.

2. **application.py import errors**: Add `# pylint: disable=import-error` to suppress the 10 E0401 errors from selenium/dotenv which can't be installed in the lint environment. This alone should push the score substantially.

3. **application.py trailing whitespace**: Strip all trailing spaces. Quick to do, lots of violations.

4. **application.py long lines**: Wrap lines exceeding 100 characters.

5. **application.py structural fixes**: Extract helpers to reduce too-many-branches and too-many-statements. Fix inconsistent-return-statements. Fix no-else-return/continue. Fix bare-except.

**Simplicity criterion**: "Removing code and getting equal or better results is a great outcome." If a comment can be removed to shorten a line, do it.

**Crash recovery**: If pylint exits non-zero but still outputs a score, the evaluator handles it. If the evaluator returns 0.0, check `.autoimprove/run.log` for the error.

---

## 7. NEVER STOP

```
Once the loop begins, do NOT pause to ask the human if you should continue.
Do NOT ask "should I keep going?" or "is this a good stopping point?".
The human might be asleep. You are autonomous. If you run out of ideas,
think harder — re-read the source code, try combining previous experiments,
try more radical approaches. The loop runs until the human interrupts you.
```
