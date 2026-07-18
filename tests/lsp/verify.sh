#!/usr/bin/env bash
# tests/lsp/verify.sh — сверка LSP-сервера транскриптом сессии JSON-RPC
# (docs/plans/LSP_PLAN.md, этап 1). По образцу EAT_NET для HTTP:
# детерминированная последовательность запрос→ответ по stdio (аксиома
# read_byte), но с живыми диагностиками — didOpen/didChange/didClose →
# publishDiagnostics на лексической, синтаксической и типовой ошибке,
# при чистом разборе и после закрытия.
#
# Вход строится здесь (Python: обрамление Content-Length с CRLF, тела в
# UTF-8), чтобы в репозитории не жили CR-байты. Выход сервера
# нормализуется (CR срезается) и сверяется с tests/lsp/session.golden.
#
# Линковка — плоская склейка (модуль 0): фазы selfhost + плоский lib/json
# (build/JsonFlat.eat) + editor/lsp/. См. шапку Makefile (LSP_FILES).
set -euo pipefail

cd "$(dirname "$0")/../.."

# Запуск сервера — тот же editor/lsp/serve.sh, что зовёт клиент VSCode
# (единый источник команды и списка файлов; он же пересобирает JsonFlat).
GOLDEN=tests/lsp/session.golden
IN=$(mktemp)
OUT=$(mktemp)
trap 'rm -f "$IN" "$OUT"' EXIT

# Кадры JSON-RPC: Content-Length + CRLF + тело (UTF-8). Тексты
# документов несут по одной ошибке каждого рода (fail-fast: первая).
python3 - > "$IN" <<'PY'
import sys, json
def frame(obj):
    b = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(b) + b)
def did_open(uri, text, ver=1):
    frame({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
        "textDocument": {"uri": uri, "languageId": "eat",
                         "version": ver, "text": text}}})
frame({"jsonrpc": "2.0", "id": 1, "method": "initialize",
       "params": {"processId": None, "capabilities": {}}})
frame({"jsonrpc": "2.0", "method": "initialized", "params": {}})
# лексическая ошибка: незакрытая строка (2:15)
did_open("file:///t/lex.eat", 'func main() {\n    print("hi)\n}\n')
# синтаксическая ошибка: нет выражения (2:18)
did_open("file:///t/syn.eat", 'func main() {\n    let y: u32 = \n}\n')
# типовая ошибка: u32 = bool (2:5)
did_open("file:///t/typ.eat", 'func main() {\n    let x: u32 = true\n}\n')
# UTF-16: ошибка после 3 кириллических (6 байт) на строке → character 16
did_open("file:///t/utf.eat", 'func main() {\n    print("абв")x\n}\n')
# модуль с import-блоком: сервер без файловой аксиомы не резолвит модули,
# ложную ошибку границы (Check.eat «модуль не встретился») подавляем →
# пустой список (лексика/синтаксис такого файла всё равно проверены)
did_open("file:///t/mod.eat",
         'import {\n    NONE,\n} from "lib/core/Const.eat"\n\nfunc main() {\n    print("ok")\n}\n')
# чистый разбор: пустой список диагностик
did_open("file:///t/ok.eat", 'func main() {\n    let n: u32 = 7\n    print("{n}")\n}\n')
# go-to-definition (same-file): курсор на вызове helper → объявление
did_open("file:///t/def.eat",
         'func helper(x: u32) -> u32\n{\n    return x + 1\n}\n\nfunc main()\n{\n    print("{helper(3)}")\n}\n')
frame({"jsonrpc":"2.0","id":10,"method":"textDocument/definition","params":{
    "textDocument":{"uri":"file:///t/def.eat"},"position":{"line":7,"character":12}}})
# go-to-definition (кросс-файл): клиент шлёт синтетический модуль в корпус,
# затем клик по импортированному FOO → объявление в модуле
frame({"jsonrpc":"2.0","method":"eat/module","params":{
    "path":"t/dep.eat","uri":"file:///t/dep.eat",
    "text":"export {\n    FOO,\n}\n\nconstexpr FOO: u32 = 5\n"}})
did_open("file:///t/use.eat",
         'import {\n    FOO,\n} from "t/dep.eat"\n\nfunc main()\n{\n    let x: u32 = FOO\n    print("{x}")\n}\n')
frame({"jsonrpc":"2.0","id":11,"method":"textDocument/definition","params":{
    "textDocument":{"uri":"file:///t/use.eat"},"position":{"line":6,"character":17}}})
# кросс-файловая ДИАГНОСТИКА (1c): синтетический модуль-0 (rt0, пусто) +
# уже присланный t/dep.eat (FOO); открытый модульный файл с типовой ошибкой
# → реальная диагностика (а не ложная «модуль не встретился»). eat/order
# пересчитывает: сперва одиночный анализ (подавлен), затем модульный.
frame({"jsonrpc":"2.0","method":"eat/module","params":{
    "path":"rt0","uri":"file:///t/rt0","text":""}})
did_open("file:///t/diag.eat",
         'import {\n    FOO,\n} from "t/dep.eat"\n\nfunc main()\n{\n    let bad: bool = FOO\n}\n')
frame({"jsonrpc":"2.0","method":"eat/order","params":{
    "uri":"file:///t/diag.eat","paths":["rt0","t/dep.eat"]}})
# 1c для БИБЛИОТЕКИ (export, без main): Check бросил бы «нет функции main»
# до проверки тел — сервер дописывает синтетическую main, и типовая ошибка
# в теле функции всё же ловится (иначе lib-файлы без диагностики).
did_open("file:///t/lib.eat",
         'export {\n    g,\n}\n\nfunc g() -> u32\n{\n    let bad: bool = 5\n    return 1\n}\n')
frame({"jsonrpc":"2.0","method":"eat/order","params":{
    "uri":"file:///t/lib.eat","paths":["rt0"]}})
# didChange ok.eat → внести ошибку (полная синхронизация)
frame({"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
    "textDocument": {"uri": "file:///t/ok.eat", "version": 2},
    "contentChanges": [{"text": "func main() {\n    let b: bool = 5\n}\n"}]}})
# didClose ok.eat → снять подчёркивания
frame({"jsonrpc": "2.0", "method": "textDocument/didClose", "params": {
    "textDocument": {"uri": "file:///t/ok.eat"}}})
frame({"jsonrpc": "2.0", "id": 2, "method": "shutdown"})
frame({"jsonrpc": "2.0", "method": "exit"})
PY

bash editor/lsp/serve.sh < "$IN" 2>/dev/null | tr -d '\r' > "$OUT"

if diff -u "$GOLDEN" "$OUT"; then
    echo "verify_lsp: OK (сессия рукопожатие+диагностики == эталон)"
else
    echo "verify_lsp: FAIL — вывод сервера разошёлся с эталоном" >&2
    exit 1
fi
