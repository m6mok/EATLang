# AGENTS.md — инструкции для агентов

EATLang — учебно-исследовательский язык: компилируемый (LLVM),
статически типизируемый, **тотальный** (каждая программа доказуемо
завершается), с 10 правилами NASA (Power of 10), зашитыми в сам язык.
Проект самохостится: компилятор написан на EATLang и собирает сам себя;
Python-бутстрап (`src/eatc/`) — эталон, с которым всё сверяется
байт-в-байт.

## Документация (читать по задаче)

| Документ | Когда читать |
| --- | --- |
| [docs/PROCESSES.md](docs/PROCESSES.md) | **сначала** — конвейер компиляции, два компилятора, команды CLI и make, процессы проверки |
| [docs/MODIFYING.md](docs/MODIFYING.md) | перед **любой** правкой компилятора/языка — инварианты, порядок работ, кодировки, чеклисты |
| [docs/POWER_OF_10.md](docs/POWER_OF_10.md) | правила Power of 10: как каждое воплощено, где проверяется, что нельзя открыть правкой |
| [SPEC.md](SPEC.md) | формальная спецификация: EBNF, семантика, пределы §6, встроенные §7 |
| [docs/GUIDE.md](docs/GUIDE.md) | как писать на языке: синтаксис, контракты, что не скомпилируется |
| [docs/SELFHOST.md](docs/SELFHOST.md) | архитектура self-hosted компилятора, фазы 1–6 |
| [docs/VERIFICATION_PLAN.md](docs/VERIFICATION_PLAN.md) | статический верификатор: каталог кейсов `tests/verify/` |
| [docs/TRACKS.md](docs/TRACKS.md) | треки работ: производительность, МК, язык — что дальше и почему |

## Главные правила

1. **Любая правка языка в `src/eatc/` зеркалится в `selfhost/*.eat`.**
   Паритет байт-в-байт: дампы, тексты ошибок, trap-сообщения, IR.
   Порядок работ и кодировки — в [docs/MODIFYING.md](docs/MODIFYING.md).
2. **Изменения синтаксиса/семантики/встроенных — только с решением
   пользователя.** Не хватает конструкции — остановись и сообщи.
3. **Определение готовности**:
   `make check verify verify_suite verify_selfhost verify_bootstrap
   verify_trapcodes verify_sig`
   проходит целиком. Частично зелёное не коммитится.
4. **Не открывать обходов Power of 10**: ни кучи, ни рекурсии,
   ни цикла без границы, ни глобалов, ни молча отброшенного результата
   ([docs/POWER_OF_10.md](docs/POWER_OF_10.md)).
5. Документация и комментарии в репозитории — **на русском**;
   коммиты — в стиле истории (`git log --oneline`).

## Быстрый старт

```sh
uv sync              # окружение (единственная зависимость — llvmlite);
                     # для линковки бинарников нужен clang
make check           # компиляция примеров: парсинг, Power of 10, типы, тесты
make verify          # бинарники == интерпретатор на всех примерах
make verify_selfhost # self-hosted компилятор против эталона на всех .eat
make verify_bootstrap# фикспойнт: компилятор собирает сам себя
make verify_trapcodes# режим trap-кодов (МК): SelfIrCodes == eatc ir --trap-codes
make verify_sig      # интерфейс lib/ == снапшот tests/sig/lib.sig
```

CLI компилятора: `PYTHONPATH=src uv run python -m eatc
{check|run|build|lex|parse|sig|typed|ir}` (в Makefile — `$(EATC)`).

## Карта репозитория

```text
src/eatc/     Python-бутстрап (эталон): lexer → parser → checks →
              typechecker → interpreter → verifier → codegen; runtime.c —
              шим шести аксиом ОС (семь функций)
selfhost/     компилятор на EATLang: Tok, Lexer, Ast, Parser, Check, Ir,
              *Main; Rt.eat — рантайм, первый модуль каждой программы
lib/          библиотека на EATLang (Ascii, Buf, Const, Fmt, Hex, Io, Num, Parse) —
              подключается списком файлов после Rt.eat
              (docs/MODULES_PLAN.md, этап 0 — конкатенация)
examples/     эталонные примеры (all — витрина конструкций; mos6502 —
              эмулятор; lexer — проба self-host)
tests/        verify/ (кейсы верификатора), lex|parse|ir/ (стресс дампов),
              bench/ (нагрузка), verify_suite.py
docs/         процессы, руководства, планы (см. таблицу выше)
```
