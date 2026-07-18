#!/usr/bin/env bash
# task.sh — процесс «контейнер-на-задачу» (CONTAINERS_PLAN этап 1).
#
# Хаб — ОТДЕЛЬНЫЙ bare-репозиторий (решение пользователя §10.4), источник
# правды для переноса; задача — ветка task/<имя> в хабе; агент — контейнер
# над своим worktree этой ветки; перенос — MERGE-COMMIT в master хаба
# (решение §10.3) СТРОГО после зелёного полного гейта в контейнере.
#
# Подкоманды (Makefile: make task-<команда> NAME=<имя>):
#   up <имя>     хаб (создать при отсутствии) + ветка task/<имя> + worktree
#   shell <имя>  интерактивный контейнер над worktree задачи (git работает:
#                worktree и хаб смонтированы по хостовым путям)
#   gate <имя>   полный гейт (10 целей) в контейнере над worktree задачи
#   merge <имя>  чистота worktree → полный гейт → merge --no-ff в master
#                хаба (временный worktree хаба) → ff-sync master репозитория
#   down <имя>   убрать worktree и слитую ветку (неслитую не удаляет)
#   sync         подтянуть master репозитория к master хаба (ff-only)
#
# Пути (переопределяются окружением):
#   EAT_HUB   — bare-хаб   (по умолчанию ../EATLang-hub.git)
#   EAT_TASKS — worktree'ы (по умолчанию ../eatlang-tasks/<имя>)
#   IMAGE     — пиннутый образ (по умолчанию eatlang-dev:etap0)
#
# Гигиена — docs/CONTAINERS.md: podman run всегда --rm, venv в контейнере
# (UV_PROJECT_ENVIRONMENT), ulimit -s 262144 (256 МиБ = потолок линковки).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
HUB="${EAT_HUB:-$(dirname "$REPO")/EATLang-hub.git}"
TASKS="${EAT_TASKS:-$(dirname "$REPO")/eatlang-tasks}"
IMAGE="${IMAGE:-eatlang-dev:etap0}"

GATE='make check verify verify_suite verify_selfhost verify_bootstrap \
      verify_trapcodes verify_selfhost_opt verify_sig \
      verify_selfhost_verify verify_selfhost_verify_all'

usage() {
    echo "использование: containers/task.sh {up|shell|gate|merge|down} <имя> | sync" >&2
    exit 2
}

cmd="${1:-}"
name="${2:-}"
if [ "$cmd" != "sync" ] && { [ -z "$cmd" ] || [ -z "$name" ]; }; then
    usage
fi
BR="task/$name"
WT="$TASKS/$name"

# ff-подтяжка master репозитория к master хаба (после merge в хабе).
hub_sync() {
    [ -d "$HUB" ] || { echo "хаба нет: $HUB (сначала task-up)"; return 0; }
    git -C "$REPO" fetch "$HUB" master
    if git -C "$REPO" merge-base --is-ancestor FETCH_HEAD HEAD; then
        echo "sync: master репозитория не отстаёт от хаба"
    elif git -C "$REPO" merge-base --is-ancestor HEAD FETCH_HEAD; then
        git -C "$REPO" merge --ff-only FETCH_HEAD
        echo "sync: master репозитория подтянут к хабу"
    else
        echo "sync: ветки разошлись — разбор вручную (хаб: $HUB)" >&2
        exit 1
    fi
}

case "$cmd" in
up)
    if [ ! -d "$HUB" ]; then
        git init --bare -b master "$HUB"
        git -C "$REPO" push "$HUB" master:master
        echo "хаб создан: $HUB (master = $(git -C "$REPO" rev-parse --short HEAD))"
    else
        # рабочий master уехал вперёд хаба — заслать (ff); отстал — sync
        if git -C "$REPO" push "$HUB" master:master 2>/dev/null; then
            echo "хаб обновлён master'ом репозитория"
        else
            hub_sync
        fi
    fi
    mkdir -p "$TASKS"
    if git --git-dir="$HUB" show-ref --verify --quiet "refs/heads/$BR"; then
        git --git-dir="$HUB" worktree add "$WT" "$BR"
    else
        git --git-dir="$HUB" worktree add "$WT" -b "$BR" master
    fi
    echo "worktree задачи: $WT (ветка $BR)"
    echo "дальше: make task-shell NAME=$name  # или task-gate / task-merge"
    ;;
shell)
    # worktree и хаб — по хостовым путям: .git worktree'а указывает на
    # $HUB/worktrees/<имя> абсолютным путём, git внутри контейнера работает
    exec podman run -it --rm \
        -v "$WT":"$WT" \
        -v "$HUB":"$HUB" \
        -w "$WT" \
        -e UV_FROZEN=1 \
        -e UV_PROJECT_ENVIRONMENT=/root/eat-venv \
        "$IMAGE" \
        bash -c "ulimit -s 262144 && uv sync --frozen && exec bash"
    ;;
gate)
    exec podman run --rm \
        -v "$WT":/work \
        -w /work \
        -e UV_FROZEN=1 \
        -e UV_PROJECT_ENVIRONMENT=/root/eat-venv \
        "$IMAGE" \
        bash -c "ulimit -s 262144 && uv sync --frozen && $GATE"
    ;;
merge)
    if [ -n "$(git -C "$WT" status --porcelain)" ]; then
        echo "merge: в worktree незакоммиченный WIP — сначала commit" >&2
        exit 1
    fi
    echo "merge: полный гейт в контейнере над $WT (обязателен перед переносом)"
    podman run --rm \
        -v "$WT":/work \
        -w /work \
        -e UV_FROZEN=1 \
        -e UV_PROJECT_ENVIRONMENT=/root/eat-venv \
        "$IMAGE" \
        bash -c "ulimit -s 262144 && uv sync --frozen && $GATE"
    MW="$(mktemp -d)/merge"
    git --git-dir="$HUB" worktree add "$MW" master
    if ! git -C "$MW" merge --no-ff --no-edit "$BR"; then
        git -C "$MW" merge --abort || true
        git --git-dir="$HUB" worktree remove --force "$MW"
        echo "merge: конфликт — в worktree задачи слей master хаба в $BR," >&2
        echo "перегони гейт и повтори task-merge" >&2
        exit 1
    fi
    git --git-dir="$HUB" worktree remove "$MW"
    echo "merge: $BR слит в master хаба ($(git --git-dir="$HUB" rev-parse --short master))"
    hub_sync
    ;;
down)
    git --git-dir="$HUB" worktree remove "$WT"
    git --git-dir="$HUB" branch -d "$BR"
    echo "задача $name убрана (worktree и ветка)"
    ;;
sync)
    hub_sync
    ;;
*)
    usage
    ;;
esac
