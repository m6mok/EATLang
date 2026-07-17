// Порт examples/mos6502/{Cpu6502,Main}.eat 1:1 — эмулятор MOS 6502
// как макробенч кросс-языкового сравнения. Структура повторяет
// оригинал: та же память mem[65536] в CPU, те же rd/wr/step/exec_*
// с той же логикой ветвлений и теми же масками (& 255 / & 65535).
// Декодер — по структуре опкода aaabbbcc, без таблицы. Вывод отчёта
// обязан совпасть с EATLang-оригиналом байт-в-байт.
package main

import (
	"fmt"
	"io"
	"os"
)

const LOAD uint32 = 1536

type Cpu struct {
	a, x, y, sp, pc  uint32
	c, z, i, d, v, n uint32
	halted           bool
	steps            uint32
	mem              [65536]uint8
}

// --- шина ------------------------------------------------------------

func (self *Cpu) rd(ad uint32) uint32 {
	return uint32(self.mem[ad&65535])
}

func (self *Cpu) rd16(ad uint32) uint32 {
	return self.rd(ad) | (self.rd(ad+1) << 8)
}

func (self *Cpu) wr(ad uint32, val uint32) {
	self.mem[ad&65535] = uint8(val & 255)
}

func (self *Cpu) fetch() uint32 {
	b := self.rd(self.pc)
	self.pc = (self.pc + 1) & 65535
	return b
}

func (self *Cpu) fetch16() uint32 {
	lo := self.fetch()
	hi := self.fetch()
	return lo | (hi << 8)
}

// --- стек ($0100..$01FF) ----------------------------------------------

func (self *Cpu) push(val uint32) {
	self.wr(256|self.sp, val)
	self.sp = (self.sp + 255) & 255
}

func (self *Cpu) pop() uint32 {
	self.sp = (self.sp + 1) & 255
	return self.rd(256 | self.sp)
}

// --- флаги -------------------------------------------------------------

func (self *Cpu) set_nz(val uint32) {
	self.n = val >> 7
	if val == 0 {
		self.z = 1
	} else {
		self.z = 0
	}
}

// Байт P: NV1BDIZC (бит 5 всегда 1, B — только на стеке).
func (self *Cpu) flags_byte(brk uint32) uint32 {
	return (self.n << 7) | (self.v << 6) | 32 | (brk << 4) |
		(self.d << 3) | (self.i << 2) | (self.z << 1) | self.c
}

func (self *Cpu) set_flags(p uint32) {
	self.n = p >> 7
	self.v = (p >> 6) & 1
	self.d = (p >> 3) & 1
	self.i = (p >> 2) & 1
	self.z = (p >> 1) & 1
	self.c = p & 1
}

// --- адресация ---------------------------------------------------------

// Режимы cc=1 по bbb: 0 (zp,X)  1 zp  2 #imm  3 abs  4 (zp),Y
// 5 zp,X  6 abs,Y  7 abs,X. Для #imm операнд лежит по адресу pc.
func (self *Cpu) ea_alu(bbb uint32) uint32 {
	if bbb == 0 {
		p := (self.fetch() + self.x) & 255
		return self.rd(p) | (self.rd((p+1)&255) << 8)
	} else if bbb == 1 {
		return self.fetch()
	} else if bbb == 2 {
		ad := self.pc
		self.pc = (self.pc + 1) & 65535
		return ad
	} else if bbb == 3 {
		return self.fetch16()
	} else if bbb == 4 {
		p2 := self.fetch()
		base := self.rd(p2) | (self.rd((p2+1)&255) << 8)
		return (base + self.y) & 65535
	} else if bbb == 5 {
		return (self.fetch() + self.x) & 255
	} else if bbb == 6 {
		return (self.fetch16() + self.y) & 65535
	}
	return (self.fetch16() + self.x) & 65535
}

// Режимы cc=0/2 по bbb: 0 #imm  1 zp  3 abs  5 zp,idx  7 abs,idx.
// ry=1 — индексирование Y (STX/LDX): zp,Y и abs,Y.
func (self *Cpu) ea_mem(bbb uint32, ry uint32) uint32 {
	var idx uint32 = self.x
	if ry == 1 {
		idx = self.y
	}
	if bbb == 0 {
		ad := self.pc
		self.pc = (self.pc + 1) & 65535
		return ad
	} else if bbb == 1 {
		return self.fetch()
	} else if bbb == 3 {
		return self.fetch16()
	} else if bbb == 5 {
		return (self.fetch() + idx) & 255
	} else if bbb == 7 {
		return (self.fetch16() + idx) & 65535
	}
	self.halted = true
	return 0
}

