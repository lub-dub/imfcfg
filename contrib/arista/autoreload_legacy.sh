#!/bin/sh
kill -TERM `pgrep -f autoreload.py` 2>/dev/null || true
/usr/bin/python2 /mnt/flash/autoreload.py "$@"

