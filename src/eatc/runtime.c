/* Шим EATLang: аксиомы ОС — байт из stdin, байт в stdout,
 * диапазон байтов в stdout, байт в stderr, штатный выход с кодом, trap,
 * аргументы командной строки (arg_count/arg_len/arg_byte),
 * сокеты HTTP-трека (socket_listen/accept/avail/read_byte/
 * write_span/close, HTTP_PLAN §5: сверка — транскрипт EAT_NET,
 * живой режим — реальные неблокирующие сокеты).
 * Вся логика рантайма (строки, интерполяция, read_line, parse_i32)
 * написана на EATLang: selfhost/Rt.eat — первый модуль каждой
 * программы. Линкуется clang'ом вместе с объектным файлом. */

#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* --- стек главного потока (Linux) ----------------------------------
 * Пулы программ EATLang живут в кадре main (кучи нет — Power of 10);
 * у self-hosted компилятора кадр ~85 МБ. Линковочный
 * `-Wl,-z,stacksize=` (STACK_FLAGS Makefile, codegen.py) задаёт лишь
 * сегмент PT_GNU_STACK, который glibc НЕ применяет к главному потоку
 * (в отличие от mach-O `-stack_size`), поэтому под дефолтным
 * `ulimit -s` 8 МБ бинарник падал SIGSEGV на входе в main
 * (FAULTS 2026-07-18). Self-provision: конструктор до main поднимает
 * мягкий RLIMIT_STACK до потолка 256 МиБ (= значению линковочного
 * флага) и РОВНО ОДИН раз перезапускает процесс — лишь execve даёт
 * ядру заложить раскладку адресного пространства (mmap-базу) под
 * новый лимит; setrlimit без перезапуска места росту стека не
 * гарантирует. Ограничено: один re-exec (страж EAT_STACK_REEXEC),
 * явный потолок; при недоступности (урезан жёсткий лимит, exec
 * провалился) тихо продолжаем с тем, что подняли. glibc зовёт
 * функции .init_array с (argc, argv, envp) — отсюда argv для execv;
 * до main ни ввода, ни вывода ещё не было, перезапуск невидим для
 * семантики программы. macOS не касается (#ifdef __linux__). */
#ifdef __linux__
#include <sys/resource.h>

#define EAT_STACK_BYTES ((rlim_t)268435456) /* 256 МиБ = stacksize линковки */

__attribute__((constructor)) static void
eat_stack_provision(int argc, char **argv, char **envp) {
    (void)argc;
    (void)envp;
    struct rlimit rl;
    if (getrlimit(RLIMIT_STACK, &rl) != 0) {
        return;
    }
    if (rl.rlim_cur == RLIM_INFINITY || rl.rlim_cur >= EAT_STACK_BYTES) {
        return;
    }
    if (getenv("EAT_STACK_REEXEC") != 0) {
        return; /* уже перезапускались — второго раза не будет */
    }
    rlim_t want = EAT_STACK_BYTES;
    if (rl.rlim_max != RLIM_INFINITY && rl.rlim_max < want) {
        want = rl.rlim_max;
    }
    if (want <= rl.rlim_cur) {
        return;
    }
    rl.rlim_cur = want;
    if (setrlimit(RLIMIT_STACK, &rl) != 0) {
        return;
    }
    if (argv == 0 || argv[0] == 0) {
        return; /* не-glibc не передал argv — остаёмся без re-exec */
    }
    setenv("EAT_STACK_REEXEC", "1", 1);
    execv("/proc/self/exe", argv);
    /* exec не удался: живём с поднятым лимитом без гарантий раскладки */
}
#endif

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

/* --- сокеты (HTTP_PLAN §5, решения H1/H2) --------------------------
 * Два режима, переключатель — переменная окружения EAT_NET:
 *   - EAT_NET=<файл> — сверка: аксиомы читают записанный транскрипт
 *     (текстовые события `accept` / `data <fd> <байты>` / `close <fd>`,
 *     потребляются по порядку; вывод socket_write_span — в stdout тем
 *     же потоком, что write). Дескрипторы детерминированы: слушатель 3,
 *     соединения 4, 5, ... Паритет с интерпретатором — байт-в-байт.
 *   - без EAT_NET — живой режим (make serve): реальные неблокирующие
 *     сокеты ядра, в make verify* не участвует.
 * Контракты (оба режима, тексты trap байт-в-байт с интерпретатором):
 *   - операция на чужом/закрытом fd — trap "socket: неверный дескриптор";
 *   - socket_read_byte без готовых данных в сверке — trap
 *     "socket_read_byte без готовых данных" (детерминированный
 *     суррогат вечной блокировки; страж socket_avail(fd) > 0);
 *   - кривой сценарий — trap "EAT_NET: неверный сценарий".
 * Состояние — статики шима, как argv/ticks (граница доверия аксиом). */

#define EAT_NET_EVENTS 8192
#define EAT_NET_POOL (1u << 20)
#define EAT_NET_CONNS 64
#define EAT_NET_NO_CONN 0xffffffffu

/* События сценария: kind 0 accept, 1 data, 2 close. */
static int net_mode = -1;            /* -1 не решено, 0 живой, 1 транскрипт */
static uint8_t ev_kind[EAT_NET_EVENTS];
static uint32_t ev_fd[EAT_NET_EVENTS];
static uint32_t ev_off[EAT_NET_EVENTS];
static uint32_t ev_len[EAT_NET_EVENTS];
static uint32_t ev_link[EAT_NET_EVENTS]; /* цепочка очереди одного fd */
static uint32_t nev = 0;
static uint32_t ev_next = 0;         /* первое непримененное событие */
static uint8_t net_pool[EAT_NET_POOL];
static uint32_t npool = 0;
/* Соединение i — fd 4+i; слушатель — fd 3. */
static uint32_t cq_first[EAT_NET_CONNS]; /* голова цепочки данных */
static uint32_t cq_last[EAT_NET_CONNS];
static uint32_t cq_cur[EAT_NET_CONNS];   /* съедено в головном событии */
static uint8_t c_peer_closed[EAT_NET_CONNS];
static uint8_t c_prog_closed[EAT_NET_CONNS];
static uint32_t nconn = 0;
static uint8_t listener_open = 0;

static void net_scenario_fail(void) {
    eat_trap("EAT_NET: неверный сценарий");
}

static void net_ev_push(uint8_t kind, uint32_t fd, uint32_t off,
                        uint32_t len) {
    if (nev >= EAT_NET_EVENTS) {
        net_scenario_fail();
    }
    ev_kind[nev] = kind;
    ev_fd[nev] = fd;
    ev_off[nev] = off;
    ev_len[nev] = len;
    ev_link[nev] = EAT_NET_NO_CONN;
    nev++;
}

/* Разбор файла сценария: строка — событие; пустые строки и строки
 * с '#' в первом столбце — комментарии. Payload `data` — остаток
 * строки после второго пробела; эскейпы: \r \n \t \\ \xHH. */
static void net_parse(FILE *f) {
    int c;
    while ((c = getc(f)) != EOF) {
        if (c == '\n') {
            continue;
        }
        if (c == '#') {
            while ((c = getc(f)) != EOF && c != '\n') {
            }
            continue;
        }
        char word[8];
        uint32_t wl = 0;
        while (c != EOF && c != '\n' && c != ' ') {
            if (wl + 1 >= sizeof(word)) {
                net_scenario_fail();
            }
            word[wl++] = (char)c;
            c = getc(f);
        }
        word[wl] = 0;
        if (strcmp(word, "accept") == 0) {
            if (c == ' ') {
                net_scenario_fail();
            }
            net_ev_push(0, 0, 0, 0);
            continue;
        }
        if (strcmp(word, "data") != 0 && strcmp(word, "close") != 0) {
            net_scenario_fail();
        }
        if (c != ' ') {
            net_scenario_fail();
        }
        uint32_t fd = 0;
        int nd = 0;
        while ((c = getc(f)) != EOF && c >= '0' && c <= '9') {
            fd = fd * 10u + (uint32_t)(c - '0');
            nd++;
        }
        if (nd == 0) {
            net_scenario_fail();
        }
        if (word[0] == 'c') {
            if (c != EOF && c != '\n') {
                net_scenario_fail();
            }
            net_ev_push(2, fd, 0, 0);
            continue;
        }
        if (c != ' ') {
            net_scenario_fail();
        }
        uint32_t off = npool;
        while ((c = getc(f)) != EOF && c != '\n') {
            uint8_t b;
            if (c == '\\') {
                int e = getc(f);
                if (e == 'r') {
                    b = '\r';
                } else if (e == 'n') {
                    b = '\n';
                } else if (e == 't') {
                    b = '\t';
                } else if (e == '\\') {
                    b = '\\';
                } else if (e == 'x') {
                    int h1 = getc(f);
                    int h2 = getc(f);
                    int v1 = h1 >= '0' && h1 <= '9'   ? h1 - '0'
                             : h1 >= 'a' && h1 <= 'f' ? h1 - 'a' + 10
                             : h1 >= 'A' && h1 <= 'F' ? h1 - 'A' + 10
                                                      : -1;
                    int v2 = h2 >= '0' && h2 <= '9'   ? h2 - '0'
                             : h2 >= 'a' && h2 <= 'f' ? h2 - 'a' + 10
                             : h2 >= 'A' && h2 <= 'F' ? h2 - 'A' + 10
                                                      : -1;
                    if (v1 < 0 || v2 < 0) {
                        net_scenario_fail();
                    }
                    b = (uint8_t)(v1 * 16 + v2);
                } else {
                    net_scenario_fail();
                    b = 0;
                }
            } else {
                b = (uint8_t)c;
            }
            if (npool >= EAT_NET_POOL) {
                net_scenario_fail();
            }
            net_pool[npool++] = b;
        }
        net_ev_push(1, fd, off, npool - off);
    }
}

static void net_init(void) {
    if (net_mode >= 0) {
        return;
    }
    const char *path = getenv("EAT_NET");
    if (path == 0 || path[0] == 0) {
        net_mode = 0;
        signal(SIGPIPE, SIG_IGN);
        return;
    }
    FILE *f = fopen(path, "rb");
    if (f == 0) {
        net_scenario_fail();
        return;
    }
    net_parse(f);
    fclose(f);
    net_mode = 1;
}

static uint32_t net_slot(uint32_t fd) {
    if (fd < 4 || fd - 4 >= nconn || c_prog_closed[fd - 4]) {
        eat_trap("socket: неверный дескриптор");
    }
    return fd - 4;
}

/* Применить пассивные события (data/close) до ближайшего accept:
 * данные «в пути» становятся видимыми, темп задаёт сценарий. */
static void net_advance(void) {
    while (ev_next < nev && ev_kind[ev_next] != 0) {
        uint32_t fd = ev_fd[ev_next];
        if (fd < 4 || fd - 4 >= nconn) {
            net_scenario_fail();
        }
        uint32_t s = fd - 4;
        if (ev_kind[ev_next] == 2) {
            c_peer_closed[s] = 1;
        } else if (ev_len[ev_next] > 0) {
            if (cq_last[s] == EAT_NET_NO_CONN) {
                cq_first[s] = ev_next;
            } else {
                ev_link[cq_last[s]] = ev_next;
            }
            cq_last[s] = ev_next;
        }
        ev_next++;
    }
}

int64_t eat_socket_listen(uint32_t port) {
    net_init();
    if (net_mode == 1) {
        listener_open = 1;
        return 3;
    }
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        return -1;
    }
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in a;
    memset(&a, 0, sizeof(a));
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    a.sin_port = htons((uint16_t)port);
    if (bind(fd, (struct sockaddr *)&a, sizeof(a)) < 0 ||
        listen(fd, 16) < 0 ||
        fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

uint32_t eat_socket_accept(uint32_t fd) {
    net_init();
    if (net_mode == 1) {
        if (fd != 3 || !listener_open) {
            eat_trap("socket: неверный дескриптор");
        }
        net_advance();
        if (ev_next < nev && ev_kind[ev_next] == 0) {
            ev_next++;
            if (nconn >= EAT_NET_CONNS) {
                net_scenario_fail();
            }
            uint32_t s = nconn++;
            cq_first[s] = EAT_NET_NO_CONN;
            cq_last[s] = EAT_NET_NO_CONN;
            cq_cur[s] = 0;
            c_peer_closed[s] = 0;
            c_prog_closed[s] = 0;
            return 4 + s;
        }
        return EAT_NET_NO_CONN;
    }
    int c = accept((int)fd, 0, 0);
    if (c < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            return EAT_NET_NO_CONN;
        }
        eat_trap("socket: неверный дескриптор");
    }
    fcntl(c, F_SETFL, fcntl(c, F_GETFL, 0) | O_NONBLOCK);
    return (uint32_t)c;
}

uint32_t eat_socket_avail(uint32_t fd) {
    net_init();
    if (net_mode == 1) {
        uint32_t s = net_slot(fd);
        net_advance();
        uint64_t total = 0;
        uint32_t e = cq_first[s];
        uint32_t cur = cq_cur[s];
        while (e != EAT_NET_NO_CONN) {
            total += ev_len[e] - cur;
            cur = 0;
            e = ev_link[e];
        }
        if (total > 0) {
            return total > 0xffffffffu ? 0xffffffffu : (uint32_t)total;
        }
        return c_peer_closed[s] ? 1u : 0u;
    }
    int n = 0;
    if (ioctl((int)fd, FIONREAD, &n) == 0 && n > 0) {
        return (uint32_t)n;
    }
    struct pollfd p = {(int)fd, POLLIN, 0};
    if (poll(&p, 1, 0) > 0 && (p.revents & (POLLIN | POLLHUP | POLLERR))) {
        return 1;
    }
    return 0;
}

/* Протокол результата: 0..255 — байт, 256 — Eof (пир закрыл),
 * 257 — Fail. Сентинелы положительные (не -1, как у eat_read_byte):
 * кодоген собирает Result сравнениями с неотрицательными литералами —
 * паритет эмиттеров без отрицательных констант в IR. */
int32_t eat_socket_read_byte(uint32_t fd) {
    net_init();
    if (net_mode == 1) {
        uint32_t s = net_slot(fd);
        net_advance();
        uint32_t e = cq_first[s];
        if (e != EAT_NET_NO_CONN) {
            uint8_t b = net_pool[ev_off[e] + cq_cur[s]];
            cq_cur[s]++;
            if (cq_cur[s] >= ev_len[e]) {
                cq_first[s] = ev_link[e];
                if (cq_first[s] == EAT_NET_NO_CONN) {
                    cq_last[s] = EAT_NET_NO_CONN;
                }
                cq_cur[s] = 0;
            }
            return b;
        }
        if (c_peer_closed[s]) {
            return 256;
        }
        eat_trap("socket_read_byte без готовых данных");
        return 257; /* недостижимо: eat_trap завершает процесс */
    }
    for (;;) {
        uint8_t b;
        ssize_t r = recv((int)fd, &b, 1, 0);
        if (r == 1) {
            return b;
        }
        if (r == 0) {
            return 256;
        }
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            /* страж avail не сработал — блокирующая семантика read_byte */
            struct pollfd p = {(int)fd, POLLIN, 0};
            poll(&p, 1, -1);
            continue;
        }
        if (errno == EBADF || errno == ENOTSOCK) {
            eat_trap("socket: неверный дескриптор");
        }
        return 257;
    }
}

uint32_t eat_socket_write_span(uint32_t fd, const uint8_t *p, uint32_t n) {
    net_init();
    if (net_mode == 1) {
        (void)net_slot(fd);
        eat_write_span(p, n);
        return n;
    }
    if (n == 0) {
        return 0;
    }
    ssize_t w = send((int)fd, p, n, 0);
    if (w >= 0) {
        return (uint32_t)w;
    }
    if (errno == EAGAIN || errno == EWOULDBLOCK) {
        return 0;
    }
    if (errno == EBADF || errno == ENOTSOCK) {
        eat_trap("socket: неверный дескриптор");
    }
    /* пир умер (EPIPE/ECONNRESET): байты некому слать — считаем
     * принятыми, закрытие сервер увидит по Err(Eof) чтения */
    return n;
}

void eat_socket_close(uint32_t fd) {
    net_init();
    if (net_mode == 1) {
        if (fd == 3) {
            listener_open = 0;
            return;
        }
        if (fd < 4 || fd - 4 >= nconn) {
            eat_trap("socket: неверный дескриптор");
        }
        /* идемпотентно: повторный close слота — no-op */
        c_prog_closed[fd - 4] = 1;
        return;
    }
    close((int)fd);
}
