/* Порт tests/bench/programs/StrCmpBench.eat 1:1 — сборка строки
 * в char-буфере (snprintf: префикс + десятичное число) и посимвольное
 * сравнение strcmp с общим префиксом 40+ байт. Вывод обязан совпасть
 * байт-в-байт с EATLang-оригиналом при том же REPEAT. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const uint32_t REPEAT = 1;

int main(void) {
    const char *t = "common-prefix-the-quick-brown-fox-jumps-tail-00000";
    uint32_t acc = 0;
    for (uint32_t r = 0; r < REPEAT; r++) {
        for (uint32_t k = 0; k < 20u; k++) {
            for (uint32_t i = 0; i < 1000u; i++) {
                acc = (acc * 31u + i + k) % 65536u;
                char s[256];
                snprintf(s, sizeof s,
                         "common-prefix-the-quick-brown-fox-jumps-tail-%u",
                         acc);
                if (strcmp(s, t) == 0) {
                    acc = acc + 7u;
                }
            }
        }
    }
    printf("checksum %u\n", acc);
    return 0;
}
