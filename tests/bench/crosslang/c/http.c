/* Порт tests/bench/programs/HttpBench.eat 1:1 (методика CROSSLANG):
 * тот же HTTP-парсер, что lib/Http.eat — request-line + заголовки в
 * фиксированные буферы, срезы-Header, OWS-трим, 400/413/431, мини-
 * роутер и keep-alive-решение; та же чек-сумма. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const uint32_t REPEAT = 1;

#define HTTP_NONE 0xffffffffu
#define PARSE_MORE 0u
#define PARSE_DONE 1u

typedef struct {
    uint32_t ns, nl, vs, vl;
} Header;

typedef struct {
    uint8_t raw[8192];
    uint32_t n, state, ls, ms, ml, ps, pl, vs, vl, nh, err;
    Header hdr[64];
} Req;

static void req_new(Req *r) {
    memset(r, 0, sizeof(*r));
}

/* Зеркало Req.reset (OPTIMIZATIONS §8.2): скалярные поля в 0,
 * raw/hdr не трогаются — кадр переиспользуется между запросами. */
static void req_reset(Req *r) {
    r->n = 0;
    r->state = 0;
    r->ls = 0;
    r->ms = 0;
    r->ml = 0;
    r->ps = 0;
    r->pl = 0;
    r->vs = 0;
    r->vl = 0;
    r->nh = 0;
    r->err = 0;
}

static uint32_t find_sp(const Req *r, uint32_t b0, uint32_t e0) {
    for (uint32_t i = b0; i < e0; i++) {
        if (r->raw[i] == 32) {
            return i;
        }
    }
    return HTTP_NONE;
}

static uint32_t parse_reqline(Req *r, uint32_t ls2, uint32_t le) {
    uint32_t sp1 = find_sp(r, ls2, le);
    uint32_t sp2 = HTTP_NONE;
    int bad = sp1 == HTTP_NONE;
    if (!bad) {
        sp2 = find_sp(r, sp1 + 1, le);
        bad = sp2 == HTTP_NONE;
    }
    if (!bad) {
        bad = sp1 == ls2 || sp2 == sp1 + 1 || sp2 + 1 == le ||
              find_sp(r, sp2 + 1, le) != HTTP_NONE;
    }
    if (bad) {
        r->state = 3;
        r->err = 400;
        return 400;
    }
    r->ms = ls2;
    r->ml = sp1 - ls2;
    r->ps = sp1 + 1;
    r->pl = sp2 - sp1 - 1;
    r->vs = sp2 + 1;
    r->vl = le - sp2 - 1;
    r->state = 1;
    return PARSE_MORE;
}

static uint32_t parse_header(Req *r, uint32_t ls2, uint32_t le) {
    if (r->nh >= 64) {
        r->state = 3;
        r->err = 431;
        return 431;
    }
    uint32_t colon = HTTP_NONE;
    for (uint32_t i = ls2; i < le; i++) {
        if (r->raw[i] == 58) {
            colon = i;
            break;
        }
    }
    if (colon == HTTP_NONE || colon == ls2) {
        r->state = 3;
        r->err = 400;
        return 400;
    }
    uint32_t vs2 = colon + 1, vl2 = le - vs2;
    while (vl2 > 0 && (r->raw[vs2] == 32 || r->raw[vs2] == 9)) {
        vs2++;
        vl2--;
    }
    while (vl2 > 0) {
        uint8_t tb = r->raw[vs2 + vl2 - 1];
        if (tb != 32 && tb != 9) {
            break;
        }
        vl2--;
    }
    r->hdr[r->nh].ns = ls2;
    r->hdr[r->nh].nl = colon - ls2;
    r->hdr[r->nh].vs = vs2;
    r->hdr[r->nh].vl = vl2;
    r->nh++;
    return PARSE_MORE;
}

static uint32_t push_byte(Req *r, uint8_t b) {
    if (r->state == 2) {
        return PARSE_DONE;
    }
    if (r->state == 3) {
        return r->err;
    }
    if (r->n >= 8192) {
        r->state = 3;
        r->err = 413;
        return 413;
    }
    r->raw[r->n++] = b;
    if (b != 10) {
        return PARSE_MORE;
    }
    uint32_t le = r->n - 1;
    if (le > r->ls && le >= 1 && r->raw[le - 1] == 13) {
        le--;
    }
    uint32_t ls2 = r->ls;
    r->ls = r->n;
    if (r->state == 0) {
        return parse_reqline(r, ls2, le);
    }
    if (le == ls2) {
        r->state = 2;
        return PARSE_DONE;
    }
    return parse_header(r, ls2, le);
}

static uint32_t feed_line(Req *r, const char *s) {
    uint32_t st = PARSE_MORE;
    for (const char *p = s; *p; p++) {
        st = push_byte(r, (uint8_t)*p);
    }
    st = push_byte(r, 13);
    st = push_byte(r, 10);
    return st;
}

static uint8_t lower(uint8_t b) {
    return (b >= 65 && b <= 90) ? (uint8_t)(b + 32) : b;
}

