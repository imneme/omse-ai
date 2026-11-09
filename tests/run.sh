#!/bin/sh
# omse-ai's tests (about half a minute).  PY=/path/to/python3 ./tests/run.sh to choose a Python.
cd "$(dirname "$0")/.." || exit 1
exec "${PY:-python3}" -m unittest discover -s tests -v "$@"
