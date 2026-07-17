// Порт tests/bench/programs/TodoBench.eat 1:1 — ядро RESTful TODO-list:
// bounded-пул из 64 слотов под потоком create/toggle/serialize/remove.
// Вывод обязан совпасть байт-в-байт с EATLang-оригиналом при том же
// REPEAT.
package main

import "fmt"

const REPEAT uint32 = 1
const CAP uint32 = 64
const TLEN uint32 = 16

type Store struct {
	id     [64]uint32
	title  [1024]uint8
	done   [64]uint8
	used   [64]uint8
	nextID uint32
}

func (s *Store) create(k, seed uint32) uint32 {
	slot := k % CAP
	base := slot * TLEN
	id := s.nextID
	s.id[slot] = id
	for j := uint32(0); j < 16; j++ {
		s.title[base+j] = uint8(65 + (seed+k+j*7)%26)
	}
	s.done[slot] = uint8(k % 2)
	s.used[slot] = 1
	s.nextID++
	return id
}

func (s *Store) toggle(idx uint32) {
	if s.done[idx] == 0 {
		s.done[idx] = 1
	} else {
		s.done[idx] = 0
	}
}

func (s *Store) remove(idx uint32) { s.used[idx] = 0 }

func (s *Store) serialize() uint32 {
	var sum uint32 = 0
	for slot := uint32(0); slot < 64; slot++ {
		if s.used[slot] == 1 {
			m := s.id[slot]
			for d := 0; d < 10; d++ {
				if m == 0 {
					break
				}
				sum = (sum*31 + m%10) % 65536
				m = m / 10
			}
			base := slot * TLEN
			for j := uint32(0); j < 16; j++ {
				sum = (sum*31 + uint32(s.title[base+j])) % 65536
			}
			sum = (sum*31 + uint32(s.done[slot])) % 65536
		}
	}
	return sum
}

func main() {
	s := Store{nextID: 1}
	var acc uint32 = 0
	for r := uint32(0); r < REPEAT; r++ {
		for k := uint32(0); k < 2048; k++ {
			seed := acc
			id := s.create(k, seed)
			acc = (acc*31 + id) % 65536
			t := (k * 3) % CAP
			s.toggle(t)
			if k%8 == 0 {
				acc = (acc*31 + s.serialize()) % 65536
			}
			if k%16 == 0 {
				rr := (k * 5) % CAP
				s.remove(rr)
			}
		}
	}
	fmt.Printf("checksum %d\n", acc)
}