static int span_is(const Req *r, uint32_t s, uint32_t l, const char *kw) {
    if (l != (uint32_t)strlen(kw)) {
        return 0;
    }
    for (uint32_t i = 0; i < l; i++) {
        if (r->raw[s + i] != (uint8_t)kw[i]) {
            return 0;
        }
    }
    return 1;
}

static int span_is_ci(const Req *r, uint32_t s, uint32_t l, const char *kw) {
    if (l != (uint32_t)strlen(kw)) {
        return 0;
    }
    for (uint32_t i = 0; i < l; i++) {
        if (lower(r->raw[s + i]) != lower((uint8_t)kw[i])) {
            return 0;
        }
    }
    return 1;
}

static int method_is(const Req *r, const char *m) {
    return span_is(r, r->ms, r->ml, m);
}

static int path_is(const Req *r, const char *p) {
    return span_is(r, r->ps, r->pl, p);
}

static int version_is(const Req *r, const char *v) {
    return span_is(r, r->vs, r->vl, v);
}

static int path_starts(const Req *r, const char *pre) {
    uint32_t pl = (uint32_t)strlen(pre);
    if (r->pl < pl) {
        return 0;
    }
    return span_is(r, r->ps, pl, pre);
}

/* хвост пути после skip байт; -1 — нет или длиннее 64 (None) */
static int32_t path_param_len(const Req *r, uint32_t skip) {
    if (r->pl <= skip || r->pl - skip > 64) {
        return -1;
    }
    return (int32_t)(r->pl - skip);
}

static uint32_t find_header(const Req *r, const char *name) {
    for (uint32_t i = 0; i < r->nh; i++) {
        if (span_is_ci(r, r->hdr[i].ns, r->hdr[i].nl, name)) {
            return i;
        }
    }
    return HTTP_NONE;
}

static int header_val_is(const Req *r, uint32_t i, const char *v) {
    return span_is_ci(r, r->hdr[i].vs, r->hdr[i].vl, v);
}

static int wants_close(const Req *r) {
    uint32_t c = find_header(r, "connection");
    if (c != HTTP_NONE && c < 64) {
        if (header_val_is(r, c, "close")) {
            return 1;
        }
        if (header_val_is(r, c, "keep-alive")) {
            return 0;
        }
    }
    return version_is(r, "HTTP/1.0");
}

static uint32_t route_code(const Req *r) {
    if (path_is(r, "/")) {
        return 200;
    }
    if (path_starts(r, "/greet/")) {
        return 201;
    }
    return 404;
}

static uint32_t profile_a(Req *r, uint32_t k) {
    char line[64];
    req_reset(r);
    snprintf(line, sizeof(line), "GET /greet/user%u HTTP/1.1", k);
    feed_line(r, line);
    feed_line(r, "Host: bench.local");
    feed_line(r, "User-Agent: eat-bench/1.0");
    feed_line(r, "Accept: */*");
    feed_line(r, "Connection: keep-alive");
    uint32_t st = feed_line(r, "");
    uint32_t acc = st * 7 + r->nh;
    if (method_is(r, "GET")) {
        acc += route_code(r);
    }
    int32_t pl = path_param_len(r, 7);
    if (pl >= 0) {
        acc += (uint32_t)pl;
    }
    if (!wants_close(r)) {
        acc += 1;
    }
    uint32_t c = find_header(r, "connection");
    if (c != HTTP_NONE) {
        acc += c;
    }
    return acc;
}

static uint32_t profile_b(Req *r, uint32_t k) {
    char line[64];
    req_reset(r);
    feed_line(r, "POST /api/items HTTP/1.1");
    feed_line(r, "Content-Type: application/json");
    snprintf(line, sizeof(line), "X-Trace-Id: t-%u", k);
    feed_line(r, line);
    feed_line(r, "Connection: close");
    uint32_t st = feed_line(r, "");
    uint32_t acc = st * 7 + r->nh + route_code(r);
    if (wants_close(r)) {
        acc += 2;
    }
    uint32_t t = find_header(r, "x-trace-id");
    if (t != HTTP_NONE && t < 64) {
        acc += r->hdr[t].vl;
    }
    return acc;
}

static uint32_t profile_c(Req *r, uint32_t k) {
    char line[64];
    req_reset(r);
    snprintf(line, sizeof(line), "BROKEN-%u", k);
    return feed_line(r, line);
}

static uint32_t profile_d(Req *r) {
    req_reset(r);
    feed_line(r, "GET /nope HTTP/1.0");
    uint32_t st = feed_line(r, "");
    uint32_t acc = st * 7 + route_code(r);
    if (wants_close(r)) {
        acc += 3;
    }
    return acc;
}

int main(void) {
    uint32_t acc = 0;
    Req r;
    req_new(&r);
    for (uint32_t rep = 0; rep < REPEAT; rep++) {
        for (uint32_t k = 0; k < 500; k++) {
            acc = (acc * 31 + profile_a(&r, k)) % 65536;
            acc = (acc * 31 + profile_b(&r, k)) % 65536;
            acc = (acc * 31 + profile_c(&r, k)) % 65536;
            acc = (acc * 31 + profile_d(&r)) % 65536;
        }
    }
    printf("checksum %u\n", acc);
    return 0;
}
