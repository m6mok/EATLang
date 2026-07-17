# Порт tests/bench/programs/HttpBench.eat 1:1 (методика CROSSLANG):
# тот же HTTP-парсер, что lib/Http.eat, та же чек-сумма.

REPEAT = 1

HTTP_NONE = 0xFFFFFFFF
PARSE_MORE = 0
PARSE_DONE = 1


class Req:
    __slots__ = ("raw", "n", "state", "ls", "ms", "ml", "ps", "pl",
                 "vs", "vl", "hdr", "nh", "err")

    def __init__(self):
        self.raw = bytearray(8192)
        self.n = 0
        self.state = 0
        self.ls = 0
        self.ms = self.ml = self.ps = self.pl = self.vs = self.vl = 0
        self.hdr = []
        self.nh = 0
        self.err = 0

    # Зеркало Req.reset (OPTIMIZATIONS §8.2): скалярные поля в 0, raw
    # не трогается — кадр переиспользуется; hdr здесь список (аналог
    # nh = 0 при инварианте len(hdr) == nh — очистка).
    def reset(self):
        self.n = 0
        self.state = 0
        self.ls = 0
        self.ms = self.ml = self.ps = self.pl = self.vs = self.vl = 0
        del self.hdr[:]
        self.nh = 0
        self.err = 0

    def find_sp(self, b0, e0):
        for i in range(b0, e0):
            if self.raw[i] == 32:
                return i
        return HTTP_NONE

    def parse_reqline(self, ls2, le):
        sp1 = self.find_sp(ls2, le)
        sp2 = HTTP_NONE
        bad = sp1 == HTTP_NONE
        if not bad:
            sp2 = self.find_sp(sp1 + 1, le)
            bad = sp2 == HTTP_NONE
        if not bad:
            bad = (sp1 == ls2 or sp2 == sp1 + 1 or sp2 + 1 == le
                   or self.find_sp(sp2 + 1, le) != HTTP_NONE)
        if bad:
            self.state = 3
            self.err = 400
            return 400
        self.ms, self.ml = ls2, sp1 - ls2
        self.ps, self.pl = sp1 + 1, sp2 - sp1 - 1
        self.vs, self.vl = sp2 + 1, le - sp2 - 1
        self.state = 1
        return PARSE_MORE

    def parse_header(self, ls2, le):
        if self.nh >= 64:
            self.state = 3
            self.err = 431
            return 431
        colon = HTTP_NONE
        for i in range(ls2, le):
            if self.raw[i] == 58:
                colon = i
                break
        if colon == HTTP_NONE or colon == ls2:
            self.state = 3
            self.err = 400
            return 400
        vs2, vl2 = colon + 1, le - colon - 1
        while vl2 > 0 and self.raw[vs2] in (32, 9):
            vs2 += 1
            vl2 -= 1
        while vl2 > 0 and self.raw[vs2 + vl2 - 1] in (32, 9):
            vl2 -= 1
        self.hdr.append((ls2, colon - ls2, vs2, vl2))
        self.nh += 1
        return PARSE_MORE

    def push_byte(self, b):
        if self.state == 2:
            return PARSE_DONE
        if self.state == 3:
            return self.err
        if self.n >= 8192:
            self.state = 3
            self.err = 413
            return 413
        self.raw[self.n] = b
        self.n += 1
        if b != 10:
            return PARSE_MORE
        le = self.n - 1
        if le > self.ls and le >= 1 and self.raw[le - 1] == 13:
            le -= 1
        ls2 = self.ls
        self.ls = self.n
        if self.state == 0:
            return self.parse_reqline(ls2, le)
        if le == ls2:
            self.state = 2
            return PARSE_DONE
        return self.parse_header(ls2, le)

    def feed_line(self, s):
        st = PARSE_MORE
        for ch in s.encode():
            st = self.push_byte(ch)
        st = self.push_byte(13)
        st = self.push_byte(10)
        return st

    def span_is(self, s, l, kw):
        b = kw.encode()
        return l == len(b) and bytes(self.raw[s:s + l]) == b

    def span_is_ci(self, s, l, kw):
        b = kw.encode().lower()
        return l == len(b) and bytes(self.raw[s:s + l]).lower() == b

    def method_is(self, m):
        return self.span_is(self.ms, self.ml, m)

    def path_is(self, p):
        return self.span_is(self.ps, self.pl, p)

    def version_is(self, v):
        return self.span_is(self.vs, self.vl, v)

    def path_starts(self, pre):
        return self.pl >= len(pre) and self.span_is(self.ps, len(pre), pre)

    def path_param_len(self, skip):
        if self.pl <= skip or self.pl - skip > 64:
            return -1
        return self.pl - skip

    def find_header(self, name):
        for i in range(self.nh):
            h = self.hdr[i]
            if self.span_is_ci(h[0], h[1], name):
                return i
        return HTTP_NONE

    def header_val_is(self, i, v):
        h = self.hdr[i]
        return self.span_is_ci(h[2], h[3], v)

    def wants_close(self):
        c = self.find_header("connection")
        if c != HTTP_NONE and c < 64:
            if self.header_val_is(c, "close"):
                return True
            if self.header_val_is(c, "keep-alive"):
                return False
        return self.version_is("HTTP/1.0")


def route_code(r):
    if r.path_is("/"):
        return 200
    if r.path_starts("/greet/"):
        return 201
    return 404


def profile_a(r, k):
    r.reset()
    r.feed_line(f"GET /greet/user{k} HTTP/1.1")
    r.feed_line("Host: bench.local")
    r.feed_line("User-Agent: eat-bench/1.0")
    r.feed_line("Accept: */*")
    r.feed_line("Connection: keep-alive")
    st = r.feed_line("")
    acc = st * 7 + r.nh
    if r.method_is("GET"):
        acc += route_code(r)
    pl = r.path_param_len(7)
    if pl >= 0:
        acc += pl
    if not r.wants_close():
        acc += 1
    c = r.find_header("connection")
    if c != HTTP_NONE:
        acc += c
    return acc


def profile_b(r, k):
    r.reset()
    r.feed_line("POST /api/items HTTP/1.1")
    r.feed_line("Content-Type: application/json")
    r.feed_line(f"X-Trace-Id: t-{k}")
    r.feed_line("Connection: close")
    st = r.feed_line("")
    acc = st * 7 + r.nh + route_code(r)
    if r.wants_close():
        acc += 2
    t = r.find_header("x-trace-id")
    if t != HTTP_NONE and t < 64:
        acc += r.hdr[t][3]
    return acc


def profile_c(r, k):
    r.reset()
    return r.feed_line(f"BROKEN-{k}")


def profile_d(r):
    r.reset()
    r.feed_line("GET /nope HTTP/1.0")
    st = r.feed_line("")
    acc = st * 7 + route_code(r)
    if r.wants_close():
        acc += 3
    return acc


def main():
    acc = 0
    r = Req()
    for _ in range(REPEAT):
        for k in range(500):
            acc = (acc * 31 + profile_a(r, k)) % 65536
            acc = (acc * 31 + profile_b(r, k)) % 65536
            acc = (acc * 31 + profile_c(r, k)) % 65536
            acc = (acc * 31 + profile_d(r)) % 65536
    print(f"checksum {acc}")


main()
