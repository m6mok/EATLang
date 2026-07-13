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
int main(void);

__attribute__((noreturn)) void reset_handler(void) {
    for (uint32_t *load = __data_load, *dst = __data_start;
         dst < __data_end; load++, dst++) {
        *dst = *load;
    }
    for (uint32_t *dst = __bss_start; dst < __bss_end; dst++) {
        *dst = 0;
    }
    board_init();
    semihost_exit((uint32_t)main());
}

/* [0] — вершина стека, [1] — Reset; прерываний нет: программы
 * EATLang однопоточны, ISR живут в драйверах плат (extern). */
__attribute__((section(".vectors"), used)) static void *const vectors[2] = {
    (void *)__stack_top,
    (void *)reset_handler,
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
