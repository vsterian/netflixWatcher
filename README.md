

### Private Raspberry Pi deployment

GitHub deployments use Tailscale OIDC on `main`, an ephemeral `tag:pi-ci` runner,
and ordinary key-authenticated SSH to `100.109.96.69:22`. The Pi host key is pinned;
public SSH and disabled host-key verification are not used. Configure repository
variables `TS_OIDC_CLIENT_ID` and `TS_AUDIENCE` for a Tailscale federated identity
restricted to this repository's main branch and this deployment workflow.
Grant `tag:pi-ci` only TCP 22 on the Pi. Retain the existing deployment SSH key and
user/path secrets. Tailscale authentication does not replace SSH authentication.

The Tailscale action logs out its ephemeral runner in its automatic post-job
cleanup, including failed deployments. Tailscale then removes the machine; no
permanent runner enrollment is retained. Abrupt runner loss can delay automatic
removal until the ephemeral node expires.

Deployments share a Pi-side `flock` across repositories to prevent concurrent
Docker builds exhausting the Pi. Jobs wait up to 30 minutes for the lock.

### Browser runtime

Playwright runs its matching bundled Chromium in headless mode. Install
`app/requirements.txt`, then run `python -m playwright install --with-deps --no-shell chromium`
for local execution and real-browser tests. Docker installs both automatically.
One in-memory browser/context/page is reused; cookies are not exported to disk.
Password login, authenticated Household controls and terminal pages are supported;
email verification challenges before or after password submission stop automation.
Verification codes are never extracted or entered. Confirmation clicks once.

Browser health uses `netflix_browser_*` metrics. Historical `netflix_selenium_*`
series remain in InfluxDB; update consumers to the new browser metric names.


### Browser run tracing

Every workflow emits structured `Netflix browser trace` events with a random
`run_id`, stage, elapsed seconds and terminal outcome. Events cover browser
readiness, navigation, login, click start/completion, XHR/fetch response status,
HTTP errors, failed requests and JavaScript errors. Network events include method,
same-origin flag and allowlisted Chromium failure codes, without endpoint URLs. Timeout diagnostics include
DOM readiness, Household button presence/disabled state, React click-handler
presence and bounded success/error-heading flags. A React-handler flag is a
hint, not proof of complete hydration; transport errors can include unrelated
analytics requests. Diagnostics do not change waits, retry clicks or solve a
historical timeout without new evidence.

Production also writes these events to `/metrics/netflix-browser-traces.jsonl`,
next to the configured metrics file. The existing persistent host mount retains
traces across container replacement. Rotation keeps the active file plus three
backups, each limited to about 1 MiB; files are mode 0600. Ordinary logs without
`run_id` are excluded. Trace storage failure leaves console tracing available.
No passwords, email text/addresses, URLs, headers, cookies, bodies, screenshots,
DOM snapshots or raw exception messages are recorded. Native Playwright trace
archives are not enabled because they can retain authentication material.

Find recent outcomes on the Pi:

```sh
sudo jq -c 'select(.event == "finished")' /var/lib/rpi-observability/apps/netflix-watcher/netflix-browser-traces.jsonl
```

Inspect a run by replacing `RUN_ID` (include rotated files for older runs):

```sh
sudo jq -c 'select(.run_id == "RUN_ID")' /var/lib/rpi-observability/apps/netflix-watcher/netflix-browser-traces.jsonl*
```

A timeout after `click_completed` is a result/readiness problem, not a proven
failed click. Compare pre-click handler state, terminal-page flags and network
events before changing readiness logic or confirmation timeouts. Empty/missing
link failures also have run IDs. Successful latency alone is not reliability.


### Seven-day Selenium / Playwright comparison

Each matching email with a plain-text body receives one independent 50/50
random engine assignment. Assignment is committed before marking the message
seen; failed assignment storage leaves mail unread. A failed workflow is never
replayed through the other engine. Existing IMAP IDLE and one-click confirmation
rules remain. Both engines refuse email-code challenges and recognize visible
success/invalid pages. Selenium uses native WebDriver waits and eager loading;
Playwright uses its existing DOM-ready navigation and locators. Their respective
packaged Chromium builds are part of the implementations being compared.

The Pi retains one warm browser. Switching engines closes the inactive browser;
the selected engine can reuse its previous session if still active and healthy.
Initial idle warmup is random too. Cold starts and warm successes are reported
separately; keeping both browsers resident would increase memory pressure on
this 2 GiB Pi. Cookies remain volatile and are never copied between engines.

`browser-experiment.sqlite`, next to the configured metrics file, retains
assignments, run IDs, engine, timestamps, outcome, elapsed workflow/navigation
seconds and warm/cold status. Mode 0600; no email identifiers, links, account data
or raw pages. Window begins once when production first creates this database;
restarts preserve its original deadline and results. The report selects runs
assigned within the first seven days. Assignment continues randomly after the
deadline until manual review chooses a permanent implementation. There is no
automatic winner switch.

Periodic review on the Pi:

```sh
docker exec netflixwatcher python3 /app/app/browser_experiment.py /metrics/browser-experiment.sqlite
```

Report includes per-engine assigned/eligible counts, successes, failures,
outcome breakdown, success rate, successful-run median/p95 and warm/cold medians.
Latency includes engine switching, startup and blank-page cleanup. Startup
recovery remains bounded by the existing implementation's retry policy.
Already-successful pages without a watcher click are excluded from automated
success claims. Mail-flag failures and interrupted processes remain visible but
excluded from engine reliability; opening a report never interrupts active runs.
Unfinished assignments are marked interrupted only when the watcher starts.
The full database keeps subsequent runs even after the first-week report closes.

Rank reliability first, then successful-run latency under comparable warm/cold
conditions. Random assignment does not guarantee equal sample counts. Check
counts and outcome categories before interpreting median/p95; no samples appear
as null in JSON and zero in Grafana. Avoid manual confirmation during a sampled
workflow, or note its run ID during review: external manual intervention cannot
be inferred reliably. Historical manually completed requests are outside this
new experiment. Preserve traces when diagnosing failures instead of assuming
that an external connection refusal caused the Household workflow to fail.

`rpi-netflix-ops` shows active engine, review date, assignments, success rates,
outcomes, successful median/p95 and warm/cold median durations. Low-cardinality
experiment metrics persist through process restarts; run IDs remain in logs and
SQLite only. Playwright retains network/JavaScript events; Selenium records native
stage, click, safe browser-state and sanitized error-class events. Native Selenium
exceptions, URLs and page content are never logged.
