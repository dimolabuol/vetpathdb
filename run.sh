#!/bin/bash

# VetPathDB Startup Script
# Activate your Python environment (conda, venv, etc.) before running.

# Load .env if present
set -a
[ -f .env ] && . ./.env
set +a

python -m vetpathdb serve "$@"
