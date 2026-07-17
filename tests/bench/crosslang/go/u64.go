// Порт tests/bench/programs/U64Bench.eat 1:1 — 64-битная беззнаковая
// арифметика, деление, широкие сдвиги. Вывод обязан совпасть байт-в-байт
// с EATLang-оригиналом при том же REPEAT.
package main

import "fmt"

const REPEAT uint32 = 1

func work(seed uint64) uint64 {
	acc := seed
	for k := uint32(0); k < 200; k++ {
		for i := uint64(0); i < 1000; i++ {
			acc = (acc*31 + i) % 281474976710656
			acc = acc ^ (acc >> 33)
			acc = acc + acc/((i&7)+2)
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
