// Порт tests/bench/programs/BranchBench.eat 1:1 — непредсказуемые
// ветвления, if/elif-диспетчер по битам loop-carried acc. Вывод обязан
// совпасть байт-в-байт с EATLang-оригиналом при том же REPEAT.
package main

import "fmt"

const REPEAT uint32 = 1

func work(seed uint32) uint32 {
	acc := seed + 1
	for k := uint32(0); k < 500; k++ {
		for i := uint32(0); i < 1000; i++ {
			t := (acc >> (i & 7)) & 3
			if t == 0 {
				acc = (acc + i + 1) % 65536
			} else if t == 1 {
				acc = (acc*5 + 3) % 65536
			} else if t == 2 {
				acc = (acc ^ (i & 4095)) % 65536
			} else {
				acc = ((acc >> 1) | 1) % 65536
			}
		}
	}
	return acc
}

func main() {
	acc := uint32(7)
	for r := uint32(0); r < REPEAT; r++ {
		acc = work(acc)
	}
	fmt.Printf("checksum %d\n", acc)
}
