/* Шим аксиом ОС для МК — общая часть всех плат (mcu/boards/…).
 * Зависимость от железа сведена к двум функциям платы:
 *   void board_init(void);        — включить UART и т.п.
 *   void board_putc(uint8_t b);   — байт в последовательный порт.
 *
 * Аксиомы (как в src/eatc/runtime.c, но поверх железа):
 *   - вывод и диагностика — board_putc: канал на МК один;
 *   - ввод — прошитый массив eat_input (у UART нет конца потока;
 *     живой ввод реального проекта — extern-драйвер поверх ISR);
 *   - exit/trap — полухостинг: QEMU завершает процесс с кодом
 *     программы, на железе без отладчика — вечная остановка. */

#include <stdint.h>

void board_putc(uint8_t b);

/* --- полухостинг (QEMU -semihosting) ------------------------------ */

#define SYS_EXIT_EXTENDED 0x20u
#define ADP_STOPPED_APPLICATION_EXIT 0x20026u

__attribute__((noreturn)) void semihost_exit(uint32_t code) {
    uint32_t block[2] = {ADP_STOPPED_APPLICATION_EXIT, code};
    register uint32_t r0 __asm__("r0") = SYS_EXIT_EXTENDED;
    register uint32_t *r1 __asm__("r1") = block;
    __asm__ volatile("bkpt 0xAB" : : "r"(r0), "r"(r1) : "memory");
    for (;;) {
    }
}

/* --- шесть аксиом --------------------------------------------------- */

__attribute__((weak)) const uint8_t eat_input[1] = {0};
__attribute__((weak)) const uint32_t eat_input_len = 0;

int32_t eat_read_byte(void) {
    static uint32_t pos = 0;
    if (pos >= eat_input_len) {
        return -1;
    }
    return eat_input[pos++];
}

void eat_write_byte(char b) {
    board_putc((uint8_t)b);
}

void eat_write_span(const uint8_t *p, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) {
        board_putc(p[i]);
    }
}

void eat_write_err_byte(char b) {
    board_putc((uint8_t)b);
}

void eat_exit(uint32_t code) {
    semihost_exit(code);
}

/* Trap-сообщения ограничивает компилятор; страховочная граница —
 * правило 2 Power of 10 и для шима. */
void eat_trap(const char *msg) {
    for (uint32_t i = 0; msg[i] != 0 && i < 512; i++) {
        board_putc((uint8_t)msg[i]);
    }
    board_putc('\n');
    semihost_exit(1);
}

/* Режим trap-кодов (--trap-codes): в прошивке — число, таблица
 * кодов остаётся в .trapmap рядом с .ll на хосте. */
void eat_trap_code(uint32_t code) {
    static const char prefix[] = "trap ";
    for (uint32_t i = 0; prefix[i] != 0; i++) {
        board_putc((uint8_t)prefix[i]);
    }
    char digits[10];
    uint32_t n = 0;
    do {
        digits[n++] = (char)('0' + code % 10);
        code /= 10;
    } while (code != 0 && n < 10);
    while (n > 0) {
        board_putc((uint8_t)digits[--n]);
    }
    board_putc('\n');
    semihost_exit(1);
}
