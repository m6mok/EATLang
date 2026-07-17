#!/bin/sh
# Хвост verify_selfhost: поток драйвера, конкатенации, самоприменение
# и interp == native. Блоки независимы — исполняются параллельно,
# каждый со своим mktemp-каталогом. EATC/RT/STACK_FLAGS и списки
# модулей фаз передаёт Makefile переменными окружения.
set -u

stream_job() {
	d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vst.XXXXXX")
	trap 'rm -rf "$d"' EXIT INT TERM
	env $EATC stream --lib . $MODULES_MAIN > "$d/stream.eat" || exit 1
	env $EATC lex "$d/stream.eat" > "$d/ref.txt" || exit 1
	./build/SelfLex < "$d/stream.eat" > "$d/self.txt"
	diff "$d/ref.txt" "$d/self.txt" > /dev/null \
		&& echo "LEX OK (поток драйвера: Rt + lib + Main c #module)" || exit 1
	env $EATC parse "$d/stream.eat" > "$d/ref.txt" || exit 1
	./build/SelfParse < "$d/stream.eat" > "$d/self.txt"
	diff "$d/ref.txt" "$d/self.txt" > /dev/null \
		&& echo "PARSE OK (поток драйвера)" || exit 1
	env $EATC sig "$d/stream.eat" > "$d/ref.txt" || exit 1
	./build/SelfSig < "$d/stream.eat" > "$d/self.txt"
	diff "$d/ref.txt" "$d/self.txt" > /dev/null \
		&& echo "SIG OK (поток драйвера)" || exit 1
	env $EATC typed "$d/stream.eat" > "$d/ref.txt" || exit 1
	./build/SelfTyped < "$d/stream.eat" > "$d/self.txt"
	diff "$d/ref.txt" "$d/self.txt" > /dev/null \
		&& echo "TYPED OK (поток драйвера)" || exit 1
	env $EATC ir "$d/stream.eat" > "$d/ref.ll" || exit 1
	./build/SelfIr < "$d/stream.eat" > "$d/self.ll"
	diff "$d/ref.ll" "$d/self.ll" > /dev/null \
		&& echo "IR OK (поток драйвера: trap-атрибуция пофайловая)" || exit 1
}

sig_all_job() {
	d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vst.XXXXXX")
	trap 'rm -rf "$d"' EXIT INT TERM
	cat $SELFHOST_SIG > "$d/all.eat"
	env $EATC sig "$d/all.eat" > "$d/ref.txt" || exit 1
	./build/SelfSig < "$d/all.eat" > "$d/self.txt"
	diff "$d/ref.txt" "$d/self.txt" > /dev/null \
		&& echo "SIG OK (конкатенация собственных исходников)" || exit 1
}

typed_ir_job() {
	d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vst.XXXXXX")
	trap 'rm -rf "$d"' EXIT INT TERM
	cat $SELFHOST_TYPED > "$d/all.eat"
	env $EATC typed "$d/all.eat" > "$d/ref.txt" || exit 1
	./build/SelfTyped < "$d/all.eat" > "$d/self.txt"
	diff "$d/ref.txt" "$d/self.txt" > /dev/null \
		&& echo "TYPED OK (тайпчекер типизирует сам себя)" || exit 1
	env $EATC ir "$d/all.eat" > "$d/ref.ll" || exit 1
	./build/SelfIr < "$d/all.eat" > "$d/self.ll"
	diff "$d/ref.ll" "$d/self.ll" > /dev/null \
		&& echo "IR OK (самоприменение: IR всего фронтенда байт-в-байт)" || exit 1
	cat lib/Ascii.eat examples/lexer/LexUtil.eat examples/lexer/LexMain.eat \
		> "$d/probe.eat"
	clang "$d/self.ll" src/eatc/runtime.c -o "$d/typed_bin" \
		$STACK_FLAGS 2>/dev/null || exit 1
	"$d/typed_bin" < "$d/probe.eat" > "$d/e2e.txt"
	env $EATC typed "$d/probe.eat" > "$d/ref.txt" || exit 1
	diff "$d/ref.txt" "$d/e2e.txt" \
		&& echo "VERIFIED SelfIr (тайпчекер, собранный clang из self-IR, == эталон)" \
		|| exit 1
}

lex_interp_job() {
	d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vst.XXXXXX")
	trap 'rm -rf "$d"' EXIT INT TERM
	cat $SELFHOST_LEXER | env $EATC run $SELFHOST_LEXER > "$d/interp.txt" || exit 1
	cat $SELFHOST_LEXER | ./build/SelfLex > "$d/native.txt"
	diff "$d/interp.txt" "$d/native.txt" \
		&& echo "VERIFIED SelfLex (interp == native == эталон)" || exit 1
}

parse_interp_job() {
	d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vst.XXXXXX")
	trap 'rm -rf "$d"' EXIT INT TERM
	cat $SELFHOST_PARSER | env $EATC run $SELFHOST_PARSER > "$d/interp.txt" || exit 1
	cat $SELFHOST_PARSER | ./build/SelfParse > "$d/native.txt"
	diff "$d/interp.txt" "$d/native.txt" \
		&& echo "VERIFIED SelfParse (interp == native == эталон)" || exit 1
}

sig_interp_job() {
	d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vst.XXXXXX")
	trap 'rm -rf "$d"' EXIT INT TERM
	cat $SELFHOST_SIG | env $EATC run $SELFHOST_SIG > "$d/interp.txt" || exit 1
	cat $SELFHOST_SIG | ./build/SelfSig > "$d/native.txt"
	diff "$d/interp.txt" "$d/native.txt" \
		&& echo "VERIFIED SelfSig (interp == native == эталон)" || exit 1
}

typed_interp_job() {
	d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vst.XXXXXX")
	trap 'rm -rf "$d"' EXIT INT TERM
	cat lib/Ascii.eat examples/lexer/LexUtil.eat examples/lexer/LexMain.eat \
		> "$d/probe.eat"
	cat "$d/probe.eat" | env $EATC run $SELFHOST_TYPED > "$d/interp.txt" || exit 1
	cat "$d/probe.eat" | ./build/SelfTyped > "$d/native.txt"
	diff "$d/interp.txt" "$d/native.txt" \
		&& echo "VERIFIED SelfTyped (interp == native, проба лексера)" || exit 1
}

ir_interp_job() {
	d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vst.XXXXXX")
	trap 'rm -rf "$d"' EXIT INT TERM
	cat $RT examples/hello_world/HelloWorld.eat \
		| env $EATC run $SELFHOST_IR > "$d/interp.txt" || exit 1
	cat $RT examples/hello_world/HelloWorld.eat \
		| ./build/SelfIr > "$d/native.txt"
	diff "$d/interp.txt" "$d/native.txt" \
		&& echo "VERIFIED SelfIr (interp == native)" || exit 1
}

stream_job & p1=$!
sig_all_job & p2=$!
typed_ir_job & p3=$!
lex_interp_job & p4=$!
parse_interp_job & p5=$!
sig_interp_job & p6=$!
typed_interp_job & p7=$!
ir_interp_job & p8=$!
fail=0
for p in $p1 $p2 $p3 $p4 $p5 $p6 $p7 $p8; do
	wait $p || fail=1
done
exit $fail
