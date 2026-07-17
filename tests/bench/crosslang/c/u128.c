/* Порт tests/bench/programs/U128Bench.eat 1:1 — 128-битный микс без
 * деления: шаг LCG128 (константы PCG64) + точное произведение 64x64.
 * EATLang считает лимбами lib/U128.eat, C — нативным unsigned __int128.
 * Вывод обязан совпасть байт-в-байт при том же REPEAT. */
#include <stdint.h>
#include <stdio.h>

static const uint32_t REPEAT = 1;

typedef unsigned __int128 u128;

static uint64_t work(uint64_t seed) {
    const u128 mc = ((u128)2549297995355413924ull << 64)
        | 4865540595714422341ull;
    const u128 inc = 1442695040888963407ull;
    u128 s = ((u128)seed << 64) | 11634580027462260723ull;
    uint64_t acc = 0;
    for (uint32_t k = 0; k < 20u; k++) {
        for (uint32_t i = 0; i < 1000u; i++) {
            s = s * mc + inc;
            uint64_t hi = (uint64_t)(s >> 64);
            uint64_t lo = (uint64_t)s;
            u128 p = (u128)(hi ^ acc) * (u128)(lo | 1u);
            acc = acc ^ (uint64_t)(p >> 64) ^ ((uint64_t)p >> 7);
        }
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
