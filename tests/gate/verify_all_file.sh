#!/bin/sh
# Полнорепный паритет верификатора для одного .eat (make
# verify_selfhost_verify_all): канон и режим -O, вход cat Rt + файл.
# Файлы без main — паритет отрицательного случая (оба дампа пусты),
# коды возврата эталона/SelfVerify намеренно игнорируются (|| true).
set -eu
f="$1"
case "$f" in selfhost/Verify.eat|selfhost/VerifyMain.eat) exit 0;; esac
d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vfa.XXXXXX")
trap 'rm -rf "$d"' EXIT INT TERM
cat $RT "$f" > "$d/in.eat"
env $EATC verify "$d/in.eat" > "$d/ref.txt" 2>/dev/null || true
./build/SelfVerify < "$d/in.eat" > "$d/self.txt" 2>/dev/null || true
diff "$d/ref.txt" "$d/self.txt" > /dev/null \
	&& echo "VERIFY OK $f" || { echo "VERIFY DIFF $f"; exit 1; }
env $EATC verify "$d/in.eat" -O > "$d/ref.txt" 2>/dev/null || true
./build/SelfVerify -O < "$d/in.eat" > "$d/self.txt" 2>/dev/null || true
diff "$d/ref.txt" "$d/self.txt" > /dev/null \
	&& echo "VERIFY-O OK $f" || { echo "VERIFY-O DIFF $f"; exit 1; }