// --- АЛУ ----------------------------------------------------------------

func (self *Cpu) adc(m uint32) {
	sum := self.a + m + self.c
	if self.d == 1 {
		self.adc_dec(m, sum)
		return
	}
	self.c = sum >> 8
	self.v = ((self.a ^ sum) & (m ^ sum) & 128) >> 7
	self.a = sum & 255
	self.set_nz(self.a)
}

// Десятичный ADC (NMOS): Z — от двоичной суммы, N/V — после
// коррекции младшей тетрады, C — после коррекции старшей.
func (self *Cpu) adc_dec(m uint32, sum uint32) {
	if (sum & 255) == 0 {
		self.z = 1
	} else {
		self.z = 0
	}
	al := (self.a & 15) + (m & 15) + self.c
	if al >= 10 {
		al = ((al + 6) & 15) + 16
	}
	s := (self.a & 240) + (m & 240) + al
	self.n = (s >> 7) & 1
	self.v = (((self.a ^ m) ^ 255) & (self.a ^ s) & 128) >> 7
	if s >= 160 {
		s = s + 96
	}
	if s >= 256 {
		self.c = 1
	} else {
		self.c = 0
	}
	self.a = s & 255
}

// SBC: флаги NZVC всегда от двоичного результата (NMOS);
// в десятичном режиме корректируется только аккумулятор.
func (self *Cpu) sbc(m uint32) {
	borrow := 1 - self.c
	bin := self.a + 256 - m - borrow
	r := bin & 255
	self.c = bin >> 8
	self.v = ((self.a ^ m) & (self.a ^ r) & 128) >> 7
	self.set_nz(r)
	if self.d == 1 {
		al := (self.a & 15) + 16 - (m & 15) - borrow
		ah := (self.a >> 4) + 16 - (m >> 4)
		if al < 16 {
			al = (al + 10) & 15
			ah = ah - 1
		} else {
			al = al & 15
		}
		if ah < 16 {
			ah = (ah + 10) & 15
		} else {
			ah = ah & 15
		}
		self.a = (ah << 4) | al
	} else {
		self.a = r
	}
}

func (self *Cpu) cmp_gen(reg uint32, m uint32) {
	t := reg + 256 - m
	self.c = t >> 8
	self.set_nz(t & 255)
}

// --- сдвиги (значение -> результат, C и NZ ставятся) --------------------

func (self *Cpu) shift_val(aaa uint32, val uint32) uint32 {
	var r uint32 = 0
	if aaa == 0 { // ASL
		self.c = val >> 7
		r = (val << 1) & 255
	} else if aaa == 1 { // ROL
		r = ((val << 1) | self.c) & 255
		self.c = val >> 7
	} else if aaa == 2 { // LSR
		self.c = val & 1
		r = val >> 1
	} else { // ROR
		r = (val >> 1) | (self.c << 7)
		self.c = val & 1
	}
	self.set_nz(r)
	return r
}

// --- группа cc=1: ORA AND EOR ADC STA LDA CMP SBC ------------------------

func (self *Cpu) exec_alu(op uint32) {
	aaa := op >> 5
	bbb := (op >> 2) & 7
	if aaa == 4 && bbb == 2 { // STA #imm не существует
		self.halted = true
		return
	}
	ad := self.ea_alu(bbb)
	if self.halted {
		return
	}
	if aaa == 4 { // STA
		self.wr(ad, self.a)
		return
	}
	m := self.rd(ad)
	if aaa == 0 {
		self.a = self.a | m
		self.set_nz(self.a)
	} else if aaa == 1 {
		self.a = self.a & m
		self.set_nz(self.a)
	} else if aaa == 2 {
		self.a = self.a ^ m
		self.set_nz(self.a)
	} else if aaa == 3 {
		self.adc(m)
	} else if aaa == 5 {
		self.a = m
		self.set_nz(self.a)
	} else if aaa == 6 {
		self.cmp_gen(self.a, m)
	} else {
		self.sbc(m)
	}
}

// --- группа cc=2: сдвиги, STX/LDX, DEC/INC, пересылки X ------------------

