#!/usr/bin/env bash
# run-measure.sh — снять метрики OPTIMIZATIONS §2.3/§4 внутри пиннутого
# образа eatlang-dev:etap1 (несёт qemu-system-arm с insn-плагином и
# valgrind). Это ПРОФИЛЬ, не гейт: чистое измерение, паритет не трогает.
#
# §4   measure_mcu    — цикловая цена проверок mos6502 на Cortex-M3
#                       (qemu-system-arm -M mps2-an385 + insn-плагин),
#                       с верификатором и без; детерминированный счётчик.
# §2.3 measure_selfir — instr-профиль фаз self-hosted компилятора
#                       (valgrind callgrind), эмиссия IR = SelfIr − SelfTyped.
#
# Использование:
#   podman build -f containers/Containerfile -t eatlang-dev:etap1 containers
#   containers/run-measure.sh [ПУТЬ_К_ДЕРЕВУ] [ЦЕЛЬ]    # цель: measure|measure_mcu|measure_selfir
#
# По образцу run-gate.sh: venv В КОНТЕЙНЕРЕ, ulimit -s 262144 (пулы фаз в
# кадре main). Монтируй чистый worktree на HEAD, если рядом живёт чужой WIP.
set -euo pipefail

IMAGE="${IMAGE:-eatlang-dev:etap1}"
REPO="$(cd "${1:-$PWD}" && pwd)"
TARGET="${2:-measure}"

exec podman run --rm \
    -v "$REPO":/work \
    -w /work \
    -e UV_FROZEN=1 \
    -e UV_PROJECT_ENVIRONMENT=/root/eat-venv \
    "$IMAGE" \
    bash -c "ulimit -s 262144 && uv sync --frozen && make $TARGET"
