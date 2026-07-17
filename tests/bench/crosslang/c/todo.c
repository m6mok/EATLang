/* Порт tests/bench/programs/TodoBench.eat 1:1 — ядро RESTful TODO-list:
 * bounded-пул из 64 слотов под потоком create/toggle/serialize/remove.
 * title зависит от loop-carried acc, поэтому сериализацию не сфолдить.
 * Вывод обязан совпасть байт-в-байт с EATLang-оригиналом при том же
 * REPEAT. */
#include <stdint.h>
#include <stdio.h>

static const uint32_t REPEAT = 1;

#define CAP 64u
#define TLEN 16u

struct Store {
    uint32_t id[64];
    uint8_t title[1024];
    uint8_t done[64];
    uint8_t used[64];
    uint32_t next_id;
};

static uint32_t st_create(struct Store *s, uint32_t k, uint32_t seed) {
    uint32_t slot = k % CAP;
    uint32_t base = slot * TLEN;
    uint32_t id = s->next_id;
    s->id[slot] = id;
    for (uint32_t j = 0; j < 16u; j++) {
        s->title[base + j] = (uint8_t)(65u + (seed + k + j * 7u) % 26u);
    }
    s->done[slot] = (uint8_t)(k % 2u);
    s->used[slot] = 1;
    s->next_id = s->next_id + 1u;
    return id;
}

static void st_toggle(struct Store *s, uint32_t idx) {
    if (s->done[idx] == 0) {
        s->done[idx] = 1;
    } else {
        s->done[idx] = 0;
    }
}

static void st_remove(struct Store *s, uint32_t idx) { s->used[idx] = 0; }

static uint32_t st_serialize(const struct Store *s) {
    uint32_t sum = 0;
    for (uint32_t slot = 0; slot < 64u; slot++) {
        if (s->used[slot] == 1) {
            uint32_t m = s->id[slot];
            for (uint32_t d = 0; d < 10u; d++) {
                if (m == 0) {
                    break;
                }
                sum = (sum * 31u + m % 10u) % 65536u;
                m = m / 10u;
            }
            uint32_t base = slot * TLEN;
            for (uint32_t j = 0; j < 16u; j++) {
                sum = (sum * 31u + s->title[base + j]) % 65536u;
            }
            sum = (sum * 31u + s->done[slot]) % 65536u;
        }
    }
    return sum;
}

int main(void) {
    struct Store s = {0};
    s.next_id = 1;
    uint32_t acc = 0;
    for (uint32_t r = 0; r < REPEAT; r++) {
        for (uint32_t k = 0; k < 2048u; k++) {
            uint32_t seed = acc;
            uint32_t id = st_create(&s, k, seed);
            acc = (acc * 31u + id) % 65536u;
            uint32_t t = (k * 3u) % CAP;
            st_toggle(&s, t);
            if (k % 8u == 0) {
                acc = (acc * 31u + st_serialize(&s)) % 65536u;
            }
            if (k % 16u == 0) {
                uint32_t rr = (k * 5u) % CAP;
                st_remove(&s, rr);
            }
        }
    }
    printf("checksum %u\n", acc);
    return 0;
}
