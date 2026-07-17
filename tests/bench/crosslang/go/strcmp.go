// Порт tests/bench/programs/StrCmpBench.eat 1:1 — сборка строки
// конкатенацией (префикс + strconv-десятичное) и посимвольное
// сравнение == с общим префиксом 40+ байт. Вывод обязан совпасть
// байт-в-байт с EATLang-оригиналом при том же REPEAT.
package main

import (
	"fmt"
	"strconv"
)

const REPEAT uint32 = 1

func main() {
	t := "common-prefix-the-quick-brown-fox-jumps-tail-00000"
	acc := uint32(0)
	for r := uint32(0); r < REPEAT; r++ {
		for k := uint32(0); k < 20; k++ {
			for i := uint32(0); i < 1000; i++ {
				acc = (acc*31 + i + k) % 65536
				s := "common-prefix-the-quick-brown-fox-jumps-tail-" +
					strconv.FormatUint(uint64(acc), 10)
				if s == t {
					acc = acc + 7
				}
			}
		}
	}
	fmt.Printf("checksum %d\n", acc)
}
