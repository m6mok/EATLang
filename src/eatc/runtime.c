/* Шим EATLang: аксиомы ОС — байт из stdin, байт в stdout,
 * диапазон байтов в stdout, байт в stderr, штатный выход с кодом, trap,
 * аргументы командной строки (arg_count/arg_len/arg_byte).
 * Вся логика рантайма (строки, интерполяция, read_line, parse_i32)
 * написана на EATLang: selfhost/Rt.eat — первый модуль каждой
 * программы. Линкуется clang'ом вместе с объектным файлом. */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
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
 * (~десятки нс на вызов), что дороже побайтной записи имён.
 * Порог 16 — измеренный кроссовер после слоя 0 (runtime.c с -O2):
 * fwrite обгоняет побайтную запись начиная с ~12 байт (fixed-cost
 * ~22 нс/вызов против ~2 нс/байт), к 16 байтам выигрыш ×1.4; 16 —
 * консервативная граница явного выигрыша. До -O2 кроссовер был ~32.
 * На продакшн-стадиях эффект ниже пола (эмиссия/дампы compute-bound),
 * заметен на write-доминированных путях. */
void eat_write_span(const uint8_t *p, uint32_t n) {
    if (n < 16) {
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

/* --- кооперативная асинхронность (ASYNC_PLAN, ярус 0) --------------
 * in_avail: сколько байт stdin прочитается read_byte без блокировки.
 * Файл — размер минус логическая позиция потока (ftello учитывает
 * stdio-буфер: детерминизм make verify — интерпретатор зеркалит
 * fstat+tell байт-в-байт); пайп/tty — FIONREAD, живой режим
 * (недооценка на stdio-буфер допустима, SPEC §7). Потолок — u32. */
uint32_t eat_in_avail(void) {
    struct stat st;
    if (fstat(STDIN_FILENO, &st) == 0 && S_ISREG(st.st_mode)) {
        off_t pos = ftello(stdin);
        if (pos < 0 || st.st_size <= pos) {
            return 0;
        }
        uint64_t avail = (uint64_t)(st.st_size - pos);
        return avail > 0xffffffffu ? 0xffffffffu : (uint32_t)avail;
    }
    int n = 0;
    if (ioctl(STDIN_FILENO, FIONREAD, &n) == 0 && n > 0) {
        return (uint32_t)n;
    }
    return 0;
}

/* ticks: монотонные миллисекунды, первый вызов — 0. EAT_TICKS=virt —
 * виртуальные часы (+1 на вызов, решение D2 ASYNC_PLAN): интерпретатор
 * и бинарник тикают одинаково без знания о витках loop. Состояние —
 * статики шима, как у argv (граница доверия аксиом). */
uint64_t eat_ticks(void) {
    static int virt = -1;
    static uint64_t vclock = 0;
    static uint64_t base = 0;
    static int base_set = 0;
    if (virt < 0) {
        const char *e = getenv("EAT_TICKS");
        virt = e != 0 && strcmp(e, "virt") == 0;
    }
    if (virt) {
        return vclock++;
    }
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    uint64_t now =
        (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
    if (!base_set) {
        base = now;
        base_set = 1;
    }
    return now - base;
}
