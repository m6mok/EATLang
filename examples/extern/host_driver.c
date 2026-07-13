/* Хостовая заглушка драйвера: та же граница, что на МК.
 * Вывод — через аксиому eat_write_byte (общий буфер stdout с
 * программой, порядок строк сохраняется). Кнопка детерминирована
 * (каждое третье чтение), задержка — no-op: вывод сверяем байт-в-байт
 * с МК-драйвером. */

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
    (void)ms; /* на хосте время не тянем — вывод детерминирован */
}

bool button_pressed(void) {
    static uint32_t n = 0;
    n++;
    return n % 3 == 0;
}
