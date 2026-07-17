// Порт tests/bench/programs/BankBench.eat 1:1 — банкованная память
// pool[a/4096][a%4096], адрес зависит от loop-carried acc. Вывод
// обязан совпасть байт-в-байт с EATLang-оригиналом при том же REPEAT.
package main

import "fmt"

const REPEAT uint32 = 1

func work(seed uint32) uint32 {
	var pool [8][4096]uint32
	acc := seed
	for k := uint32(0); k < 200; k++ {
		for i := uint32(0); i < 1000; i++ {
			a := (acc + i*37) % 32768
			pool[a/4096][a%4096] = (acc + i) % 65536
			b := (a*17 + 5) % 32768
			acc = (acc + pool[b/4096][b%4096]) % 65536
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
