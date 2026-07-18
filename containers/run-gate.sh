#!/usr/bin/env bash
# run-gate.sh — прогнать ПОЛНЫЙ ГЕЙТ (AGENTS.md §3) внутри пиннутого
# образа против смонтированного дерева репозитория. Этап 0 плана
# CONTAINERS_PLAN.md — разовая сверка «10 целей зелёные в контейнере».
#
# Это НЕ процесс «контейнер-на-задачу» (task-*/merge — этап 1); просто
# одноразовый прогон гейта в образе.
#
# Использование:
#   podman build -f containers/Containerfile -t eatlang-dev:etap0 containers
#   containers/run-gate.sh [ПУТЬ_К_ДЕРЕВУ]   # по умолчанию — текущий репозиторий
#
# ВАЖНО: при живом соседском WIP монтируй ЧИСТЫЙ worktree на HEAD, а не
# рабочее дерево (чужой грязный WIP ломает гейт — FAULTS 2026-07-16):
#   git worktree add ../EATLang-gate HEAD
#   containers/run-gate.sh ../EATLang-gate
set -euo pipefail

IMAGE="${IMAGE:-eatlang-dev:etap0}"
REPO="$(cd "${1:-$PWD}" && pwd)"

GATE='make check verify verify_suite verify_selfhost verify_bootstrap \
      verify_trapcodes verify_selfhost_opt verify_sig \
      verify_selfhost_verify verify_selfhost_verify_all'

# venv — В КОНТЕЙНЕРЕ, не в смонтированном дереве: у хостового `.venv`
# llvmlite под macOS, в linux-контейнере он бы не импортировался. Makefile
# зовёт `uv run` — та же переменная направит его на linux-venv.
exec podman run --rm \
    -v "$REPO":/work \
    -w /work \
    -e UV_FROZEN=1 \
    -e UV_PROJECT_ENVIRONMENT=/root/eat-venv \
    "$IMAGE" \
    bash -c "uv sync --frozen && $GATE"
