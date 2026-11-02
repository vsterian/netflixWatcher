

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
