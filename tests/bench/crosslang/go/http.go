// Порт tests/bench/programs/HttpBench.eat 1:1 (методика CROSSLANG):
// тот же HTTP-парсер, что lib/Http.eat, та же чек-сумма.
package main

import "fmt"

const REPEAT uint32 = 1

const httpNone uint32 = 0xffffffff
const parseMore uint32 = 0
const parseDone uint32 = 1

type header struct {
	ns, nl, vs, vl uint32
}

type req struct {
	raw   [8192]uint8
	n     uint32
	state uint32
	ls    uint32
	ms, ml, ps, pl, vs, vl uint32
	hdr   [64]header
	nh    uint32
	err   uint32
}

// Зеркало Req.reset (OPTIMIZATIONS §8.2): скалярные поля в 0,
// raw/hdr не трогаются — кадр переиспользуется между запросами.
func (r *req) reset() {
	r.n = 0
	r.state = 0
	r.ls = 0
	r.ms, r.ml, r.ps, r.pl, r.vs, r.vl = 0, 0, 0, 0, 0, 0
	r.nh = 0
	r.err = 0
}

func (r *req) findSp(b0, e0 uint32) uint32 {
	for i := b0; i < e0; i++ {
		if r.raw[i] == 32 {
			return i
		}
	}
	return httpNone
}

func (r *req) parseReqline(ls2, le uint32) uint32 {
	sp1 := r.findSp(ls2, le)
	sp2 := httpNone
	bad := sp1 == httpNone
	if !bad {
		sp2 = r.findSp(sp1+1, le)
		bad = sp2 == httpNone
	}
	if !bad {
		bad = sp1 == ls2 || sp2 == sp1+1 || sp2+1 == le ||
			r.findSp(sp2+1, le) != httpNone
	}
	if bad {
		r.state = 3
		r.err = 400
		return 400
	}
	r.ms, r.ml = ls2, sp1-ls2
	r.ps, r.pl = sp1+1, sp2-sp1-1
	r.vs, r.vl = sp2+1, le-sp2-1
	r.state = 1
	return parseMore
}

func (r *req) parseHeader(ls2, le uint32) uint32 {
	if r.nh >= 64 {
		r.state = 3
		r.err = 431
		return 431
	}
	colon := httpNone
	for i := ls2; i < le; i++ {
		if r.raw[i] == 58 {
			colon = i
			break
		}
	}
	if colon == httpNone || colon == ls2 {
		r.state = 3
		r.err = 400
		return 400
	}
	vs2, vl2 := colon+1, le-colon-1
	for vl2 > 0 && (r.raw[vs2] == 32 || r.raw[vs2] == 9) {
		vs2++
		vl2--
	}
	for vl2 > 0 {
		tb := r.raw[vs2+vl2-1]
		if tb != 32 && tb != 9 {
			break
		}
		vl2--
	}
	r.hdr[r.nh] = header{ls2, colon - ls2, vs2, vl2}
	r.nh++
	return parseMore
}

func (r *req) pushByte(b uint8) uint32 {
	if r.state == 2 {
		return parseDone
	}
	if r.state == 3 {
		return r.err
	}
	if r.n >= 8192 {
		r.state = 3
		r.err = 413
		return 413
	}
	r.raw[r.n] = b
	r.n++
	if b != 10 {
		return parseMore
	}
	le := r.n - 1
	if le > r.ls && le >= 1 && r.raw[le-1] == 13 {
		le--
	}
	ls2 := r.ls
	r.ls = r.n
	if r.state == 0 {
		return r.parseReqline(ls2, le)
	}
	if le == ls2 {
		r.state = 2
		return parseDone
	}
	return r.parseHeader(ls2, le)
}

func (r *req) feedLine(s string) uint32 {
	st := parseMore
	for i := 0; i < len(s); i++ {
		st = r.pushByte(s[i])
	}
	st = r.pushByte(13)
	st = r.pushByte(10)
	return st
}

func lower(b uint8) uint8 {
	if b >= 65 && b <= 90 {
		return b + 32
	}
	return b
}

func (r *req) spanIs(s, l uint32, kw string) bool {
	if l != uint32(len(kw)) {
		return false
	}
	for i := uint32(0); i < l; i++ {
		if r.raw[s+i] != kw[i] {
			return false
		}
	}
	return true
}

func (r *req) spanIsCi(s, l uint32, kw string) bool {
	if l != uint32(len(kw)) {
		return false
	}
	for i := uint32(0); i < l; i++ {
		if lower(r.raw[s+i]) != lower(kw[i]) {
			return false
		}
	}
	return true
}

