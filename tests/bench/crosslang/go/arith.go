// Порт tests/bench/programs/ArithBench.eat 1:1 — целочисленная
// арифметика в горячем цикле. Вывод обязан совпасть байт-в-байт
// с EATLang-оригиналом при том же REPEAT.
package main

import "fmt"

const REPEAT uint32 = 1

func work(seed uint32) uint32 {
	acc := seed
	for k := uint32(0); k < 1000; k++ {
		for i := uint32(0); i < 1000; i++ {
			acc = (acc*31 + i) % 65536
		}
	}
	return acc
}

func main() {
	acc := uint32(7)
	for r := uint32(0); r < REPEAT; r++ {
		acc = work(acc) % 65536
	}
	fmt.Printf("checksum %d\n", acc)
}
