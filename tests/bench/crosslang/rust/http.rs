// Порт tests/bench/programs/HttpBench.eat 1:1 (методика CROSSLANG):
// тот же HTTP-парсер, что lib/Http.eat, та же чек-сумма.

const REPEAT: u32 = 1;

const HTTP_NONE: u32 = 0xffff_ffff;
const PARSE_MORE: u32 = 0;
const PARSE_DONE: u32 = 1;

#[derive(Clone, Copy, Default)]
struct Header {
    ns: u32,
    nl: u32,
    vs: u32,
    vl: u32,
}

struct Req {
    raw: [u8; 8192],
    n: u32,
    state: u32,
    ls: u32,
    ms: u32,
    ml: u32,
    ps: u32,
    pl: u32,
    vs: u32,
    vl: u32,
    hdr: [Header; 64],
    nh: u32,
    err: u32,
}

impl Req {
    fn new() -> Req {
        Req {
            raw: [0; 8192],
            n: 0,
            state: 0,
            ls: 0,
            ms: 0,
            ml: 0,
            ps: 0,
            pl: 0,
            vs: 0,
            vl: 0,
            hdr: [Header::default(); 64],
            nh: 0,
            err: 0,
        }
    }

    fn find_sp(&self, b0: u32, e0: u32) -> u32 {
        for i in b0..e0 {
            if self.raw[i as usize] == 32 {
                return i;
            }
        }
        HTTP_NONE
    }

    fn parse_reqline(&mut self, ls2: u32, le: u32) -> u32 {
        let sp1 = self.find_sp(ls2, le);
        let mut sp2 = HTTP_NONE;
        let mut bad = sp1 == HTTP_NONE;
        if !bad {
            sp2 = self.find_sp(sp1 + 1, le);
            bad = sp2 == HTTP_NONE;
        }
        if !bad {
            bad = sp1 == ls2
                || sp2 == sp1 + 1
                || sp2 + 1 == le
                || self.find_sp(sp2 + 1, le) != HTTP_NONE;
        }
        if bad {
            self.state = 3;
            self.err = 400;
            return 400;
        }
        self.ms = ls2;
        self.ml = sp1 - ls2;
        self.ps = sp1 + 1;
        self.pl = sp2 - sp1 - 1;
        self.vs = sp2 + 1;
        self.vl = le - sp2 - 1;
        self.state = 1;
        PARSE_MORE
    }

    fn parse_header(&mut self, ls2: u32, le: u32) -> u32 {
        if self.nh >= 64 {
            self.state = 3;
            self.err = 431;
            return 431;
        }
        let mut colon = HTTP_NONE;
        for i in ls2..le {
            if self.raw[i as usize] == 58 {
                colon = i;
                break;
            }
        }
        if colon == HTTP_NONE || colon == ls2 {
            self.state = 3;
            self.err = 400;
            return 400;
        }
        let mut vs2 = colon + 1;
        let mut vl2 = le - vs2;
        while vl2 > 0 {
            let b = self.raw[vs2 as usize];
            if b != 32 && b != 9 {
                break;
            }
            vs2 += 1;
            vl2 -= 1;
        }
        while vl2 > 0 {
            let tb = self.raw[(vs2 + vl2 - 1) as usize];
            if tb != 32 && tb != 9 {
                break;
            }
            vl2 -= 1;
        }
        self.hdr[self.nh as usize] = Header {
            ns: ls2,
            nl: colon - ls2,
            vs: vs2,
            vl: vl2,
        };
        self.nh += 1;
        PARSE_MORE
    }

    fn push_byte(&mut self, b: u8) -> u32 {
        if self.state == 2 {
            return PARSE_DONE;
        }
        if self.state == 3 {
            return self.err;
        }
        if self.n >= 8192 {
            self.state = 3;
            self.err = 413;
            return 413;
        }
        self.raw[self.n as usize] = b;
        self.n += 1;
        if b != 10 {
            return PARSE_MORE;
        }
        let mut le = self.n - 1;
        if le > self.ls && le >= 1 && self.raw[(le - 1) as usize] == 13 {
            le -= 1;
        }
        let ls2 = self.ls;
        self.ls = self.n;
        if self.state == 0 {
            return self.parse_reqline(ls2, le);
        }
        if le == ls2 {
            self.state = 2;
            return PARSE_DONE;
        }
        self.parse_header(ls2, le)
    }

    fn feed_line(&mut self, s: &str) -> u32 {
        for &b in s.as_bytes() {
            self.push_byte(b);
        }
        self.push_byte(13);
        self.push_byte(10)
    }

