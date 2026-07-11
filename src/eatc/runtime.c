/* Шим EATLang: три аксиомы ОС — байт из stdin, байт в stdout, trap.
 * Вся логика рантайма (строки, интерполяция, read_line, parse_i32)
 * написана на EATLang: selfhost/Rt.eat — первый модуль каждой
 * программы. Линкуется clang'ом вместе с объектным файлом. */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/* Байт из stdin: 0..255, при конце потока -1 (Err(Eof)).
 * fflush: приглашение, напечатанное до чтения, доходит до терминала. */
int32_t eat_read_byte(void) {
    fflush(stdout);
    int c = getchar();
    return c == EOF ? -1 : (c & 0xff);
}

/* Байт в stdout (write_byte) — единственный примитив вывода;
 * буферизацию держит libc, нормальный выход из main сбрасывает её. */
void eat_write_byte(char b) {
    putchar((unsigned char)b);
}

/* Аварийная остановка: сообщение в stderr, код 1. */
void eat_trap(const char *msg) {
    fflush(stdout);
    fprintf(stderr, "%s\n", msg);
    exit(1);
}
