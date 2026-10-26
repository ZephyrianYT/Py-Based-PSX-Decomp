#!/bin/sh
# Start the web UI. UI_PORT and UI_BIND choose where it listens (as MA_PORT does
# for opencanary-ui). Inside a container it must bind 0.0.0.0 to be reachable;
# the port is only published to the host by `docker run -p` / compose.
set -eu
cd "$(dirname "$0")"
exec streamlit run app.py \
  --server.port "${UI_PORT:-8501}" \
  --server.address "${UI_BIND:-0.0.0.0}"
