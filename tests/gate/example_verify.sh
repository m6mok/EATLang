#!/bin/sh
# Сверка одного примера (make verify): вывод бинарника == вывод
# интерпретатора. Параллельный воркер xargs -P; diff при расхождении
# печатается (как в исходном цикле).
set -eu
f="$1"
name=$(basename "$f" .eat)
d=$(mktemp -d "${TMPDIR:-/tmp}/eat_ver.XXXXXX")
trap 'rm -rf "$d"' EXIT INT TERM
echo "" | env $EATC run $RT "$f" > "$d/interp.txt"
echo "" | "./build/$name" > "$d/native.txt"
diff "$d/interp.txt" "$d/native.txt" && echo "VERIFIED $name" || exit 1
