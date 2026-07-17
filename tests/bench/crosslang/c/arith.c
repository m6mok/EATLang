/* Порт tests/bench/programs/ArithBench.eat 1:1 — целочисленная
 * арифметика в горячем цикле. Вывод обязан совпасть байт-в-байт
 * с EATLang-оригиналом при том же REPEAT. */
#include <stdint.h>
#include <stdio.h>

static const uint32_t REPEAT = 1;

static uint32_t work(uint32_t seed) {
    uint32_t acc = seed;
    for (uint32_t k = 0; k < 1000u; k++) {
        for (uint32_t i = 0; i < 1000u; i++) {
            acc = (acc * 31u + i) % 65536u;
        }
    }
    return acc;
}

int main(void) {
    uint32_t acc = 7u;
    for (uint32_t r = 0; r < REPEAT; r++) {
        acc = work(acc) % 65536u;
    }
    printf("checksum %u\n", acc);
    return 0;
}