func (r *req) methodIs(m string) bool  { return r.spanIs(r.ms, r.ml, m) }
func (r *req) pathIs(p string) bool    { return r.spanIs(r.ps, r.pl, p) }
func (r *req) versionIs(v string) bool { return r.spanIs(r.vs, r.vl, v) }

func (r *req) pathStarts(pre string) bool {
	if r.pl < uint32(len(pre)) {
		return false
	}
	return r.spanIs(r.ps, uint32(len(pre)), pre)
}

// хвост пути после skip байт; -1 — нет или длиннее 64 (None)
func (r *req) pathParamLen(skip uint32) int32 {
	if r.pl <= skip || r.pl-skip > 64 {
		return -1
	}
	return int32(r.pl - skip)
}

func (r *req) findHeader(name string) uint32 {
	for i := uint32(0); i < r.nh; i++ {
		if r.spanIsCi(r.hdr[i].ns, r.hdr[i].nl, name) {
			return i
		}
	}
	return httpNone
}

func (r *req) headerValIs(i uint32, v string) bool {
	return r.spanIsCi(r.hdr[i].vs, r.hdr[i].vl, v)
}

func (r *req) wantsClose() bool {
	c := r.findHeader("connection")
	if c != httpNone && c < 64 {
		if r.headerValIs(c, "close") {
			return true
		}
		if r.headerValIs(c, "keep-alive") {
			return false
		}
	}
	return r.versionIs("HTTP/1.0")
}

func routeCode(r *req) uint32 {
	if r.pathIs("/") {
		return 200
	}
	if r.pathStarts("/greet/") {
		return 201
	}
	return 404
}

func profileA(r *req, k uint32) uint32 {
	r.reset()
	r.feedLine(fmt.Sprintf("GET /greet/user%d HTTP/1.1", k))
	r.feedLine("Host: bench.local")
	r.feedLine("User-Agent: eat-bench/1.0")
	r.feedLine("Accept: */*")
	r.feedLine("Connection: keep-alive")
	st := r.feedLine("")
	acc := st*7 + r.nh
	if r.methodIs("GET") {
		acc += routeCode(r)
	}
	if pl := r.pathParamLen(7); pl >= 0 {
		acc += uint32(pl)
	}
	if !r.wantsClose() {
		acc++
	}
	if c := r.findHeader("connection"); c != httpNone {
		acc += c
	}
	return acc
}

func profileB(r *req, k uint32) uint32 {
	r.reset()
	r.feedLine("POST /api/items HTTP/1.1")
	r.feedLine("Content-Type: application/json")
	r.feedLine(fmt.Sprintf("X-Trace-Id: t-%d", k))
	r.feedLine("Connection: close")
	st := r.feedLine("")
	acc := st*7 + r.nh + routeCode(r)
	if r.wantsClose() {
		acc += 2
	}
	if t := r.findHeader("x-trace-id"); t != httpNone && t < 64 {
		acc += r.hdr[t].vl
	}
	return acc
}

func profileC(r *req, k uint32) uint32 {
	r.reset()
	return r.feedLine(fmt.Sprintf("BROKEN-%d", k))
}

func profileD(r *req) uint32 {
	r.reset()
	r.feedLine("GET /nope HTTP/1.0")
	st := r.feedLine("")
	acc := st*7 + routeCode(r)
	if r.wantsClose() {
		acc += 3
	}
	return acc
}

func profileE(r *req, slots *[64]uint32, k uint32) uint32 {
	r.reset()
	r.feedLine(fmt.Sprintf("PUT /todos/%d HTTP/1.1", k))
	r.feedLine("Host: bench.local")
	r.feedLine("Connection: close")
	st := r.feedLine("")
	acc := st*7 + r.nh + routeCode(r)
	slot := k % 64
	slots[slot] = (slots[slot] + acc + 1) % 65536
	return acc + slots[slot]
}

func main() {
	var acc uint32
	var r req
	var slots [64]uint32
	for rep := uint32(0); rep < REPEAT; rep++ {
		for k := uint32(0); k < 500; k++ {
			acc = (acc*31 + profileA(&r, k)) % 65536
			acc = (acc*31 + profileB(&r, k)) % 65536
			acc = (acc*31 + profileC(&r, k)) % 65536
			acc = (acc*31 + profileD(&r)) % 65536
			acc = (acc*31 + profileE(&r, &slots, k)) % 65536
		}
	}
	fmt.Printf("checksum %d\n", acc)
}
