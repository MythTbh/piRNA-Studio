#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! bash packaging/setup.sh; then
  printf '\n%s\n' 'Setup could not finish. Check the messages above or .runtime/setup.log, then reopen this launcher to retry.'
  if [ -t 0 ]; then read -r -p 'Press Return to close.' _; fi
  exit 1
fi
source packaging/runtime.sh
"$runner" -m server --port 8765 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT INT TERM
for _ in 1 2 3 4 5; do
  sleep 1
  kill -0 "$server_pid" 2>/dev/null || { wait "$server_pid"; exit 1; }
  if curl -fsS http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    if command -v open >/dev/null; then open http://127.0.0.1:8765/;
    elif command -v xdg-open >/dev/null; then xdg-open http://127.0.0.1:8765/; fi
    break
  fi
done
wait "$server_pid"
