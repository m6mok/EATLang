#!/bin/sh
# Смок-кейс верификатора (make verify_selfhost_verify): SelfVerify ==
# eatc verify на одном курируемом кейсе. Параллельный воркер xargs -P.
set -eu
c="$1"
test -f "tests/verify/$c.eat" \
	|| { echo "VERIFY NO CASE $c (пустые дампы дали бы ложный OK)"; exit 1; }
d=$(mktemp -d "${TMPDIR:-/tmp}/eat_vfy.XXXXXX")
trap 'rm -rf "$d"' EXIT INT TERM
env $EATC verify "tests/verify/$c.eat" > "$d/ref.txt" || true
./build/SelfVerify < "tests/verify/$c.eat" > "$d/self.txt" || true
diff "$d/ref.txt" "$d/self.txt" > /dev/null \
	&& echo "VERIFY OK $c" || { echo "VERIFY DIFF $c"; exit 1; }
