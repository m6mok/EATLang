// Порт tests/bench/programs/U128Bench.eat 1:1 — 128-битный микс без
// деления: шаг LCG128 (константы PCG64) + точное произведение 64x64.
// EATLang считает лимбами lib/U128.eat; у Go нативного 128-бит нет —
// идиоматичная пара uint64 через math/bits (Mul64/Add64, как в
// реализациях PCG). Вывод обязан совпасть байт-в-байт при том же
// REPEAT.
package main

import (
	"fmt"
	"math/bits"
)

const REPEAT uint32 = 1

const (
	mcHi  uint64 = 2549297995355413924
	mcLo  uint64 = 4865540595714422341
	incLo uint64 = 1442695040888963407
)

func work(seed uint64) uint64 {
	shi := seed
	slo := uint64(11634580027462260723)
	acc := uint64(0)
	for k := uint32(0); k < 20; k++ {
		for i := uint32(0); i < 1000; i++ {
			// s = s*mc + inc mod 2^128
			hi, lo := bits.Mul64(slo, mcLo)
			hi += slo*mcHi + shi*mcLo
			lo, c := bits.Add64(lo, incLo, 0)
			hi, _ = bits.Add64(hi, 0, c)
			shi, slo = hi, lo
			phi, plo := bits.Mul64(shi^acc, slo|1)
			acc = acc ^ phi ^ (plo >> 7)
		}
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
