#!/usr/bin/env bash
# editor/lsp/serve.sh — запуск LSP-сервера EATLang по stdio
# (docs/plans/LSP_PLAN.md, этап 1). Единый источник команды запуска:
# его зовёт клиент editor/vscode (по stdio) и сверка tests/lsp/verify.sh.
#
# Сервер линкуется ПЛОСКОЙ склейкой (модуль 0): фазы selfhost/ (без
# экспортов) + плоский lib/json (build/JsonFlat.eat, снятые import-блоки)
# + editor/lsp/. Импорт-блоки в потоке запрещены (нужны #module-границы
# драйвера), поэтому lib/json подаётся плоским. См. шапку Makefile.
#
# cwd приводится к корню репозитория: пути файлов — от него. Скрипт
# сперва пересобирает build/JsonFlat.eat (производный из Json.eat), затем
# exec'ит интерпретатор — stdin/stdout остаются каналом JSON-RPC.
set -euo pipefail

cd "$(dirname "$0")/../.."

# Маркер в stderr (канал логов LSP, не JSON-RPC): подтверждает, что
# сервер поднят именно этим скриптом (плоская склейка). Виден в VS Code:
# Output → EATLang LSP. Идёт ДО перенаправления — попадает в панель.
echo "serve.sh: LSP EATLang — плоская склейка фаз (cwd=$(pwd))" >&2

# Сборка НАТИВНОГО бинарника сервера (один раз; make пересобирает лишь при
# правке источников). Критично для скорости: интерпретатор `eatc run`
# анализирует замыкание модулей ~35 с на правку, бинарник — ~0,01 с. Вывод
# сборки — в лог (НЕ в stdout: там канал JSON-RPC). Первый запуск ждёт
# ~10 с сборки, дальше бинарник закеширован.
make build/eat-lsp >> build/lsp.log 2>&1 || {
    echo "serve.sh: сборка сервера не удалась — см. build/lsp.log" >&2
    exit 1
}

# stderr сервера (eprint компилятора: `err: …` при одиночном анализе до
# eat/order — шум, не провал) уводим в build/lsp.log, чтобы не засорять
# панель Output. Настоящие подчёркивания идут по JSON-RPC (stdout).
# Отладка сервера: tail -f build/lsp.log.
exec ./build/eat-lsp 2>> build/lsp.log
