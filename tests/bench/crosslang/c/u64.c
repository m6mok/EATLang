/* Порт tests/bench/programs/U64Bench.eat 1:1 — 64-битная беззнаковая
 * арифметика, деление, широкие сдвиги. Вывод обязан совпасть байт-в-байт
 * с EATLang-оригиналом при том же REPEAT. */
#include <stdint.h>
#include <stdio.h>

static const uint32_t REPEAT = 1;

static uint64_t work(uint64_t seed) {
    uint64_t acc = seed;
    for (uint32_t k = 0; k < 200u; k++) {
        for (uint32_t i = 0; i < 1000u; i++) {
            acc = (acc * 31u + (uint64_t)i) % 281474976710656ull;
            acc = acc ^ (acc >> 33);
            acc = acc + acc / (uint64_t)((i & 7u) + 2u);
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
