#!/usr/bin/env bash
# Compatibility entrypoint. Manual usage is now Python-first:
#   python3 scripts/dev-test-setup.py --stack-name dev --user-pool mgmt
source .venv/bin/activate

eval "$(python ./scripts/dev-test-setup.py "$@")"

deactivate