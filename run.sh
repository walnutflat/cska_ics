#!/bin/bash
DIR="$(dirname "$0")"
cd $DIR;
uv run "$DIR/main.py" && open --reveal cska.ics;