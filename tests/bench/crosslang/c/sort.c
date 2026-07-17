/* Порт tests/bench/programs/SortBench.eat 1:1 — сортировка вставками
 * с data-dependent ветвлениями и взвешенной свёрткой результата.
 * Вывод обязан совпасть байт-в-байт с EATLang-оригиналом при том же
 * REPEAT. */
#include <stdint.h>
#include <stdio.h>

static const uint32_t REPEAT = 1;

static uint32_t fill(uint32_t seed, uint32_t k) {
    return (seed * 31u + k + 1u) % 65536u;
}

int main(void) {
    uint32_t a[32] = {0};
    uint32_t acc = 7u;
    for (uint32_t r = 0; r < REPEAT; r++) {
        for (uint32_t s = 0; s < 500u; s++) {
            for (uint32_t i = 0; i < 32u; i++) {
                acc = fill(acc, i);
                a[i] = acc;
            }
            for (uint32_t i = 1; i < 32u; i++) {
                uint32_t v = a[i];
                uint32_t j = i;
                for (uint32_t t = 0; t < 32u; t++) {
                    int move = 0;
                    if (j > 0) {
                        if (a[j - 1] > v) {
                            move = 1;
                        }
                    }
                    if (move) {
                        a[j] = a[j - 1];
                        j = j - 1;
                    } else {
                        break;
                    }
                }
                a[j] = v;
            }
            for (uint32_t i = 0; i < 32u; i++) {
                acc = (acc * 3u + a[i]) % 65536u;
            }
        }
    }
    printf("checksum %u\n", acc);
    return 0;
}
