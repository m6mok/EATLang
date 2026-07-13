/* Шим EATLang для микроконтроллера: ARM Cortex-M3, плата QEMU
 * mps2-an385 (трек 2 TRACKS.md). Те же шесть аксиом ОС, что в
 * src/eatc/runtime.c, но поверх железа вместо libc:
 *
 *   - вывод (write_byte / write_span / write_err_byte) — CMSDK UART0;
 *     канал диагностики на МК не отделён от полезного вывода:
 *     последовательный порт один;
 *   - ввод (read_byte) — прошитый в образ массив eat_input: у UART
 *     нет понятия «конец потока», поэтому вход программы (ROM для
 *     эмулятора 6502) зашивается в прошивку на этапе сборки
 *     (mcu/embed_input.py);
 *   - выход и trap — полухостинг SYS_EXIT_EXTENDED: QEMU завершает
 *     процесс с кодом программы (флаг -semihosting); на реальном
 *     железе bkpt останавливает ядро под отладчиком.
 *
 * Здесь же стартап (таблица векторов, reset: .data/.bss, main) и
 * EABI-хелперы памяти, которые LLVM генерирует для freestanding-цели.
 */

#include <stddef.h>
#include <stdint.h>

/* --- CMSDK APB UART0 платы mps2-an385 --------------------------- */

#define UART0_BASE 0x40004000u
#define UART_DATA (*(volatile uint32_t *)(UART0_BASE + 0x00))
#define UART_STATE (*(volatile uint32_t *)(UART0_BASE + 0x04))
#define UART_CTRL (*(volatile uint32_t *)(UART0_BASE + 0x08))

#define UART_STATE_TX_FULL 1u
#define UART_CTRL_TX_EN 1u
#define UART_CTRL_RX_EN 2u

/* Ожидание свободного TX-буфера ограничено только скоростью UART:
 * это единственная «граница», которую даёт железо (в QEMU буфер
 * не заполняется никогда). */
static void uart_put(uint8_t b) {
    while (UART_STATE & UART_STATE_TX_FULL) {
    }
    UART_DATA = b;
}

/* --- Полухостинг (ARM semihosting, QEMU -semihosting) ------------ */

#define SYS_EXIT_EXTENDED 0x20u
#define ADP_STOPPED_APPLICATION_EXIT 0x20026u

__attribute__((noreturn)) static void semihost_exit(uint32_t code) {
    uint32_t block[2] = {ADP_STOPPED_APPLICATION_EXIT, code};
    register uint32_t r0 __asm__("r0") = SYS_EXIT_EXTENDED;
    register uint32_t *r1 __asm__("r1") = block;
    __asm__ volatile("bkpt 0xAB" : : "r"(r0), "r"(r1) : "memory");
    for (;;) { /* на железе без отладчика — вечная остановка */
    }
}

/* --- Шесть аксиом ОС --------------------------------------------- */

/* Вход программы: массив, прошитый в образ (mcu/embed_input.py
 * генерирует сильные определения); слабые умолчания — пустой вход,
 * первый же read_byte отвечает Err(Eof). */
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
    uart_put((uint8_t)b);
}

void eat_write_span(const uint8_t *p, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) {
        uart_put(p[i]);
    }
}

void eat_write_err_byte(char b) {
    uart_put((uint8_t)b);
}

void eat_exit(uint32_t code) {
    semihost_exit(code);
}

/* Trap-сообщения компилятор ограничивает сам; страховочная граница
 * цикла — правило 2 Power of 10 и для шима. */
void eat_trap(const char *msg) {
    for (uint32_t i = 0; msg[i] != 0 && i < 512; i++) {
        uart_put((uint8_t)msg[i]);
    }
    uart_put('\n');
    semihost_exit(1);
}

/* Режим trap-кодов (--trap-codes): в прошивке — только число,
 * таблица кодов остаётся в .trapmap рядом с .ll на хосте. */
void eat_trap_code(uint32_t code) {
    static const char prefix[] = "trap ";
    for (uint32_t i = 0; prefix[i] != 0; i++) {
        uart_put((uint8_t)prefix[i]);
    }
    char digits[10];
    uint32_t n = 0;
    do {
        digits[n++] = (char)('0' + code % 10);
        code /= 10;
    } while (code != 0 && n < 10);
    while (n > 0) {
        uart_put((uint8_t)digits[--n]);
    }
    uart_put('\n');
    semihost_exit(1);
}

/* --- EABI-хелперы памяти ------------------------------------------ */
/* LLVM для freestanding-цели зовёт __aeabi_*: копирование агрегатов
 * (str — 260 байт) и обнуление кадров. Побайтные реализации —
 * простота важнее скорости демонстрации. */

void *memcpy(void *dst, const void *src, size_t n) {
    uint8_t *d = dst;
    const uint8_t *s = src;
    for (size_t i = 0; i < n; i++) {
        d[i] = s[i];
    }
    return dst;
}

void *memset(void *dst, int value, size_t n) {
    uint8_t *d = dst;
    for (size_t i = 0; i < n; i++) {
        d[i] = (uint8_t)value;
    }
    return dst;
}

void __aeabi_memcpy(void *dst, const void *src, size_t n) {
    memcpy(dst, src, n);
}

void __aeabi_memcpy4(void *dst, const void *src, size_t n) {
    memcpy(dst, src, n);
}

void __aeabi_memcpy8(void *dst, const void *src, size_t n) {
    memcpy(dst, src, n);
}

void __aeabi_memclr(void *dst, size_t n) {
    memset(dst, 0, n);
}

void __aeabi_memclr4(void *dst, size_t n) {
    memset(dst, 0, n);
}

void __aeabi_memclr8(void *dst, size_t n) {
    memset(dst, 0, n);
}

void __aeabi_memset(void *dst, size_t n, int value) {
    memset(dst, value, n);
}

/* --- Стартап ------------------------------------------------------ */

extern uint32_t __data_load[], __data_start[], __data_end[];
extern uint32_t __bss_start[], __bss_end[];
extern uint32_t __stack_top[];

int main(void);

/* Reset: перенос .data из образа, обнуление .bss, включение UART,
 * main, штатный выход с его кодом (программы EATLang без exit
 * возвращают 0). */
__attribute__((noreturn)) void reset_handler(void) {
    for (uint32_t *load = __data_load, *dst = __data_start;
         dst < __data_end; load++, dst++) {
        *dst = *load;
    }
    for (uint32_t *dst = __bss_start; dst < __bss_end; dst++) {
        *dst = 0;
    }
    UART_CTRL = UART_CTRL_TX_EN | UART_CTRL_RX_EN;
    semihost_exit((uint32_t)main());
}

/* Таблица векторов Cortex-M: [0] — вершина стека, [1] — Reset.
 * Остальные обработчики не нужны: программы EATLang однопоточны,
 * прерывания не включаются. */
__attribute__((section(".vectors"), used)) static void *const vectors[2] = {
    (void *)__stack_top,
    (void *)reset_handler,
};
