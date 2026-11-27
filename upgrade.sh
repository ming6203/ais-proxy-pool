#!/bin/sh
# Run with an existing Python >=3.11; never installs dependencies or the app.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${PYTHON:-python3}" -B "$here/upgrade.py" "$@"
