#!/usr/bin/env bash
# Compatibility entrypoint. Manual usage is now Python-first:
#   python3 scripts/dev-test-setup.py --stack-name dev --user-pool mgmt
exec python3 "$(dirname "$0")/dev-test-setup.py" "$@"
