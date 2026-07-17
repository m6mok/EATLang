/* Порт tests/bench/programs/BankBench.eat 1:1 — банкованная память
 * pool[a/4096][a%4096], адрес зависит от loop-carried acc (LLVM не
 * сворачивает). Вывод обязан совпасть байт-в-байт с EATLang-
 * оригиналом при том же REPEAT. Банк — static (128 КБ, не на стеке
 * main), сбрасывается в начале каждого work() как var pool в EATLang. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const uint32_t REPEAT = 1;

static uint32_t pool[8][4096];

static uint32_t work(uint32_t seed) {
    memset(pool, 0, sizeof(pool));
    uint32_t acc = seed;
    for (uint32_t k = 0; k < 200u; k++) {
        for (uint32_t i = 0; i < 1000u; i++) {
            uint32_t a = (acc + i * 37u) % 32768u;
            pool[a / 4096u][a % 4096u] = (acc + i) % 65536u;
            uint32_t b = (a * 17u + 5u) % 32768u;
            acc = (acc + pool[b / 4096u][b % 4096u]) % 65536u;
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
