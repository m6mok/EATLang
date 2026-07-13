/* 64-битные EABI-хелперы для ARM32 (u64/i64 в языке): LLVM опускает
 * 64-битное деление в __aeabi_uldivmod/__aeabi_ldivmod на всех
 * thumb-целях, а на thumbv6m (Cortex-M0) ещё и умножение/сдвиги —
 * в __aeabi_lmul/__aeabi_llsl/__aeabi_llsr/__aeabi_lasr. Готового
 * libclang_rt.builtins.a под baremeтal-arm в тулчейне macOS нет —
 * хелперы свои, в духе startup.c (деление столбиком, явные границы).
 *
 * Внутри — только константные 64-битные сдвиги, 32-битные переменные
 * сдвиги и 32x32->32 умножения: ни одна функция не порождает вызов
 * самой себя или соседки. */

#include <stdint.h>

/* Деление столбиком, 64 итерации; сдвиги только на константу. */
uint64_t __udivmoddi4(uint64_t num, uint64_t den, uint64_t *rem) {
    uint64_t q = 0;
    uint64_t r = 0;
    for (int i = 0; i < 64; i++) {
        r = (r << 1) | (num >> 63);
        num <<= 1;
        q <<= 1;
        if (r >= den) {
            r -= den;
            q |= 1u;
        }
    }
    if (rem) {
        *rem = r;
    }
    return q;
}

int64_t __divmoddi4(int64_t a, int64_t b, int64_t *rem) {
    uint64_t ua = a < 0 ? 0u - (uint64_t)a : (uint64_t)a;
    uint64_t ub = b < 0 ? 0u - (uint64_t)b : (uint64_t)b;
    uint64_t ur;
    uint64_t uq = __udivmoddi4(ua, ub, &ur);
    int64_t q = ((a < 0) != (b < 0)) ? -(int64_t)uq : (int64_t)uq;
    int64_t r = a < 0 ? -(int64_t)ur : (int64_t)ur;
    if (rem) {
        *rem = r;
    }
    return q;
}

/* aeabi-контракт uldivmod/ldivmod: частное в r0:r1, остаток в r2:r3 —
 * в C невыразимо, обвязка на asm (thumb1-совместимая: низкие регистры),
 * остаток кладётся в слот на стеке и поднимается в r2:r3. */
__attribute__((naked)) void __aeabi_uldivmod(void) {
    __asm__ volatile(
        "push {r6, lr}\n\t"
        "sub sp, #16\n\t"
        "add r6, sp, #8\n\t"
        "str r6, [sp]\n\t"
        "bl __udivmoddi4\n\t"
        "ldr r2, [sp, #8]\n\t"
        "ldr r3, [sp, #12]\n\t"
        "add sp, #16\n\t"
        "pop {r6, pc}\n\t");
}

__attribute__((naked)) void __aeabi_ldivmod(void) {
    __asm__ volatile(
        "push {r6, lr}\n\t"
        "sub sp, #16\n\t"
        "add r6, sp, #8\n\t"
        "str r6, [sp]\n\t"
        "bl __divmoddi4\n\t"
        "ldr r2, [sp, #8]\n\t"
        "ldr r3, [sp, #12]\n\t"
        "add sp, #16\n\t"
        "pop {r6, pc}\n\t");
}

/* 64x64->64 через 16-битные половины: 32x32->32 (muls) есть и на
 * v6-M, поэтому рекурсии в __aeabi_lmul нет. */
static uint64_t mul32x32(uint32_t a, uint32_t b) {
    uint32_t a_lo = a & 0xFFFFu;
    uint32_t a_hi = a >> 16;
    uint32_t b_lo = b & 0xFFFFu;
    uint32_t b_hi = b >> 16;
    uint64_t r = (uint64_t)(a_lo * b_lo);
    r += (uint64_t)(a_lo * b_hi) << 16;
    r += (uint64_t)(a_hi * b_lo) << 16;
    r += (uint64_t)(a_hi * b_hi) << 32;
    return r;
}

uint64_t __aeabi_lmul(uint64_t a, uint64_t b) {
    uint32_t a0 = (uint32_t)a;
    uint32_t b0 = (uint32_t)b;
    uint64_t r = mul32x32(a0, b0);
    r += (uint64_t)((uint32_t)(a >> 32) * b0 + a0 * (uint32_t)(b >> 32))
         << 32;
    return r;
}

/* Сдвиги по 32-битным половинам: переменные 32-битные сдвиги — в
 * железе, 64-битные — только на константу 32. Величина < 64 (trap
 * «сдвиг ≥ ширины» стоит до вызова). */
uint64_t __aeabi_llsl(uint64_t x, int n) {
    uint32_t lo = (uint32_t)x;
    uint32_t hi = (uint32_t)(x >> 32);
    if (n >= 32) {
        return (uint64_t)(lo << (n - 32)) << 32;
    }
    if (n == 0) {
        return x;
    }
    return ((uint64_t)((hi << n) | (lo >> (32 - n))) << 32) |
           (uint64_t)(lo << n);
}

uint64_t __aeabi_llsr(uint64_t x, int n) {
    uint32_t lo = (uint32_t)x;
    uint32_t hi = (uint32_t)(x >> 32);
    if (n >= 32) {
        return (uint64_t)(hi >> (n - 32));
    }
    if (n == 0) {
        return x;
    }
    return ((uint64_t)(hi >> n) << 32) |
           (uint64_t)((lo >> n) | (hi << (32 - n)));
}

int64_t __aeabi_lasr(int64_t x, int n) {
    uint32_t lo = (uint32_t)(uint64_t)x;
    int32_t hi = (int32_t)((uint64_t)x >> 32);
    if (n >= 32) {
        return ((int64_t)(hi >> 31) << 32) | (uint32_t)(hi >> (n - 32));
    }
    if (n == 0) {
        return x;
    }
    return ((int64_t)(hi >> n) << 32) |
           (uint64_t)((lo >> n) | ((uint32_t)hi << (32 - n)));
}

/* Знаковое 32-битное деление: v6-M зовёт __aeabi_idiv(mod) так же,
 * как беззнаковое (__aeabi_uidiv в startup.c). */
static uint32_t udiv32e(uint32_t num, uint32_t den, uint32_t *rem) {
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

int32_t __aeabi_idiv(int32_t a, int32_t b) {
    uint32_t ua = a < 0 ? 0u - (uint32_t)a : (uint32_t)a;
    uint32_t ub = b < 0 ? 0u - (uint32_t)b : (uint32_t)b;
    uint32_t ur;
    uint32_t uq = udiv32e(ua, ub, &ur);
    return ((a < 0) != (b < 0)) ? -(int32_t)uq : (int32_t)uq;
}

/* aeabi-контракт idivmod: частное в r0, остаток в r1 — 64-битная
 * пара, компилятор разложит её по r0/r1 (как uidivmod в startup.c). */
uint64_t __aeabi_idivmod(int32_t a, int32_t b) {
    uint32_t ua = a < 0 ? 0u - (uint32_t)a : (uint32_t)a;
    uint32_t ub = b < 0 ? 0u - (uint32_t)b : (uint32_t)b;
    uint32_t ur;
    uint32_t uq = udiv32e(ua, ub, &ur);
    int32_t q = ((a < 0) != (b < 0)) ? -(int32_t)uq : (int32_t)uq;
    int32_t r = a < 0 ? -(int32_t)ur : (int32_t)ur;
    return ((uint64_t)(uint32_t)r << 32) | (uint32_t)q;
}
