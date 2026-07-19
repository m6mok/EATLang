#!/usr/bin/env bash
# measure_selfir.sh — §2.3 OPTIMIZATIONS: детерминированный instr-профиль
# фаз self-hosted компилятора «ниже пола `sample`».
#
# valgrind --tool=callgrind даёт точный, детерминированный между прогонами
# счётчик исполненных инструкций (Ir) нативного бинарника + пофункциональную
# атрибуцию — это «инструментированный прогон», который сам §2.3 называет
# допустимым энейблером. (Почему не qemu-user insn-плагин: Debian собирает
# --enable-plugins только для qemu-system-*; qemu-user идёт без плагинов —
# FAULTS 2026-07-19.)
#
# Вход — реальная самокомпиляция: склейка модулей IR-фазы (тот же поток, что
# verify_bootstrap и нагрузка «0.14 с» бенча). Каждый фазовый бинарник
# делает полный фронтенд плюс свою эмиссию; эмиссия IR ≈ SelfIr − SelfTyped
# (та же декомпозиция ir−typed, что в §2.3).
#
# Бинарники build/measure/Self{Lex,Parse,Sig,Typed,Ir} собирает вызывающий
# (make measure_selfir — из тех же SELFHOST_* списков, DRY). Отдельный
# каталог build/measure/ — чтобы Linux-ELF профиля НИКОГДА не затирал
# build/Self* гейта (иначе на хосте ложный красный — FAULTS 2026-07-19).
set -euo pipefail

SRC="${1:?использование: measure_selfir.sh <вход.eat>}"
CG=/tmp/measure_selfir
mkdir -p "$CG"
# пулы фаз живут в кадре main — тот же потолок стека, что у гейта
ulimit -s 262144 || true

declare -A IR
PHASES=(SelfLex SelfParse SelfSig SelfTyped SelfIr)
for bin in "${PHASES[@]}"; do
  b="build/measure/$bin"
  [ -x "$b" ] || { echo "нет $b — соберите: make measure_selfir"; exit 1; }
  out="$CG/$bin.cg"
  # только Ir (без кэш/бранч-симуляции) — быстро и детерминированно.
  # Пулы фаз живут ОДНИМ кадром main (~85 МБ, фаза 5). valgrind даёт
  # клиенту всего 16 МБ стека по умолчанию (ulimit -s он не уважает) —
  # без --main-stacksize main переполняет стек и падает; --max-stackframe
  # глушит эвристику «подозрительно большой кадр». 256 МБ = потолок гейта.
  valgrind --tool=callgrind --callgrind-out-file="$out" \
      --cache-sim=no --branch-sim=no \
      --main-stacksize=268435456 --max-stackframe=268435456 \
      "$b" < "$SRC" > "$CG/$bin.dump" 2> "$CG/$bin.log"
  ir=$(grep -E '^summary:' "$out" | awk '{print $2}')
  IR[$bin]=$ir
  echo "PHASE $bin Ir=$ir  (дамп $(wc -c < "$CG/$bin.dump") Б)"
done

echo "=== декомпозиция по фазам (инструкций, Ir) ==="
echo "lex                     : ${IR[SelfLex]}"
echo "parse−lex               : $(( ${IR[SelfParse]} - ${IR[SelfLex]} ))"
echo "check (sig−parse)       : $(( ${IR[SelfSig]} - ${IR[SelfParse]} ))"
echo "typed (полн. фронтенд)  : ${IR[SelfTyped]}"
echo "IR-эмиссия (SelfIr−Typed): $(( ${IR[SelfIr]} - ${IR[SelfTyped]} ))"
echo "SelfIr всего            : ${IR[SelfIr]}"
awk -v ir="${IR[SelfIr]}" -v ty="${IR[SelfTyped]}" 'BEGIN{
  printf "IR-эмиссия как доля SelfIr: %.1f%%\n", 100*(ir-ty)/ir }'

echo "=== топ функций SelfIr (callgrind_annotate) — где кандидаты §2.3? ==="
callgrind_annotate --threshold=90 "$CG/SelfIr.cg" 2>/dev/null \
  | sed -n '/Ir  *file:function/,/^$/p' | head -30 || true
