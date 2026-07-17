/* Порт tests/bench/programs/BranchBench.eat 1:1 — непредсказуемые
 * ветвления, if/elif-диспетчер по битам loop-carried acc. Вывод обязан
 * совпасть байт-в-байт с EATLang-оригиналом при том же REPEAT. */
#include <stdint.h>
#include <stdio.h>

static const uint32_t REPEAT = 1;

static uint32_t work(uint32_t seed) {
    uint32_t acc = seed + 1u;
    for (uint32_t k = 0; k < 500u; k++) {
        for (uint32_t i = 0; i < 1000u; i++) {
            uint32_t t = (acc >> (i & 7u)) & 3u;
            if (t == 0u) {
                acc = (acc + i + 1u) % 65536u;
            } else if (t == 1u) {
                acc = (acc * 5u + 3u) % 65536u;
            } else if (t == 2u) {
                acc = (acc ^ (i & 4095u)) % 65536u;
            } else {
                acc = ((acc >> 1) | 1u) % 65536u;
            }
        }
    }
    return acc;
}

int main(void) {
    uint32_t acc = 7u;
    for (uint32_t r = 0; r < REPEAT; r++) {
        acc = work(acc);
    }
    printf("checksum %u\n", acc);
    return 0;
}
