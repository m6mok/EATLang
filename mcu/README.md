# mcu/ — порты EATLang на микроконтроллеры (трек 2)

Логика — на EATLang со всеми гарантиями (тотальность, Power of 10,
отчёт §8), железо — за узкой границей: шесть аксиом ОС поверх UART
платы плюс `extern func` для периферии проекта
([docs/plans/MCU_PLAN.md](../docs/plans/MCU_PLAN.md)).

## Сборка и сверка

```sh
brew install lld qemu llvm # ld.lld, qemu-system-arm, llvm-objcopy

make mcu BOARD=microbit SRC="selfhost/Rt.eat App.eat" \
    [EXTERN="drv.c"] [INPUT=data.bin]     # прошивка build/mcu/<board>/App.elf
make mcu_run BOARD=… SRC=…                # запуск в QEMU
make mcu_flash BOARD=pico SRC=…           # прошивка реальной платы
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
- `common/shim.c` — периферийный шим §6 (`gpio_set`/`gpio_get`/
  `systick_ms`/`uart_poll`) поверх хуков платы + кольцо SPSC для
  ISR-приёма; EATLang-граница с контрактами — [Mcu.eat](Mcu.eat);
- `boards/<board>/` — `board.c` (UART и периферия чипа, хуки шима),
  `board.ld` (память), `board.mk` (`--target`, `-mcpu`, размер RAM,
  QEMU-машина или команда прошивки `FLASH_CMD`).

## Периферийный шим (MCU_PLAN §6)

Граница с железом — extern-функции (решение §1.1), объявленные в
[mcu/Mcu.eat](Mcu.eat): `gpio_set(line, on)` / `gpio_get(line)`
(линии логические: 0 — LED, 1 — кнопка; плата отображает на свои
пины), `systick_ms()` (u64, мс от старта, 24-битный SysTick с
накоплением), `uart_poll()` (байт или сентинел 256; обёртка
`poll_byte()` возвращает `Option<u8>`). Прерывания — деталь драйвера
(§2): полная таблица векторов в `common/startup.c` зовёт `board_irq`,
ISR платы кладёт байты в кольцо `shim_ring_put`, суперцикл забирает
их через `uart_poll`. QEMU-платы обходятся опросом RX-регистра —
эмулятор придерживает байты сам.

## Платы

QEMU-проверяемые (в `verify_mcu`, сверка байт-в-байт):

| BOARD | Чип (ядро) | RAM | Периферия |
| --- | --- | --- | --- |
| `mps2_an385` | ARM MPS2 (Cortex-M3) | 4 МБ | UART RX опросом, GPIO — зеркало |
| `microbit` | nRF51822 (Cortex-M0) | 16 КБ | UART RX опросом, GPIO — зеркало |
| `stm32vldiscovery` | STM32F100 (Cortex-M3) | 8 КБ | UART RX опросом, GPIO — зеркало |
| `netduinoplus2` | STM32F405 (Cortex-M4) | 128 КБ | UART RX опросом, GPIO — зеркало |

Прошивочные (в `verify_mcu` — сборка + автосверка §8; проверка на
железе — у пользователя, `make mcu_flash BOARD=…`):

| BOARD | Чип (ядро) | RAM | Прошивка | LED / кнопка |
| --- | --- | --- | --- | --- |
| `pico` | RP2040 (M0+) | 264 КБ | `.uf2`: picotool или BOOTSEL-диск | GP25 / GP14→GND |
| `bluepill` | STM32F103C8 (M3) | 20 КБ | `.bin`: st-flash / OpenOCD | PC13 / PA0→GND |
| `f4discovery` | STM32F407VG (M4) | 128 КБ | `.bin`: st-flash / OpenOCD | PD12 / PA0 (USER) |
| `nrf52840dk` | nRF52840 (M4) | 256 КБ | `.hex`: nrfjprog / OpenOCD; Dongle — nrfutil dfu | P0.13 / P0.11 |

У прошивочных портов UART-приём идёт по прерыванию в кольцо шима
(ISR → SPSC → `uart_poll`, MCU_PLAN §2); pico стартует через свой
`boot2.S` (XIP по команде 03h), CRC блока и UF2 делает
`boards/pico/elf2uf2.py`. Клоки не разгоняются (HSI/XOSC без PLL):
меньше точек отказа, для 115200 бод и суперцикла хватает.

`verify_mcu`: mos6502 (262 КБ стека по §8) сверяется с интерпретатором
на mps2-an385 — на остальные платы он честно не влезает и автосверка
§8 это ловит; extern-пример `examples/extern/Blinky.eat` и флагман
[examples/blinky_cli/](../examples/blinky_cli/README.md) гоняются на
**всех** QEMU-платах и сверяются байт-в-байт с хостовым бинарником
(интерпретатор extern не исполняет — эталон в этом случае хост);
прошивочные порты собирают blinky_cli с проверкой §8.

## Числа (2026-07-14; blinky_cli — 2026-07-16)

- Blinky (extern, суперцикл): **2054 Б** `.text`, RAM 280 Б
  (стек §8 272 + .bss 8) — влезает даже в 8 КБ STM32F100.
- blinky_cli (флагман §6: мигание + кнопка + UART-CLI, u64-время):
  7.5–8.4 КБ `.text` по платам, RAM ~1.5 КБ (стек §8 1360 + .bss
  ~100) — шестикратный запас даже на 8 КБ F100; латентность такта
  суперцикла в QEMU ~1.07 мкс (M3) / ~1.7 мкс (M0) — подробности в
  tests/bench/FINDINGS.md, итерация 34.
- Mos6502 (эмулятор, 64К памяти гостя): 6.4 КБ `.text`,
  262 598 Б RAM — только mps2-an385 (4 МБ).
- LTO на коде программы: −32 % флеша, линковка мгновенная; шим —
  нативный объект (`__aeabi_*` рождаются при LTO-кодогенерации).

## Цена проверок во флеше (2026-07-14)

Сколько статический верификатор экономит на МК: тот же `.ll`
собран дважды — с верификатором (снятие доказанных проверок) и без
(все проверки остаются), оба `--trap-codes`, компиляция под
Cortex-M3, сверка `.text` (`llvm-size`).

| mos6502, Cortex-M3 | trap-сайтов | `.text` |
| --- | --- | --- |
| все проверки | 322 | 6156 Б |
| верификатор (доказанные сняты) | 61 | 5624 Б |
| **экономия** | **−81 %** | **−532 Б (−8.6 %)** |

Цена сайта мала (~2 Б: `cmp; bcs`) — холодные trap-блоки LLVM сливает
в общий хвост `eat_trap_code`. В режиме trap-строк экономия больше
(снятый trap уносит и строку из `__const`), но МК идёт в trap-кодах.
Проверки рантайм-нейтральны на суперскаляре (десктоп), но стоят флеша
на МК — верификатор здесь инструмент размера, а не хостовой скорости.

## Цена проверок в тактах (2026-07-19)

Тот же mos6502 (`mul13x11.rom`, 65 шагов 6502) под `qemu-system-arm -M
mps2-an385` с TCG insn-плагином (`-plugin … -d plugin`) — детерминиро­
ванный счётчик исполненных инструкций, дважды (все проверки / доказан­
ные сняты). Энейблер — образ `eatlang-dev:etap1`; запуск `make
measure_mcu` (`containers/run-measure.sh`).

| mos6502, Cortex-M3 | insns | `.text` |
| --- | --- | --- |
| все проверки | 653 409 | 8970 Б |
| доказанные сняты | 653 062 | 8738 Б |
| **разница** | **−347 (−0.053 %)** | **−232 Б** |

Δ = 347 инстр / 65 шагов ≈ **5.3 инстр/шаг** (масштабируется входом
линейно; крошечный ROM разбавляет долю стартапом/печатью). Даже на
in-order M3 снятые проверки стоят ~0.05 % тактов — ценность
верификатора на МК подтверждённо **флеш**, а не такты.

Воспроизведение (эмиссия обоих `.ll` — `verify()` до `compile_binary`
даёт «доказанные сняты», без него — «все проверки»):

```sh
# оба .ll: PYTHONPATH=src, compile_binary(..., trap_codes=True, link=False)
clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -O2 -ffreestanding \
      -fno-unwind-tables -c prog.ll -o prog.o && llvm-size prog.o
