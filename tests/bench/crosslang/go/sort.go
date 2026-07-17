// Порт tests/bench/programs/SortBench.eat 1:1 — сортировка вставками
// с data-dependent ветвлениями и взвешенной свёрткой результата.
// Вывод обязан совпасть байт-в-байт с EATLang-оригиналом при том же
// REPEAT.
package main

import "fmt"

const REPEAT uint32 = 1

func fill(seed, k uint32) uint32 {
	return (seed*31 + k + 1) % 65536
}

func main() {
	var a [32]uint32
	acc := uint32(7)
	for r := uint32(0); r < REPEAT; r++ {
		for s := uint32(0); s < 500; s++ {
			for i := uint32(0); i < 32; i++ {
				acc = fill(acc, i)
				a[i] = acc
			}
			for i := uint32(1); i < 32; i++ {
				v := a[i]
				j := i
				for t := uint32(0); t < 32; t++ {
					move := false
					if j > 0 {
						if a[j-1] > v {
							move = true
						}
					}
					if move {
						a[j] = a[j-1]
						j = j - 1
					} else {
						break
					}
				}
				a[j] = v
			}
			for i := uint32(0); i < 32; i++ {
				acc = (acc*3 + a[i]) % 65536
			}
		}
	}
	fmt.Printf("checksum %d\n", acc)
}
