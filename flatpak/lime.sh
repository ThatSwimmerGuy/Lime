#!/bin/sh
export PYTHONPATH=/app/share/lime
exec python3 -m phonemessages "$@"
