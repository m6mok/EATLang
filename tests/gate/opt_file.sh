#!/bin/sh
# Сверка оси -O для одного входа (make verify_selfhost_opt):
# eatc ir -O == SelfIrOpt байт-в-байт. Параллельный воркер xargs -P.
set -eu
f="$1"
d=$(mktemp -d "${TMPDIR:-/tmp}/eat_iro.XXXXXX")
trap 'rm -rf "$d"' EXIT INT TERM
cat $RT "$f" > "$d/in.eat"
if env $EATC ir -O "$d/in.eat" > "$d/ref.ll" 2>/dev/null; then
	./build/SelfIrOpt < "$d/in.eat" > "$d/self.ll"
	diff "$d/ref.ll" "$d/self.ll" > /dev/null \
		&& echo "IR-O OK $f" || { echo "IR-O DIFF $f"; exit 1; }
fi
