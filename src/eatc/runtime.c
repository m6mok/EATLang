/* Шим EATLang: пять аксиом ОС — байт из stdin, байт в stdout,
 * байт в stderr, штатный выход с кодом, trap.
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
    int c = getchar();
    return c == EOF ? -1 : (c & 0xff);
}

/* Байт в stdout (write_byte) — единственный примитив вывода;
 * буферизацию держит libc, нормальный выход из main сбрасывает её. */
void eat_write_byte(char b) {
    putchar((unsigned char)b);
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
