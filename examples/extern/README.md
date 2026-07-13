# extern: граница с C на живом примере

`Blinky.eat` — логика на EATLang (суперцикл, счёт нажатий),
драйверы за границей `extern func`:

- `host_driver.c` — хостовая заглушка (кнопка детерминирована,
  задержка no-op): пример собирается обычным бинарником;
- `mcu_driver.c` — тот же контракт для любой платы mcu/boards/
  (вывод через аксиому `eat_write_byte` — UART платы).

Вывод обоих миров совпадает байт-в-байт — это и есть сверка
`make verify_mcu` (интерпретатор extern не исполняет, эталоном
служит хостовый бинарник):

```sh
# хост
make binary SRC="selfhost/Rt.eat examples/extern/Blinky.eat" \
    EXTERN=examples/extern/host_driver.c && ./build/Blinky

# любая плата из mcu/boards/
make mcu_run BOARD=microbit \
    SRC="selfhost/Rt.eat examples/extern/Blinky.eat" \
    EXTERN=examples/extern/mcu_driver.c
```

Контракты работают через границу: `requires ms <= 1000` у
`delay_ms` проверяется у вызывающего (или доказывается статически),
`ensures` extern-функции — на вере, как у аксиом ОС (SPEC §7).