    fn span_is(&self, s: u32, l: u32, kw: &str) -> bool {
        let kb = kw.as_bytes();
        if l as usize != kb.len() {
            return false;
        }
        for i in 0..l {
            if self.raw[(s + i) as usize] != kb[i as usize] {
                return false;
            }
        }
        true
    }

    fn span_is_ci(&self, s: u32, l: u32, kw: &str) -> bool {
        let kb = kw.as_bytes();
        if l as usize != kb.len() {
            return false;
        }
        for i in 0..l {
            if lower(self.raw[(s + i) as usize]) != lower(kb[i as usize]) {
                return false;
            }
        }
        true
    }

    fn method_is(&self, m: &str) -> bool {
        self.span_is(self.ms, self.ml, m)
    }

    fn path_is(&self, p: &str) -> bool {
        self.span_is(self.ps, self.pl, p)
    }

    fn version_is(&self, v: &str) -> bool {
        self.span_is(self.vs, self.vl, v)
    }

    fn path_starts(&self, pre: &str) -> bool {
        if (self.pl as usize) < pre.len() {
            return false;
        }
        self.span_is(self.ps, pre.len() as u32, pre)
    }

    // хвост пути после skip байт; -1 — нет или длиннее 64 (None)
    fn path_param_len(&self, skip: u32) -> i32 {
        if self.pl <= skip || self.pl - skip > 64 {
            return -1;
        }
        (self.pl - skip) as i32
    }

    fn find_header(&self, name: &str) -> u32 {
        for i in 0..self.nh {
            let h = self.hdr[i as usize];
            if self.span_is_ci(h.ns, h.nl, name) {
                return i;
            }
        }
        HTTP_NONE
    }

    fn header_val_is(&self, i: u32, v: &str) -> bool {
        let h = self.hdr[i as usize];
        self.span_is_ci(h.vs, h.vl, v)
    }

    fn wants_close(&self) -> bool {
        let c = self.find_header("connection");
        if c != HTTP_NONE && c < 64 {
            if self.header_val_is(c, "close") {
                return true;
            }
            if self.header_val_is(c, "keep-alive") {
                return false;
            }
        }
        self.version_is("HTTP/1.0")
    }
}

fn lower(b: u8) -> u8 {
    if (65..=90).contains(&b) {
        b + 32
    } else {
        b
    }
}

fn route_code(r: &Req) -> u32 {
    if r.path_is("/") {
        return 200;
    }
    if r.path_starts("/greet/") {
        return 201;
    }
    404
}

fn profile_a(k: u32) -> u32 {
    let mut r = Req::new();
    r.feed_line(&format!("GET /greet/user{} HTTP/1.1", k));
    r.feed_line("Host: bench.local");
    r.feed_line("User-Agent: eat-bench/1.0");
    r.feed_line("Accept: */*");
    r.feed_line("Connection: keep-alive");
    let st = r.feed_line("");
    let mut acc = st * 7 + r.nh;
    if r.method_is("GET") {
        acc += route_code(&r);
    }
    let pl = r.path_param_len(7);
    if pl >= 0 {
        acc += pl as u32;
    }
    if !r.wants_close() {
        acc += 1;
    }
    let c = r.find_header("connection");
    if c != HTTP_NONE {
        acc += c;
    }
    acc
}

fn profile_b(k: u32) -> u32 {
    let mut r = Req::new();
    r.feed_line("POST /api/items HTTP/1.1");
    r.feed_line("Content-Type: application/json");
    r.feed_line(&format!("X-Trace-Id: t-{}", k));
    r.feed_line("Connection: close");
    let st = r.feed_line("");
    let mut acc = st * 7 + r.nh + route_code(&r);
    if r.wants_close() {
        acc += 2;
    }
    let t = r.find_header("x-trace-id");
    if t != HTTP_NONE && t < 64 {
        acc += r.hdr[t as usize].vl;
    }
    acc
}

fn profile_c(k: u32) -> u32 {
    let mut r = Req::new();
    r.feed_line(&format!("BROKEN-{}", k))
}

fn profile_d() -> u32 {
    let mut r = Req::new();
    r.feed_line("GET /nope HTTP/1.0");
    let st = r.feed_line("");
    let mut acc = st * 7 + route_code(&r);
    if r.wants_close() {
        acc += 3;
    }
    acc
}

fn main() {
    let mut acc: u32 = 0;
    for _ in 0..REPEAT {
        for k in 0..500u32 {
            acc = (acc * 31 + profile_a(k)) % 65536;
            acc = (acc * 31 + profile_b(k)) % 65536;
            acc = (acc * 31 + profile_c(k)) % 65536;
            acc = (acc * 31 + profile_d()) % 65536;
        }
    }
    println!("checksum {}", acc);
}
