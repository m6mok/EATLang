# Кросс-языковое сравнение производительности

План и решения — [docs/plans/CROSSLANG_BENCH_PLAN.md](../../../docs/plans/CROSSLANG_BENCH_PLAN.md);
результаты и выводы — [tests/bench/CROSSLANG.md](../CROSSLANG.md).

```sh
make bench_crosslang                 # полный прогон
uv run python tests/bench/crosslang/run.py --quick --only arith,mos6502
```

Ручная цель, не гейт: требует `clang`, `rustc` и `go` на машине.
Артефакты — в `build/bench/crosslang/`.

## Устройство

- `run.py` — раннер: сборка всех вариантов, дифференциальная сверка
  stdout байт-в-байт, замер медианой из N прогонов; счётчики
  процессора (instructions retired, cycles → IPC, инстр/оп) и пиковый
  RSS — через `/usr/bin/time -l`.
- `c/ rust/ go/ py/` — порты бенчмарк-программ 1:1 (без идиоматических
  ускорений; та же структура, типы, границы). Маркер
  `REPEAT = 1` подменяется раннером, как в `bench.py`.
- `gen6502.py` — генератор нагрузочного ROM макробенча (эмулятор
  `examples/mos6502/`): вложенные счётчики 6502 с бегущей контрольной
  суммой, размер — параметрами `--top/--outer/--middle`.

## Варианты (оси «налог на безопасность»)

| Вариант | Что это |
| --- | --- |
| EATLang build | штатный `eatc build`: доказанные верификатором проверки сняты |
| EATLang все-trap | канонический IR (`eatc ir`, все trap'ы) + `clang -O2` + runtime.c |
| EATLang selfhost -O | `build/SelfIrOpt` (компилятор на EATLang, ось `-O`) + `clang -O2`; пропускается, если бинарник не собран |
| C -O2 / UBSan | без проверок / `-fsanitize=undefined,bounds` |
| Rust safe / unchecked | обычная индексация / `get_unchecked` (файл `*_unchecked.rs`, только где есть массивы) |
| Go / -gcflags=-B | проверки границ / снятые bounds-check |
| Python 3.11 | CPython, одна точка (старт интерпретатора вычитается) |

Сверка: каждый вариант обязан выдать stdout байт-в-байт равный
EATLang-бинарнику — на едином REPEAT=2 (микро) или лёгких ROM
(макро: `mul13x11.rom` + `rom_verify`). Провал сверки исключает
вариант из замера и красит прогон.