```

## Как добавить плату

1. `mcu/boards/<имя>/board.c` — `board_init()` и `board_putc(b)`
   поверх UART чипа плюс хуки шима §6: `board_clock_hz` (клок ядра
   для SysTick), `board_gpio_set/get` (отображение логических линий
   на пины), `board_uart_poll` (опрос RX или `shim_ring_get` +
   `board_irq` с ISR-приёмом);
2. `board.ld` — `MEMORY { FLASH …, RAM … }` + `INCLUDE
   mcu/common/sections.ld`;
3. `board.mk` — `ARCH_FLAGS`, `RAM_SIZE`, `QEMU_MACHINE` (если есть)
   или `FLASH_CMD` (+ при надобности `MCU_POST` для .bin/.hex/.uf2 и
   `BOARD_EXTRA` для доп. исходников вроде boot2).

На реальном железе полухостинг (`bkpt 0xAB`) без отладчика уходит в
вечный цикл — замените выход на сброс по месту; UART реальных плат
требует клоков/GPIO (см. комментарии в board.c).

## Ограничения

- Плата = один последовательный канал: stderr не отделён от stdout.
- Прошитый вход только для batch-сверки; интерактив — extern поверх
  ISR-кольца драйвера (см. examples/extern/).
- Прерывания живут в C-драйверах; EATLang-суперцикл однопоточен —
  это осознанная архитектура (MCU_PLAN §2).
