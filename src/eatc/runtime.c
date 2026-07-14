/* Шим EATLang: аксиомы ОС — байт из stdin, байт в stdout,
 * диапазон байтов в stdout, байт в stderr, штатный выход с кодом, trap,
 * аргументы командной строки (arg_count/arg_len/arg_byte).
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

/* --- аргументы командной строки (argv без имени программы) ---------
 * Состояние argv — статики шима: у языка нет глобалов, argv живёт на
 * доверенной границе аксиом рядом с pos/interactive. Трамплин @main
 * один раз отдаёт сюда (argc, argv) до вызова eat_main. */
static int argv_n = 0;
static char **argv_p = 0;

void eat_args_set(int32_t argc, char **argv) {
    /* argv[0] — имя программы; программе видны аргументы с индекса 1 */
    if (argc > 1) {
        argv_n = argc - 1;
        argv_p = argv + 1;
    }
}

uint32_t eat_arg_count(void) {
    return (uint32_t)argv_n;
}

/* arg_len/arg_byte вызываются только после проверки границ в коде
 * программы (компилятор эмитит trap) — индексы здесь уже валидны. */
uint32_t eat_arg_len(uint32_t i) {
    uint32_t n = 0;
    const char *s = argv_p[i];
    while (s[n] != 0) {
        n++;
    }
    return n;
}

uint8_t eat_arg_byte(uint32_t i, uint32_t j) {
    return (uint8_t)argv_p[i][j];
}
