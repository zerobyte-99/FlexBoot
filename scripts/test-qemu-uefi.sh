#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
  echo "usage: $0 IMAGE" >&2
  exit 2
fi
exec python3 -m flexboot image boot "$1"

