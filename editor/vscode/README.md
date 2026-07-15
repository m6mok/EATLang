# EATLang для VS Code

Подсветка синтаксиса языка EAT (файлы `.eat`): ключевые слова, контракты
(`requires`/`ensures`/`assert`), модули (`import`/`export`/`from`/`as`,
`extern`), типы (`u8`..`u64`, `i32`/`i64`, `Result`/`Option`), встроенные
функции и аксиомы, битовые операторы, hex-литералы `0x…`, строки с
интерполяцией `{expr}`, char-литералы, комментарии `#`.

## Установка (локально, без сборки)

Симлинк в каталог расширений VS Code и перезагрузка окна:

```sh
ln -s "$(pwd)/editor/vscode" ~/.vscode/extensions/eatlang.eatlang-0.0.1
```

Затем в VS Code: `Cmd+Shift+P` → «Developer: Reload Window».

## Сборка .vsix (опционально)

```sh
npx @vscode/vsce package
code --install-extension eatlang-0.0.1.vsix
```
