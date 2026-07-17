// Порт tests/bench/programs/U128DivBench.eat 1:1 — деление 128 бит:
// EATLang — полный сдвиговый divrem (128 итераций) и divrem_32 по
// лимбам; у Go нативного 128-бит нет — идиоматичная цепочка из двух
// bits.Div64 (делитель 64-битный, остаток первой ступени < d, паника
// невозможна). Вывод обязан совпасть байт-в-байт при том же REPEAT.
package main

import (
	"fmt"
	"math/bits"
)

const REPEAT uint32 = 1

func lcg(x uint64) uint64 {
	return (x*31 + 7) % 281474976710656
}

func div128(hi, lo, d uint64) (uint64, uint64, uint64) {
	qhi, r1 := bits.Div64(0, hi, d)
	qlo, r := bits.Div64(r1, lo, d)
	return qhi, qlo, r
}

func work(seed uint64) uint64 {
	x := seed + 3
	acc := uint64(0)
	for i := uint32(0); i < 400; i++ {
		x = lcg(x)
		hi := x
		x = lcg(x)
		lo := x
		x = lcg(x)
		d := x | 1
		qhi, qlo, r := div128(hi, lo, d)
		acc = acc ^ qlo ^ qhi ^ r
	}
	for i := uint32(0); i < 4000; i++ {
		x = lcg(x)
		hi := x
		x = lcg(x)
		lo := x
		x = lcg(x)
		d32 := (x & 4294967295) | 1
		qhi, qlo, r := div128(hi, lo, d32)
		acc = acc ^ qlo ^ qhi ^ r
	}
	return acc % 65536
}

func main() {
	acc := uint64(7)
	for r := uint32(0); r < REPEAT; r++ {
		acc = work(acc)
	}
	c := uint32(acc)
	fmt.Printf("checksum %d\n", c)
}
