#!/usr/bin/env bash
# measure_mcu.sh — §4 OPTIMIZATIONS: цикловая цена проверок на МК.
#
# Тот же mos6502 на Cortex-M3 (mps2-an385), собранный дважды — со снятыми
# верификатором доказанными проверками (канон `eatc build`) и со всеми
# проверками (канон `eatc ir` без verify) — прогоняется под qemu-system-arm
# с insn-плагином счётчика инструкций. Разница = цикловая цена проверок,
# которые верификатор доказал и снял (дополняет .text-метрику из
# mcu/README.md детерминированным счётчиком исполненных инструкций).
#
# Запускать ВНУТРИ образа eatlang-dev:etap1 (несёт qemu-system-arm с
# --enable-plugins и /usr/local/lib/libinsn.so; ENV EAT_QEMU_INSN):
#   podman run --rm -v <repo>:/work -w /work \
#     -e UV_PROJECT_ENVIRONMENT=/root/eat-venv eatlang-dev:etap1 \
#     bash containers/measure_mcu.sh
set -euo pipefail

PLUGIN="${EAT_QEMU_INSN:?нет EAT_QEMU_INSN — не тот образ (нужен etap1)}"
BOARD=mps2_an385
M=/tmp/measure_mcu
mkdir -p "$M"

# пулы self-hosted компилятора живут в кадре main — тот же потолок стека,
# что у гейта (run-gate.sh); без него runtime.c re-exec'ит бинарник.
ulimit -s 262144 || true
uv sync --frozen >/dev/null 2>&1 || uv sync >/dev/null 2>&1

export PYTHONPATH=src
EATC=(uv run python -m eatc)

echo "== эмиссия обоих .ll через внутренности eatc (apples-to-apples: единственная разница — verify) =="
# mos6502 многофайловый → канон `eatc ir` (однофайловый) не годится;
# эмитируем оба .ll напрямую как README §4: compile_binary(link=False) без
# verify() = все проверки, с verify() = доказанные сняты (элизия).
uv run python - "$M" <<'PY'
import sys
from eatc.__main__ import _compile_many
from eatc.codegen import compile_binary
from eatc.verifier import verify
outdir = sys.argv[1]
paths = ["selfhost/Rt.eat", "lib/fmt/Hex.eat",
         "examples/mos6502/Cpu6502.eat", "examples/mos6502/Tests.eat",
         "examples/mos6502/Main.eat"]
# все проверки: без verify → элизии нет
p, _, t, m = _compile_many(paths)
compile_binary(p, t.checker, m, outdir + "/all", trap_codes=True, link=False)
# доказанные сняты: свежая загрузка, verify → компиляция с элизией
p2, _, t2, m2 = _compile_many(paths)
pr = verify(p2, t2.checker)
compile_binary(p2, t2.checker, m2, outdir + "/elided", trap_codes=True,
               link=False)
print(f"trap-checks: всего {pr['total']}, доказано {pr['proven']}, "
      f"в рантайме остаётся {pr['total'] - pr['proven']}")
PY

uv run python mcu/common/embed_input.py examples/mos6502/mul13x11.rom \
  > "$M/input.c"

# флаги платы — точно как mcu-цель Makefile (mps2_an385/board.mk)
CC=(clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -O2 -ffreestanding \
    -fno-unwind-tables -Wno-override-module)

echo "== сборка общих объектов шима/платы/входа (одни на оба варианта) =="
COMMON_SRC=(mcu/common/runtime.c mcu/common/startup.c mcu/common/eabi64.c \
            mcu/common/shim.c "mcu/boards/$BOARD/board.c" "$M/input.c")
COMMON_OBJS=()
for f in "${COMMON_SRC[@]}"; do
  o="$M/$(basename "${f%.*}").o"
  "${CC[@]}" -c "$f" -o "$o"
  COMMON_OBJS+=("$o")
done

run_variant() {  # $1 = метка, $2 = путь .ll
  local v="$1" ll="$2"
  "${CC[@]}" -flto -c "$ll" -o "$M/$v.o"
  ld.lld -T "mcu/boards/$BOARD/board.ld" "$M/$v.o" "${COMMON_OBJS[@]}" \
    -o "$M/$v.elf"
  llvm-size-22 "$M/$v.elf" 2>/dev/null || size "$M/$v.elf" || true
  # вывод insn-плагина в system-mode идёт в -D лог только под -d plugin.
  # два прогона — подтверждаем детерминизм счётчика.
  local c1 c2
  qemu-system-arm -M mps2-an385 -semihosting -display none -monitor none \
    -serial file:"$M/$v.out" -plugin "$PLUGIN" -d plugin -D "$M/$v.qlog" \
    -kernel "$M/$v.elf" >/dev/null 2>&1
  c1=$(grep -oE 'total insns: [0-9]+' "$M/$v.qlog" | grep -oE '[0-9]+' || true)
  qemu-system-arm -M mps2-an385 -semihosting -display none -monitor none \
    -serial null -plugin "$PLUGIN" -d plugin -D "$M/$v.qlog2" \
    -kernel "$M/$v.elf" >/dev/null 2>&1
  c2=$(grep -oE 'total insns: [0-9]+' "$M/$v.qlog2" | grep -oE '[0-9]+' || true)
  echo "VARIANT $v insns=$c1 (повтор=$c2)"
}

echo "== прогон под qemu-system-arm + insn-плагин =="
run_variant elided "$M/elided.ll"
run_variant all    "$M/all.ll"

echo "== санити: вывод mos6502 == эталон интерпретатора? =="
cat examples/mos6502/mul13x11.rom | "${EATC[@]}" run \
  selfhost/Rt.eat lib/fmt/Hex.eat examples/mos6502/Cpu6502.eat \
  examples/mos6502/Tests.eat examples/mos6502/Main.eat > "$M/interp.out"
if diff -q "$M/interp.out" "$M/elided.out" >/dev/null; then
  echo "OK: elided ELF == интерпретатор"
else
  echo "ВНИМАНИЕ: вывод elided ELF расходится с интерпретатором"; fi
