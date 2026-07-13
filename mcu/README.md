# mcu/ — порты EATLang на микроконтроллеры (трек 2)

Логика — на EATLang со всеми гарантиями (тотальность, Power of 10,
отчёт §8), железо — за узкой границей: шесть аксиом ОС поверх UART
платы плюс `extern func` для периферии проекта
([docs/MCU_PLAN.md](../docs/MCU_PLAN.md)).

## Сборка и сверка

```sh
brew install lld qemu      # ld.lld (ELF) и qemu-system-arm

make mcu BOARD=microbit SRC="selfhost/Rt.eat App.eat" \
    [EXTERN="drv.c"] [INPUT=data.bin]     # прошивка build/mcu/<board>/App.elf
make mcu_run BOARD=… SRC=…                # запуск в QEMU
make verify_mcu                           # все QEMU-платы, байт-в-байт
```

Каждая сборка печатает отчёт §8 и сверяет `стек + .data + .bss`
с RAM платы — переполнение валит сборку, а не устройство
(`mcu/common/check_mem.py`).

## Структура

- `common/runtime.c` — шим шести аксиом поверх `board_putc`/`board_init`;
  вход — прошитый массив (`common/embed_input.py`: у UART нет EOF,
  живой ввод — extern-драйвер); exit/trap — полухостинг (QEMU
  завершает процесс с кодом программы);
- `common/startup.c` — вектора, `.data`/`.bss`, вызов main;
  EABI-хелперы памяти и программное деление для Cortex-M0 (thumbv6m
  без аппаратного udiv);
- `common/eabi64.c` — 64-битные EABI-хелперы (u64/i64 в языке):
  `__aeabi_uldivmod`/`ldivmod` на всех thumb-целях, `lmul`/`llsl`/
  `llsr`/`lasr` для v6-M, плюс знаковое 32-битное деление
  (`__aeabi_idiv(mod)`); готового libclang_rt.builtins.a под
  baremetal-arm в тулчейне macOS нет — хелперы свои;
- `common/sections.ld` — общая раскладка секций (`.ARM.exidx`
  отброшен: исключений нет);
- `boards/<board>/` — `board.c` (UART чипа), `board.ld` (память),
  `board.mk` (`--target`, `-mcpu`, размер RAM, QEMU-машина).

## Платы

| BOARD | Чип (ядро) | RAM | Проверка |
| --- | --- | --- | --- |
| `mps2_an385` | ARM MPS2 (Cortex-M3) | 4 МБ | QEMU, в `verify_mcu` |
| `microbit` | nRF51822 (Cortex-M0) | 16 КБ | QEMU, в `verify_mcu` |
| `stm32vldiscovery` | STM32F100 (Cortex-M3) | 8 КБ | QEMU, в `verify_mcu` |
| `netduinoplus2` | STM32F405 (Cortex-M4) | 128 КБ | QEMU, в `verify_mcu` |

`verify_mcu`: mos6502 (262 КБ стека по §8) сверяется с интерпретатором
на mps2-an385 — на остальные платы он честно не влезает и автосверка
§8 это ловит; extern-пример `examples/extern/Blinky.eat` гоняется на
**всех** платах и сверяется байт-в-байт с хостовым бинарником
(интерпретатор extern не исполняет — эталон в этом случае хост).

## Числа (2026-07-14)

- Blinky (extern, суперцикл): **2054 Б** `.text`, RAM 280 Б
  (стек §8 272 + .bss 8) — влезает даже в 8 КБ STM32F100.
- Mos6502 (эмулятор, 64К памяти гостя): 6.4 КБ `.text`,
  262 598 Б RAM — только mps2-an385 (4 МБ).
- LTO на коде программы: −32 % флеша, линковка мгновенная; шим —
  нативный объект (`__aeabi_*` рождаются при LTO-кодогенерации).

## Как добавить плату

1. `mcu/boards/<имя>/board.c` — `board_init()` и `board_putc(b)`
   поверх UART чипа (≈20 строк C);
2. `board.ld` — `MEMORY { FLASH …, RAM … }` + `INCLUDE
   mcu/common/sections.ld`;
3. `board.mk` — `ARCH_FLAGS`, `RAM_SIZE`, `QEMU_MACHINE` (если есть)
   или команда прошивки.

На реальном железе полухостинг (`bkpt 0xAB`) без отладчика уходит в
вечный цикл — замените выход на сброс по месту; UART реальных плат
требует клоков/GPIO (см. комментарии в board.c).

## Ограничения

- Плата = один последовательный канал: stderr не отделён от stdout.
- Прошитый вход только для batch-сверки; интерактив — extern поверх
  ISR-кольца драйвера (см. examples/extern/).
- Прерывания живут в C-драйверах; EATLang-суперцикл однопоточен —
  это осознанная архитектура (MCU_PLAN §2).
