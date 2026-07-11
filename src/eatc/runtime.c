/* Рантайм EATLang: строки фиксированной ёмкости, ввод, trap.
 * Кучи нет — все буферы статической ёмкости (SPEC.md §3).
 * Линкуется clang'ом вместе с объектным файлом программы. */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define EAT_STR_CAP 256

typedef struct {
    int32_t len;
    char buf[EAT_STR_CAP];
} eat_str;

void eat_trap(const char *msg) {
    fprintf(stderr, "%s\n", msg);
    exit(1);
}

void eat_print(const eat_str *s) {
    printf("%.*s\n", (int)s->len, s->buf);
    fflush(stdout);
}

void eat_str_init(eat_str *s) {
    s->len = 0;
}

void eat_str_append_bytes(eat_str *s, const char *p, int32_t n) {
    if (s->len + n > EAT_STR_CAP) {
        eat_trap("trap: строка длиннее ёмкости str<256>");
    }
    memcpy(s->buf + s->len, p, (size_t)n);
    s->len += n;
}

void eat_str_append_str(eat_str *s, const eat_str *o) {
    eat_str_append_bytes(s, o->buf, o->len);
}

void eat_str_append_i32(eat_str *s, int32_t v) {
    char tmp[16];
    int n = snprintf(tmp, sizeof tmp, "%d", v);
    eat_str_append_bytes(s, tmp, (int32_t)n);
}

void eat_str_append_u32(eat_str *s, uint32_t v) {
    char tmp[16];
    int n = snprintf(tmp, sizeof tmp, "%u", v);
    eat_str_append_bytes(s, tmp, (int32_t)n);
}

void eat_str_append_char(eat_str *s, char c) {
    eat_str_append_bytes(s, &c, 1);
}

void eat_str_append_bool(eat_str *s, int32_t v) {
    if (v) {
        eat_str_append_bytes(s, "true", 4);
    } else {
        eat_str_append_bytes(s, "false", 5);
    }
}

int32_t eat_str_eq(const eat_str *a, const eat_str *b) {
    return a->len == b->len &&
           memcmp(a->buf, b->buf, (size_t)a->len) == 0;
}

/* 0 — Ok, 1 — Eof */
int32_t eat_read_line(eat_str *out) {
    char tmp[EAT_STR_CAP + 8];
    if (fgets(tmp, sizeof tmp, stdin) == NULL) {
        return 1;
    }
    size_t n = strlen(tmp);
    if (n > 0 && tmp[n - 1] == '\n') {
        n--;
    }
    if (n > EAT_STR_CAP) {
        eat_trap("trap: ввод длиннее str<256>");
    }
    memcpy(out->buf, tmp, n);
    out->len = (int32_t)n;
    return 0;
}

/* 0 — Ok, 1 — Empty, 2 — BadChar, 3 — Overflow.
 * Семантика повторяет интерпретатор: обрезка пробелов, знак, цифры. */
int32_t eat_parse_i32(const eat_str *s, int32_t *out) {
    int32_t lo = 0;
    int32_t hi = s->len;
    while (lo < hi && (s->buf[lo] == ' ' || s->buf[lo] == '\t')) {
        lo++;
    }
    while (hi > lo && (s->buf[hi - 1] == ' ' || s->buf[hi - 1] == '\t')) {
        hi--;
    }
    if (lo == hi) {
        return 1;
    }
    int64_t sign = 1;
    if (s->buf[lo] == '+' || s->buf[lo] == '-') {
        sign = s->buf[lo] == '-' ? -1 : 1;
        lo++;
        if (lo == hi) {
            return 2;
        }
    }
    int64_t acc = 0;
    for (int32_t i = lo; i < hi; i++) {
        char c = s->buf[i];
        if (c < '0' || c > '9') {
            return 2;
        }
        acc = acc * 10 + (c - '0');
        if (acc * sign > INT32_MAX || acc * sign < INT32_MIN) {
            return 3;
        }
    }
    *out = (int32_t)(acc * sign);
    return 0;
}
