/* Стартап Cortex-M, общий для всех плат: таблица векторов, перенос
 * .data, обнуление .bss, инициализация платы, main, штатный выход.
 * Здесь же EABI-хелперы памяти: LLVM зовёт их на freestanding-цели
 * (копирование агрегатов — str 260 байт, обнуление кадров). */

#include <stddef.h>
#include <stdint.h>

extern uint32_t __data_load[], __data_start[], __data_end[];
extern uint32_t __bss_start[], __bss_end[];
extern uint32_t __stack_top[];

void board_init(void);
__attribute__((noreturn)) void semihost_exit(uint32_t code);
/* трамплин @main принимает (argc, argv); у МК argv нет — (0, 0) */
int main(int argc, char **argv);

__attribute__((noreturn)) void reset_handler(void) {
    for (uint32_t *load = __data_load, *dst = __data_start;
         dst < __data_end; load++, dst++) {
        *dst = *load;
    }
    for (uint32_t *dst = __bss_start; dst < __bss_end; dst++) {
        *dst = 0;
    }
    board_init();
    semihost_exit((uint32_t)main(0, 0));
}

/* Программы EATLang однопоточны; прерывания — деталь драйвера платы
 * (MCU_PLAN §2): каждый внешний IRQ уходит в общий трамплин, тот
 * читает номер из IPSR и зовёт board_irq(irq). Слабая заглушка —
 * пусто: IRQ не приходят, пока плата их не включила. Отказ ядра
 * (HardFault и т.п.) — выход с кодом 70: язык тотальный, фолт
 * означает дыру в шиме, а не в программе. */

__attribute__((weak)) void board_irq(uint32_t irq) {
    (void)irq;
}

static void irq_trampoline(void) {
    uint32_t ipsr;
    __asm__ volatile("mrs %0, ipsr" : "=r"(ipsr));
    board_irq((ipsr & 0x1FFu) - 16u);
}

static void fault_handler(void) {
    semihost_exit(70);
}

/* [0] — вершина стека, [1] — Reset, [2..15] — отказы ядра,
 * [16..79] — 64 внешних IRQ (хватает всем портам mcu/boards/). */
#define VECTORS_IRQS 64
__attribute__((section(".vectors"), used)) static void *const
    vectors[16 + VECTORS_IRQS] = {
        (void *)__stack_top,
        (void *)reset_handler,
        [2 ... 15] = (void *)fault_handler,
        [16 ...(15 + VECTORS_IRQS)] = (void *)irq_trampoline,
};

/* --- EABI-хелперы памяти -------------------------------------------- */

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

/* --- программное деление для Cortex-M0/M0+ (thumbv6m) --------------- */
/* У армv6-M нет аппаратного udiv: LLVM зовёт __aeabi_uidiv(mod).
 * Школьное длинное деление, 32 итерации — граница цикла явная.
 * aeabi-контракт uidivmod: частное в r0, остаток в r1 — возвращаем
 * 64-битную пару (компилятор разложит её по r0/r1). */

static uint32_t udiv32(uint32_t num, uint32_t den, uint32_t *rem) {
    uint32_t q = 0;
    uint32_t r = 0;
    for (int i = 31; i >= 0; i--) {
        r = (r << 1) | ((num >> i) & 1u);
        q <<= 1;
        if (r >= den) {
            r -= den;
            q |= 1u;
        }
    }
    *rem = r;
    return q;
}

uint32_t __aeabi_uidiv(uint32_t num, uint32_t den) {
    uint32_t rem;
    return udiv32(num, den, &rem);
}

uint64_t __aeabi_uidivmod(uint32_t num, uint32_t den) {
    uint32_t rem;
    uint32_t q = udiv32(num, den, &rem);
    return ((uint64_t)rem << 32) | q;
}
