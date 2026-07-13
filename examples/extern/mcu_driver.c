/* МК-драйвер той же границы: работает на любой плате mcu/boards/ —
 * вывод идёт через аксиому eat_write_byte (UART платы). Кнопка
 * детерминирована как в host_driver.c: QEMU-вывод сверяется с
 * хостовым бинарником байт-в-байт. На реальной плате замените
 * led_set/button_pressed на GPIO своего чипа. */

#include <stdbool.h>
#include <stdint.h>

void eat_write_byte(char b);

static void say(const char *s) {
    for (; *s != 0; s++) {
        eat_write_byte(*s);
    }
}

void led_set(bool on) {
    say(on ? "LED on\n" : "LED off\n");
}

void delay_ms(uint32_t ms) {
    /* Занятая пауза: на такт цикла хватает; SysTick не нужен для
     * детерминированного вывода. */
    for (volatile uint32_t i = 0; i < ms * 100; i++) {
    }
}

bool button_pressed(void) {
    static uint32_t n = 0;
    n++;
    return n % 3 == 0;
}
