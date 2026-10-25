#!/usr/bin/env bash
# Зависимости Python в окружение: bash deploy/python_deps.sh <путь к python окружения>
# На Linux x86_64 сначала PyTorch без CUDA (deploy/torch-cpu.txt), затем requirements.txt.
set -euo pipefail

PY="$1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$PY" -m pip install -q --upgrade pip
if [ "$(uname -s)" = "Linux" ] && [ "$(uname -m)" = "x86_64" ]; then
    "$PY" -m pip install -q -r "$ROOT/deploy/torch-cpu.txt"
fi
"$PY" -m pip install -q -r "$ROOT/requirements.txt"
