# Repository Analysis — netflixWatcher

## What does this project do?

netflixWatcher is a Python automation daemon that monitors a Gmail inbox every 5 seconds for Netflix Household update confirmation emails. When a relevant email arrives (subject: "Important: How to update your Netflix Household"), it parses the body to extract the confirmation link, then drives a headless Chrome browser via Selenium to load the page, log in to Netflix if required, and click the "Set Primary Location" button — fully automating the Netflix Household confirmation workflow.

## Primary Success Metric

Since the application cannot be run without real credentials and a running Chrome/Selenium environment, and no test suite currently exists, the primary metric is **code quality as measured by pylint score** on the two source files. A pylint run on `app/application.py` and `app/logger.py` produces a score in [0.0, 10.0]; we normalize it to [0.0, 1.0] as `score = pylint_score / 10.0`. Higher is better. This captures correctness of style, dead code, missing doc-strings, complexity, unused imports, etc.

A secondary metric is **type-annotation coverage** on the same files, measured by the fraction of function signatures that have at least one type annotation.

## File Map

```
app/application.py     — Main daemon: email polling, Selenium automation, Netflix login
app/logger.py          — Custom JSON formatter and logger setup
app/requirements.txt   — Python runtime dependencies (selenium, python-dotenv)
dockerfile             — Docker image build definition
docker-compose.yml     — Docker Compose service definitions (app + daily scheduler)
Setup/netflixwatcherstart.sh    — Shell helper to start the daemon on a Raspberry Pi
Setup/netflixwatcher_restart.sh — Shell helper to restart the daemon on a Raspberry Pi
readme.md              — User-facing setup and usage documentation
.autoimprove/          — autoimprove evaluation harness (DO NOT MODIFY)
```

## Tech Stack

- **Language**: Python 3
- **Framework**: None (pure stdlib + third-party)
- **Package manager**: pip (no pyproject.toml / setup.py)
- **Test runner**: N/A (no tests exist)
- **Dependencies**: selenium, python-dotenv, imaplib (stdlib), email (stdlib)

## How to Build

N/A — pure Python, no build step required.

## How to Test

No test suite exists currently. Tests should be added.

## How to Run

```bash
cd app && python application.py
```
(Requires `.env` file with credentials and a running Chromium + chromedriver.)

## How to Evaluate the Primary Metric

```bash
uv run .autoimprove/eval_harness.py
```

The primary evaluator runs pylint on `app/application.py` and `app/logger.py` and normalizes the 0–10 pylint score to [0.0, 1.0].

## Editable Files

- `app/application.py` — Core logic: email polling, Selenium, login handling. May be improved for code quality, error handling, type annotations, and correctness.
- `app/logger.py` — Logging utilities. May be improved for style, annotations, and completeness.
- `readme.md` — Documentation. May be improved for accuracy and completeness.

## Fixed Files (DO NOT MODIFY)

- `.autoimprove/` — The entire autoimprove directory: eval harness, evaluators, configs.
- `dockerfile` / `docker-compose.yml` — Infrastructure definitions.
- `Setup/` — Deployment scripts.
- `app/requirements.txt` — Adding new packages here is fine; removing existing ones is not.

## Current Quality Issues

1. **No type annotations** on most function parameters and return types.
2. **Bare `except` clause** in `fetch_last_unseen_email` (`finally` block silently swallows errors).
3. **`extract_links` return type** is always a list but never explicitly annotated.
4. **Unused `EMAIL_IMAP` variable** — loaded from env but never used (hardcoded `'imap.gmail.com'`).
5. **`login_to_netflix` returns `True` in both success and "already logged in" paths** making the return value meaningless; the caller never actually checks it.
6. **`open_link_with_selenium` has no explicit return** on the happy path (returns `None` implicitly).
7. **Repeated `driver.find_element` call** for `use_password_field` / `use_password_button` (same element found twice).
8. **High cyclomatic complexity** in `open_link_with_selenium` — nested try/except/loops.
9. **`time.sleep` blocking calls** scattered through the code instead of configurable constants.
10. **Missing module-level docstring** on `application.py`.
