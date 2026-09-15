#!/usr/bin/env bash
set -u

metrics_file=${METRICS_FILE:-/metrics/netflix-watcher-scheduler.prom}
service_up=1
last_heartbeat=0
next_run=0
last_attempt=0
last_success=-1
success_total=0
failure_total=0

write_metrics() {
    local temporary
    mkdir -p "$(dirname "$metrics_file")"
    temporary=$(mktemp "${metrics_file}.tmp.XXXXXX")
    {
        printf '# TYPE netflix_scheduler_service_up gauge\nnetflix_scheduler_service_up %s\n' "$service_up"
        printf '# TYPE netflix_scheduler_last_heartbeat_timestamp_seconds gauge\nnetflix_scheduler_last_heartbeat_timestamp_seconds %s\n' "$last_heartbeat"
        printf '# TYPE netflix_scheduler_next_run_timestamp_seconds gauge\nnetflix_scheduler_next_run_timestamp_seconds %s\n' "$next_run"
        printf '# TYPE netflix_scheduler_last_restart_attempt_timestamp_seconds gauge\nnetflix_scheduler_last_restart_attempt_timestamp_seconds %s\n' "$last_attempt"
        printf '# TYPE netflix_scheduler_last_restart_success gauge\nnetflix_scheduler_last_restart_success %s\n' "$last_success"
        printf '# TYPE netflix_scheduler_restart_success_total counter\nnetflix_scheduler_restart_success_total %s\n' "$success_total"
        printf '# TYPE netflix_scheduler_restart_failure_total counter\nnetflix_scheduler_restart_failure_total %s\n' "$failure_total"
    } > "$temporary"
    chmod 0644 "$temporary"
    mv "$temporary" "$metrics_file"
}

shutdown() {
    service_up=0
    last_heartbeat=$(date +%s)
    write_metrics
    exit 0
}
trap shutdown TERM INT

while true; do
    now=$(date +%s)
    hour=$(date +%H)
    minute=$(date +%M)
    second=$(date +%S)
    seconds_today=$((10#$hour * 3600 + 10#$minute * 60 + 10#$second))
    target_seconds=$((18 * 3600))
    if (( seconds_today < target_seconds )); then
        delay=$((target_seconds - seconds_today))
    else
        delay=$((86400 - seconds_today + target_seconds))
    fi
    next_run=$((now + delay))
    last_heartbeat=$now
    write_metrics
    sleep "$delay" &
    wait $!

    last_attempt=$(date +%s)
    last_heartbeat=$last_attempt
    if docker restart netflixwatcher; then
        last_success=1
        success_total=$((success_total + 1))
    else
        last_success=0
        failure_total=$((failure_total + 1))
    fi
    write_metrics
done
