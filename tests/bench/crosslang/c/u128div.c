/* Порт tests/bench/programs/U128DivBench.eat 1:1 — деление 128 бит:
 * EATLang — полный сдвиговый divrem (128 итераций) и divrem_32 по
 * лимбам, C — нативное деление __int128 (__udivti3). Вывод обязан
 * совпасть байт-в-байт при том же REPEAT. */
#include <stdint.h>
#include <stdio.h>

static const uint32_t REPEAT = 1;

typedef unsigned __int128 u128;

static uint64_t lcg(uint64_t x) {
    return (x * 31u + 7u) % 281474976710656ull;
}

static uint64_t work(uint64_t seed) {
    uint64_t x = seed + 3u;
    uint64_t acc = 0;
    for (uint32_t i = 0; i < 400u; i++) {
        x = lcg(x);
        uint64_t hi = x;
        x = lcg(x);
        uint64_t lo = x;
        x = lcg(x);
        uint64_t d = x | 1u;
        u128 a = ((u128)hi << 64) | lo;
        u128 q = a / d;
        u128 r = a % d;
        acc = acc ^ (uint64_t)q ^ (uint64_t)(q >> 64) ^ (uint64_t)r;
    }
    for (uint32_t i = 0; i < 4000u; i++) {
        x = lcg(x);
        uint64_t hi = x;
        x = lcg(x);
        uint64_t lo = x;
        x = lcg(x);
        uint64_t d32 = (x & 4294967295ull) | 1u;
        u128 a = ((u128)hi << 64) | lo;
        u128 q = a / d32;
        u128 r = a % d32;
        acc = acc ^ (uint64_t)q ^ (uint64_t)(q >> 64) ^ (uint64_t)r;
    }
    return acc % 65536u;
}

int main(void) {
    uint64_t acc = 7u;
    for (uint32_t r = 0; r < REPEAT; r++) {
        acc = work(acc);
    }
    uint32_t c = (uint32_t)acc;
    printf("checksum %u\n", c);
    return 0;
}
