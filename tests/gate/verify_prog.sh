#!/bin/sh
# Полносоставные конкатенации примеров (Rt + lib + модули): паритет
# РЕШЕНИЙ верификатора (MODE=verify: канон и -O) и оси -O IR
# (MODE=iropt) на программах целиком. Дрейф решений живёт только в
# контексте вызовов (FAULTS 2026-07-17: hex_digit) — пофайловый
# вакуумный паритет его не видит: файлы lib/ без main дают паритет
# отрицательного случая. Вход: main драйвера (stream --lib .) либо
# явный список файлов через запятую (mos6502 — конкатенация этапа 0).
set -eu
p="$1"
d=$(mktemp -d "${TMPDIR:-/tmp}/eat_prog.XXXXXX")
trap 'rm -rf "$d"' EXIT INT TERM
case "$p" in
*,*) (IFS=','; cat $p) > "$d/in.eat";;
*) env $EATC stream --lib . "$p" > "$d/in.eat";;
esac
if [ "${MODE:-verify}" = "iropt" ]; then
	if env $EATC ir -O "$d/in.eat" > "$d/ref.ll" 2>/dev/null; then
		./build/SelfIrOpt < "$d/in.eat" > "$d/self.ll"
		diff "$d/ref.ll" "$d/self.ll" > /dev/null \
			&& echo "IR-O OK $p" || { echo "IR-O DIFF $p"; exit 1; }
	fi
	exit 0
fi
env $EATC verify "$d/in.eat" > "$d/ref.txt" 2>/dev/null || true
./build/SelfVerify < "$d/in.eat" > "$d/self.txt" 2>/dev/null || true
diff "$d/ref.txt" "$d/self.txt" > /dev/null \
	&& echo "VERIFY OK $p" || { echo "VERIFY DIFF $p"; exit 1; }
env $EATC verify "$d/in.eat" -O > "$d/ref.txt" 2>/dev/null || true
./build/SelfVerify -O < "$d/in.eat" > "$d/self.txt" 2>/dev/null || true
diff "$d/ref.txt" "$d/self.txt" > /dev/null \
	&& echo "VERIFY-O OK $p" || { echo "VERIFY-O DIFF $p"; exit 1; }
