/* Шим EATLang: шесть аксиом ОС — байт из stdin, байт в stdout,
 * диапазон байтов в stdout, байт в stderr, штатный выход с кодом, trap.
 * Вся логика рантайма (строки, интерполяция, read_line, parse_i32)
 * написана на EATLang: selfhost/Rt.eat — первый модуль каждой
 * программы. Линкуется clang'ом вместе с объектным файлом. */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/* Байт из stdin: 0..255, при конце потока -1 (Err(Eof)).
 * fflush перед чтением нужен только диалогу с терминалом (приглашение
 * обязано дойти до пользователя); в батч-режиме (фильтр stdin -> stdout)
 * он стоил бы по вызову libc на каждый входной байт. */
int32_t eat_read_byte(void) {
    static int interactive = -1;
    if (interactive < 0) {
        interactive = isatty(STDIN_FILENO) || isatty(STDOUT_FILENO);
    }
    if (interactive) {
        fflush(stdout);
    }
    int c = getc_unlocked(stdin);
    return c == EOF ? -1 : (c & 0xff);
}

/* Байт в stdout (write_byte) — единственный примитив вывода;
 * буферизацию держит libc, нормальный выход из main сбрасывает её.
 * Программы EATLang однопоточны по построению, поэтому _unlocked:
 * flockfile/funlockfile на каждый байт — до 2/3 цены putchar. */
void eat_write_byte(char b) {
    putc_unlocked((unsigned char)b, stdout);
}

/* Диапазон байтов в stdout одним вызовом (write_span): батч-вывод
 * для рантайма и эмиттеров — вместо вызова на каждый байт.
 * Короткие спаны — putc_unlocked: fwrite берёт блокировку потока
 * (~десятки нс на вызов), что дороже побайтной записи имён. */
void eat_write_span(const uint8_t *p, uint32_t n) {
    if (n < 32) {
        for (uint32_t i = 0; i < n; i++) {
            putc_unlocked(p[i], stdout);
        }
    } else {
        fwrite(p, 1, n, stdout);
    }
}

/* Байт в stderr (write_err_byte): канал диагностики,
 * не смешивается с полезным выводом фильтра stdin -> stdout. */
void eat_write_err_byte(char b) {
    fputc((unsigned char)b, stderr);
}

/* Штатное завершение с кодом (exit) — только из main, не более
 * одного вызова на программу; exit() сбрасывает буферы libc. */
void eat_exit(uint32_t code) {
    exit((int)code);
}

/* Аварийная остановка: сообщение в stderr, код 1. */
void eat_trap(const char *msg) {
    fflush(stdout);
    fprintf(stderr, "%s\n", msg);
    exit(1);
}

/* Аварийная остановка в режиме trap-кодов (--trap-codes, метрика
 * флеша МК): в бинарнике вместо текста — число; таблица
 * `; trap <код>: <сообщение>` — комментарии в хвосте .ll. */
void eat_trap_code(uint32_t code) {
    fflush(stdout);
    fprintf(stderr, "trap %u\n", code);
    exit(1);
}
