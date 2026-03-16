#!/bin/bash
# Monitor Elasticsearch ingestion progress

# Run curl inside docker, but parse on the host to avoid nested quoting hell
count=$(docker compose exec -T elasticsearch curl -sS http://localhost:9200/gabi_documents_v1/_count 2>/dev/null | grep -oE '"count":[0-9]+' | cut -d: -f2)

# Prevent script from crashing if count is empty (e.g., ES is restarting)
if [ -z "$count" ]; then
  echo "Waiting for Elasticsearch to respond..."
  exit 0
fi

total=15771256
now=$(date +%s)
state=/tmp/gabi-es-eta.state

if [ -f "$state" ]; then
  read prev_count prev_time < "$state"
  delta_count=$((count - prev_count))
  delta_time=$((now - prev_time))

  if [ "$delta_count" -gt 0 ] && [ "$delta_time" -gt 0 ]; then
    remaining=$((total - count))
    rate=$((delta_count * 60 / delta_time))
    eta_sec=$((remaining * delta_time / delta_count))
    printf "count=%s / %s  rate=%s docs/min  eta=%02dh:%02dm:%02ds\n" \
      "$count" "$total" "$rate" \
      "$((eta_sec/3600))" "$(((eta_sec%3600)/60))" "$((eta_sec%60))"
  else
    printf "count=%s / %s  rate=warming-up\n" "$count" "$total"
  fi
else
  printf "count=%s / %s  collecting baseline...\n" "$count" "$total"
fi

echo "$count $now" > "$state"
