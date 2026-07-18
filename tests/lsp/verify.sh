#!/usr/bin/env bash
# tests/lsp/verify.sh — сверка LSP-сервера транскриптом рукопожатия
# (docs/plans/LSP_PLAN.md, этап 0). По образцу EAT_NET для HTTP:
# детерминированная последовательность JSON-RPC запрос→ответ, но по
# stdio (аксиома read_byte), а не по сокету.
#
# Вход строится здесь (printf с CRLF-обрамлением Content-Length), чтобы
# в репозитории не жили CR-байты. Выход сервера нормализуется (CR
# срезается) и сверяется с эталоном tests/lsp/handshake.golden.
set -euo pipefail

cd "$(dirname "$0")/../.."

MAIN=editor/lsp/LspMain.eat
GOLDEN=tests/lsp/handshake.golden
IN=$(mktemp)
OUT=$(mktemp)
trap 'rm -f "$IN" "$OUT"' EXIT

# Кадр LSP: "Content-Length: N\r\n\r\n<тело>" (N — длина тела в байтах).
frame() {
    local body="$1"
    printf 'Content-Length: %d\r\n\r\n%s' "${#body}" "$body"
}

{
    frame '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"processId":null,"capabilities":{}}}'
    frame '{"jsonrpc":"2.0","method":"initialized","params":{}}'
    frame '{"jsonrpc":"2.0","id":2,"method":"shutdown"}'
    frame '{"jsonrpc":"2.0","method":"exit"}'
} > "$IN"

PYTHONPATH=src uv run python -m eatc run --lib . "$MAIN" < "$IN" | tr -d '\r' > "$OUT"

if diff -u "$GOLDEN" "$OUT"; then
    echo "verify_lsp: OK (рукопожатие initialize/shutdown/exit == эталон)"
else
    echo "verify_lsp: FAIL — вывод сервера разошёлся с эталоном" >&2
    exit 1
fi
