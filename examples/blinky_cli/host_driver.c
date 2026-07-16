/* Хостовый драйвер-эталон extern-границы mcu/Mcu.eat: та же
 * семантика, что у шима плат (mcu/common/shim.c), — вывод blinky_cli
 * на хосте совпадает с QEMU байт-в-байт и служит эталоном автосверки
 * (make verify_mcu). */

#include <stdbool.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>

/* GPIO хоста нет — зеркало в статике, кнопка всегда отпущена
 * (как у QEMU-плат: их GPIO эмулятор не моделирует). */
static bool gpio_lines[2];

void gpio_set(uint32_t line, bool on) {
    gpio_lines[line & 1u] = on;
}

bool gpio_get(uint32_t line) {
    return gpio_lines[line & 1u];
}

/* как на плате — миллисекунды от старта программы */
uint64_t systick_ms(void) {
    static uint64_t start;
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    uint64_t now =
        (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
    if (start == 0) {
        start = now;
    }
    return now - start;
}

/* stdin вместо UART; конец потока — сентинел 256 «байта нет»
 * (контракт mcu/Mcu.eat), как замолчавший порт. */
uint32_t uart_poll(void) {
    uint8_t b;
    if (read(0, &b, 1) == 1) {
        return b;
    }
    return 256u;
}