func (self *Cpu) exec_rmw(op uint32) {
	aaa := op >> 5
	bbb := (op >> 2) & 7
	if bbb == 2 || bbb == 6 {
		self.rmw_impl(op)
		return
	}
	if bbb == 0 && aaa != 5 { // #imm есть только у LDX
		self.halted = true
		return
	}
	var ry uint32 = 0
	if (aaa == 4 || aaa == 5) && (bbb == 5 || bbb == 7) {
		ry = 1 // STX/LDX индексируются Y
	}
	if aaa == 4 && bbb == 7 { // STX abs,Y не существует
		self.halted = true
		return
	}
	ad := self.ea_mem(bbb, ry)
	if self.halted {
		return
	}
	if aaa == 4 { // STX
		self.wr(ad, self.x)
		return
	}
	if aaa == 5 { // LDX
		self.x = self.rd(ad)
		self.set_nz(self.x)
		return
	}
	m := self.rd(ad)
	if aaa == 6 { // DEC
		dv := (m + 255) & 255
		self.wr(ad, dv)
		self.set_nz(dv)
	} else if aaa == 7 { // INC
		iv := (m + 1) & 255
		self.wr(ad, iv)
		self.set_nz(iv)
	} else { // ASL/ROL/LSR/ROR по памяти
		self.wr(ad, self.shift_val(aaa, m))
	}
}

// Однобайтовые опкоды колонки cc=2: xA и xA+16.
func (self *Cpu) rmw_impl(op uint32) {
	if op == 10 || op == 42 || op == 74 || op == 106 {
		self.a = self.shift_val(op>>5, self.a)
	} else if op == 138 { // TXA
		self.a = self.x
		self.set_nz(self.a)
	} else if op == 154 { // TXS
		self.sp = self.x
	} else if op == 170 { // TAX
		self.x = self.a
		self.set_nz(self.x)
	} else if op == 186 { // TSX
		self.x = self.sp
		self.set_nz(self.x)
	} else if op == 202 { // DEX
		self.x = (self.x + 255) & 255
		self.set_nz(self.x)
	} else if op == 234 { // NOP
		return
	} else {
		self.halted = true
	}
}

// --- ветвления: xxy10000, xx — флаг NVCZ, y — ожидаемое значение ---------

func (self *Cpu) branch(op uint32) {
	off := self.fetch()
	flag := self.n
	sel := op >> 6
	if sel == 1 {
		flag = self.v
	} else if sel == 2 {
		flag = self.c
	} else if sel == 3 {
		flag = self.z
	}
	if flag == ((op >> 5) & 1) {
		if off >= 128 { // знаковое смещение: -256 ≡ +65280 (mod 65536)
			self.pc = (self.pc + off + 65280) & 65535
		} else {
			self.pc = (self.pc + off) & 65535
		}
	}
}

// --- группа cc=0: управление, стек, флаги, Y-операции --------------------

func (self *Cpu) exec_ctl(op uint32) {
	if op == 0 { // BRK: вектор $FFFE; нулевой вектор — останов
		vec := self.rd16(65534)
		if vec == 0 {
			self.halted = true
			return
		}
		ret := (self.pc + 1) & 65535
		self.push(ret >> 8)
		self.push(ret & 255)
		self.push(self.flags_byte(1))
		self.i = 1
		self.pc = vec
		return
	}
	if op == 32 { // JSR
		t := self.fetch16()
		ra := (self.pc + 65535) & 65535
		self.push(ra >> 8)
		self.push(ra & 255)
		self.pc = t
		return
	}
	if op == 64 { // RTI
		p := self.pop()
		self.set_flags(p)
		lo := self.pop()
		self.pc = lo | (self.pop() << 8)
		return
	}
	if op == 96 { // RTS
		lo2 := self.pop()
		self.pc = ((lo2 | (self.pop() << 8)) + 1) & 65535
		return
	}
	if op == 76 { // JMP abs
		self.pc = self.fetch16()
		return
	}
	if op == 108 { // JMP (ind) с багом границы страницы
		p2 := self.fetch16()
		hi_ad := (p2 & 65280) | ((p2 + 1) & 255)
		self.pc = self.rd(p2) | (self.rd(hi_ad) << 8)
		return
	}
	bbb := (op >> 2) & 7
	if bbb == 2 {
		self.ctl_col2(op)
		return
	}
	if bbb == 6 {
		self.ctl_col6(op)
		return
	}
	self.ctl_mem(op, bbb)
}

// Колонка $x8: стек и инкременты Y.
func (self *Cpu) ctl_col2(op uint32) {
	if op == 8 { // PHP (B=1 на стеке)
		self.push(self.flags_byte(1))
	} else if op == 40 { // PLP
		p := self.pop()
		self.set_flags(p)
	} else if op == 72 { // PHA
		self.push(self.a)
	} else if op == 104 { // PLA
		self.a = self.pop()
		self.set_nz(self.a)
	} else if op == 136 { // DEY
		self.y = (self.y + 255) & 255
		self.set_nz(self.y)
	} else if op == 168 { // TAY
		self.y = self.a
		self.set_nz(self.y)
	} else if op == 200 { // INY
		self.y = (self.y + 1) & 255
		self.set_nz(self.y)
	} else if op == 232 { // INX
		self.x = (self.x + 1) & 255
		self.set_nz(self.x)
	} else {
		self.halted = true
	}
}

