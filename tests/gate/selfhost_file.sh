#!/bin/sh
# Пофайловая сверка self-hosted фаз с эталоном (make verify_selfhost).
# Вызывается через `xargs -P` — параллельно; временные файлы уникальны
# (mktemp -d), окружение EATC/RT передаёт Makefile. Аргумент — путь .eat.
set -eu
f="$1"
d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vs.XXXXXX")
trap 'rm -rf "$d"' EXIT INT TERM
env $EATC lex "$f" > "$d/lex_ref.txt"
./build/SelfLex < "$f" > "$d/lex_self.txt"
diff "$d/lex_ref.txt" "$d/lex_self.txt" > /dev/null && echo "LEX OK $f" \
	|| { echo "LEX DIFF $f"; exit 1; }
if env $EATC parse "$f" > "$d/parse_ref.txt" 2>/dev/null; then
	./build/SelfParse < "$f" > "$d/parse_self.txt"
	diff "$d/parse_ref.txt" "$d/parse_self.txt" > /dev/null \
		&& echo "PARSE OK $f" || { echo "PARSE DIFF $f"; exit 1; }
fi
if env $EATC sig "$f" > "$d/sig_ref.txt" 2>/dev/null; then
	./build/SelfSig < "$f" > "$d/sig_self.txt"
	diff "$d/sig_ref.txt" "$d/sig_self.txt" > /dev/null \
		&& echo "SIG OK $f" || { echo "SIG DIFF $f"; exit 1; }
fi
if env $EATC typed "$f" > "$d/typed_ref.txt" 2>/dev/null; then
	./build/SelfTyped < "$f" > "$d/typed_self.txt"
	diff "$d/typed_ref.txt" "$d/typed_self.txt" > /dev/null \
		&& echo "TYPED OK $f" || { echo "TYPED DIFF $f"; exit 1; }
fi
cat $RT "$f" > "$d/ir_in.eat"
if env $EATC ir "$d/ir_in.eat" > "$d/ir_ref.ll" 2>/dev/null; then
	./build/SelfIr < "$d/ir_in.eat" > "$d/ir_self.ll"
	diff "$d/ir_ref.ll" "$d/ir_self.ll" > /dev/null \
		&& echo "IR OK $f" || { echo "IR DIFF $f"; exit 1; }
fi
