# EATLang для VS Code

Расширение даёт **подсветку синтаксиса** и **языковой сервер (LSP)** для
языка EAT (файлы `.eat`).

Подсветка (декларативная, работает всегда): ключевые слова, контракты
(`requires`/`ensures`/`assert`), модули (`import`/`export`/`from`/`as`,
`extern`), типы (`u8`..`u64`, `i32`/`i64`, `Result`/`Option`), встроенные
функции и аксиомы, битовые операторы, hex-литералы `0x…`, строки с
интерполяцией `{expr}`, char-литералы, комментарии `#`.

Языковой сервер написан **на самом EATLang** (`editor/lsp/`,
[docs/plans/LSP_PLAN.md](../../docs/plans/LSP_PLAN.md)) и общается с
редактором по JSON-RPC поверх stdio. Этап 0 — рукопожатие
(`initialize`/`shutdown`/`exit`); диагностики, verifier-inlays, hover,
автодополнение и CodeLens бюджета памяти — следующие этапы.

## Установка

Подсветка работает без всякой сборки — симлинк в каталог расширений и
перезагрузка окна:

```sh
ln -s "$(pwd)/editor/vscode" ~/.vscode/extensions/eatlang.eatlang-0.1.0
```

Затем в VS Code: `Cmd+Shift+P` → «Developer: Reload Window».

## Включить языковой сервер

Серверу нужна одна npm-зависимость (`vscode-languageclient`); TS-сборки
нет — точка входа `extension.js` на чистом JavaScript.

```sh
cd editor/vscode
npm install
```

Перезагрузите окно. При открытии `.eat` расширение запускает сервер
командой из настроек `eatlang.server.command` / `eatlang.server.args`
(по умолчанию `uv run python -m eatc run --lib . editor/lsp/LspMain.eat`).

Требования этапа 0:

- воркспейс открыт на **корне репозитория EATLang** (сервер грузит
  `editor/lsp/` и `lib/` путями относительно корня);
- в `PATH` есть `uv`, окружение синхронизировано (`uv sync`).

Если `vscode-languageclient` не установлен, расширение это сообщит и
продолжит работать в режиме одной подсветки.

## Проверка сервера без редактора

Сервер тестируется транскриптом рукопожатия из корня репозитория:

```sh
make verify_lsp
```

## Сборка .vsix (опционально)

```sh
cd editor/vscode
npm install
npx @vscode/vsce package
code --install-extension eatlang-0.1.0.vsix
```