// Колонка $x8+16: операции с флагами и TYA.
func (self *Cpu) ctl_col6(op uint32) {
	if op == 24 { // CLC
		self.c = 0
	} else if op == 56 { // SEC
		self.c = 1
	} else if op == 88 { // CLI
		self.i = 0
	} else if op == 120 { // SEI
		self.i = 1
	} else if op == 152 { // TYA
		self.a = self.y
		self.set_nz(self.a)
	} else if op == 184 { // CLV
		self.v = 0
	} else if op == 216 { // CLD
		self.d = 0
	} else if op == 248 { // SED
		self.d = 1
	} else {
		self.halted = true
	}
}

// BIT, STY, LDY, CPY, CPX с режимами по bbb.
func (self *Cpu) ctl_mem(op uint32, bbb uint32) {
	aaa := op >> 5
	if aaa == 1 && (bbb == 1 || bbb == 3) { // BIT zp/abs
		m := self.rd(self.ea_mem(bbb, 0))
		self.n = m >> 7
		self.v = (m >> 6) & 1
		if (self.a & m) == 0 {
			self.z = 1
		} else {
			self.z = 0
		}
		return
	}
	if aaa == 4 && (bbb == 1 || bbb == 3 || bbb == 5) { // STY
		ad := self.ea_mem(bbb, 0)
		self.wr(ad, self.y)
		return
	}
	if aaa == 5 { // LDY: #imm/zp/abs/zp,X/abs,X
		ad2 := self.ea_mem(bbb, 0)
		if self.halted {
			return
		}
		self.y = self.rd(ad2)
		self.set_nz(self.y)
		return
	}
	if (aaa == 6 || aaa == 7) && (bbb == 0 || bbb == 1 || bbb == 3) {
		m2 := self.rd(self.ea_mem(bbb, 0))
		if aaa == 6 { // CPY
			self.cmp_gen(self.y, m2)
		} else { // CPX
			self.cmp_gen(self.x, m2)
		}
		return
	}
	self.halted = true
}

// --- шаг ------------------------------------------------------------------

func (self *Cpu) step() {
	if self.halted {
		return
	}
	before := self.pc
	op := self.fetch()
	cc := op & 3
	if cc == 1 {
		self.exec_alu(op)
	} else if (op & 31) == 16 {
		self.branch(op)
	} else if cc == 2 {
		self.exec_rmw(op)
	} else if cc == 0 {
		self.exec_ctl(op)
	} else { // cc=3 — неофициальные опкоды
		self.halted = true
	}
	if self.pc == before { // jam: переход сам на себя
		self.halted = true
	}
	self.steps = self.steps + 1
}

// Свежий процессор после «сброса»: SP=$FD, регистры и память — нули.
func cpu_new() Cpu {
	return Cpu{sp: 253}
}

// --- hex (lib/Hex.eat: строчные буквы a..f) -------------------------------

func hex_digit(v uint32) byte {
	if v < 10 {
		return byte(v + 48)
	}
	return byte(v + 87) // a..f
}

func write_hex8(v uint32) {
	os.Stdout.Write([]byte{hex_digit(v >> 4), hex_digit(v & 15)})
}

func write_hex16(v uint32) {
	write_hex8(v >> 8)
	write_hex8(v & 255)
}

func main() {
	cpu := cpu_new()
	data, _ := io.ReadAll(os.Stdin)
	var nb uint32 = 0
	for _, b := range data {
		if nb >= 63488 {
			break
		}
		cpu.wr(LOAD+nb, uint32(b))
		nb = nb + 1
	}
	cpu.pc = LOAD
	for {
		if cpu.halted {
			break
		}
		cpu.step()
	}
	fmt.Print("A=")
	write_hex8(cpu.a)
	fmt.Print(" X=")
	write_hex8(cpu.x)
	fmt.Print(" Y=")
	write_hex8(cpu.y)
	fmt.Print(" SP=")
	write_hex8(cpu.sp)
	fmt.Print(" PC=")
	write_hex16(cpu.pc)
	fmt.Printf(" P=%d%d1x%d%d%d%d steps=%d bytes=%d\n",
		cpu.n, cpu.v, cpu.d, cpu.i, cpu.z, cpu.c, cpu.steps, nb)
	fmt.Print("0200:")
	for k := uint32(0); k < 16; k++ {
		fmt.Print(" ")
		write_hex8(cpu.rd(512 + k))
	}
	fmt.Print("\n")
}
