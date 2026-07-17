# Порт examples/mos6502/ 1:1 — эмулятор MOS 6502 (все 151 официальный
# опкод, десятичный режим ADC/SBC с NMOS-семантикой флагов, баг JMP
# (indirect) на границе страницы, jam-детектор). Макробенч кросс-
# языкового сравнения: сырые байты со stdin грузятся в $0600, PC=$0600,
# SP=$FD, исполнение до останова; отчёт регистров/флагов и 16 байт
# страницы $0200 обязан совпасть с EATLang-эталоном байт-в-байт.
#
# Структура повторяет Cpu6502.eat: те же функции rd/wr/step/exec_*,
# те же маски (x + d) & 255 / & 65535, тот же декодер по aaabbbcc
# (обычные if/elif, без диспетчера опкод->лямбда).

import sys

LOAD = 1536


class Cpu:
    def __init__(self):
        self.a = 0
        self.x = 0
        self.y = 0
        self.sp = 253
        self.pc = 0
        self.c = 0
        self.z = 0
        self.i = 0
        self.d = 0
        self.v = 0
        self.n = 0
        self.halted = False
        self.steps = 0
        self.mem = bytearray(65536)

    # --- шина ------------------------------------------------------------

    def rd(self, ad):
        return self.mem[ad & 65535]

    def rd16(self, ad):
        return self.rd(ad) | (self.rd(ad + 1) << 8)

    def wr(self, ad, val):
        self.mem[ad & 65535] = val & 255

    def fetch(self):
        b = self.rd(self.pc)
        self.pc = (self.pc + 1) & 65535
        return b

    def fetch16(self):
        lo = self.fetch()
        hi = self.fetch()
        return lo | (hi << 8)

    # --- стек ($0100..$01FF) ----------------------------------------------

    def push(self, val):
        self.wr(256 | self.sp, val)
        self.sp = (self.sp + 255) & 255

    def pop(self):
        self.sp = (self.sp + 1) & 255
        return self.rd(256 | self.sp)

    # --- флаги -------------------------------------------------------------

    def set_nz(self, val):
        self.n = val >> 7
        if val == 0:
            self.z = 1
        else:
            self.z = 0

    # Байт P: NV1BDIZC (бит 5 всегда 1, B — только на стеке).
    def flags_byte(self, brk):
        return (
            (self.n << 7) | (self.v << 6) | 32 | (brk << 4)
            | (self.d << 3) | (self.i << 2) | (self.z << 1) | self.c
        )

    def set_flags(self, p):
        self.n = p >> 7
        self.v = (p >> 6) & 1
        self.d = (p >> 3) & 1
        self.i = (p >> 2) & 1
        self.z = (p >> 1) & 1
        self.c = p & 1

    # --- адресация ---------------------------------------------------------

    # Режимы cc=1 по bbb: 0 (zp,X)  1 zp  2 #imm  3 abs  4 (zp),Y
    # 5 zp,X  6 abs,Y  7 abs,X. Для #imm операнд лежит по адресу pc.
    def ea_alu(self, bbb):
        if bbb == 0:
            p = (self.fetch() + self.x) & 255
            return self.rd(p) | (self.rd((p + 1) & 255) << 8)
        elif bbb == 1:
            return self.fetch()
        elif bbb == 2:
            ad = self.pc
            self.pc = (self.pc + 1) & 65535
            return ad
        elif bbb == 3:
            return self.fetch16()
        elif bbb == 4:
            p2 = self.fetch()
            base = self.rd(p2) | (self.rd((p2 + 1) & 255) << 8)
            return (base + self.y) & 65535
        elif bbb == 5:
            return (self.fetch() + self.x) & 255
        elif bbb == 6:
            return (self.fetch16() + self.y) & 65535
        return (self.fetch16() + self.x) & 65535

    # Режимы cc=0/2 по bbb: 0 #imm  1 zp  3 abs  5 zp,idx  7 abs,idx.
    # ry=1 — индексирование Y (STX/LDX): zp,Y и abs,Y.
    def ea_mem(self, bbb, ry):
        idx = self.x
        if ry == 1:
            idx = self.y
        if bbb == 0:
            ad = self.pc
            self.pc = (self.pc + 1) & 65535
            return ad
        elif bbb == 1:
            return self.fetch()
        elif bbb == 3:
            return self.fetch16()
        elif bbb == 5:
            return (self.fetch() + idx) & 255
        elif bbb == 7:
            return (self.fetch16() + idx) & 65535
        self.halted = True
        return 0

    # --- АЛУ ----------------------------------------------------------------

    def adc(self, m):
        s = self.a + m + self.c
        if self.d == 1:
            self.adc_dec(m, s)
            return
        self.c = s >> 8
        self.v = ((self.a ^ s) & (m ^ s) & 128) >> 7
        self.a = s & 255
        self.set_nz(self.a)

    # Десятичный ADC (NMOS): Z — от двоичной суммы, N/V — после
    # коррекции младшей тетрады, C — после коррекции старшей.
    def adc_dec(self, m, s):
        if (s & 255) == 0:
            self.z = 1
        else:
            self.z = 0
        al = (self.a & 15) + (m & 15) + self.c
        if al >= 10:
            al = ((al + 6) & 15) + 16
        sv = (self.a & 240) + (m & 240) + al
        self.n = (sv >> 7) & 1
        self.v = (((self.a ^ m) ^ 255) & (self.a ^ sv) & 128) >> 7
        if sv >= 160:
            sv = sv + 96
        if sv >= 256:
            self.c = 1
        else:
            self.c = 0
        self.a = sv & 255

    # SBC: флаги NZVC всегда от двоичного результата (NMOS);
    # в десятичном режиме корректируется только аккумулятор.
    def sbc(self, m):
        borrow = 1 - self.c
        bin = self.a + 256 - m - borrow
        r = bin & 255
        self.c = bin >> 8
        self.v = ((self.a ^ m) & (self.a ^ r) & 128) >> 7
        self.set_nz(r)
        if self.d == 1:
            al = (self.a & 15) + 16 - (m & 15) - borrow
            ah = (self.a >> 4) + 16 - (m >> 4)
            if al < 16:
                al = (al + 10) & 15
                ah = ah - 1
            else:
                al = al & 15
            if ah < 16:
                ah = (ah + 10) & 15
            else:
                ah = ah & 15
            self.a = (ah << 4) | al
        else:
            self.a = r

    def cmp_gen(self, reg, m):
        t = reg + 256 - m
        self.c = t >> 8
        self.set_nz(t & 255)

    # --- сдвиги (значение -> результат, C и NZ ставятся) --------------------

    def shift_val(self, aaa, val):
        r = 0
        if aaa == 0:  # ASL
            self.c = val >> 7
            r = (val << 1) & 255
        elif aaa == 1:  # ROL
            r = ((val << 1) | self.c) & 255
            self.c = val >> 7
        elif aaa == 2:  # LSR
            self.c = val & 1
            r = val >> 1
        else:  # ROR
            r = (val >> 1) | (self.c << 7)
            self.c = val & 1
        self.set_nz(r)
        return r

    # --- группа cc=1: ORA AND EOR ADC STA LDA CMP SBC ------------------------

    def exec_alu(self, op):
        aaa = op >> 5
        bbb = (op >> 2) & 7
        if aaa == 4 and bbb == 2:  # STA #imm не существует
            self.halted = True
            return
        ad = self.ea_alu(bbb)
        if self.halted:
            return
        if aaa == 4:  # STA
            self.wr(ad, self.a)
            return
        m = self.rd(ad)
        if aaa == 0:
            self.a = self.a | m
            self.set_nz(self.a)
        elif aaa == 1:
            self.a = self.a & m
            self.set_nz(self.a)
        elif aaa == 2:
            self.a = self.a ^ m
            self.set_nz(self.a)
        elif aaa == 3:
            self.adc(m)
        elif aaa == 5:
            self.a = m
            self.set_nz(self.a)
        elif aaa == 6:
            self.cmp_gen(self.a, m)
        else:
            self.sbc(m)

    # --- группа cc=2: сдвиги, STX/LDX, DEC/INC, пересылки X ------------------

    def exec_rmw(self, op):
        aaa = op >> 5
        bbb = (op >> 2) & 7
        if bbb == 2 or bbb == 6:
            self.rmw_impl(op)
            return
        if bbb == 0 and aaa != 5:  # #imm есть только у LDX
            self.halted = True
            return
        ry = 0
        if (aaa == 4 or aaa == 5) and (bbb == 5 or bbb == 7):
            ry = 1  # STX/LDX индексируются Y
        if aaa == 4 and bbb == 7:  # STX abs,Y не существует
            self.halted = True
            return
        ad = self.ea_mem(bbb, ry)
        if self.halted:
            return
        if aaa == 4:  # STX
            self.wr(ad, self.x)
            return
        if aaa == 5:  # LDX
            self.x = self.rd(ad)
            self.set_nz(self.x)
            return
        m = self.rd(ad)
        if aaa == 6:  # DEC
            dv = (m + 255) & 255
            self.wr(ad, dv)
            self.set_nz(dv)
        elif aaa == 7:  # INC
            iv = (m + 1) & 255
            self.wr(ad, iv)
            self.set_nz(iv)
        else:  # ASL/ROL/LSR/ROR по памяти
            self.wr(ad, self.shift_val(aaa, m))

    # Однобайтовые опкоды колонки cc=2: xA и xA+16.
    def rmw_impl(self, op):
        if op == 10 or op == 42 or op == 74 or op == 106:
            self.a = self.shift_val(op >> 5, self.a)
        elif op == 138:  # TXA
            self.a = self.x
            self.set_nz(self.a)
        elif op == 154:  # TXS
            self.sp = self.x
        elif op == 170:  # TAX
            self.x = self.a
            self.set_nz(self.x)
        elif op == 186:  # TSX
            self.x = self.sp
            self.set_nz(self.x)
        elif op == 202:  # DEX
            self.x = (self.x + 255) & 255
            self.set_nz(self.x)
        elif op == 234:  # NOP
            return
        else:
            self.halted = True

    # --- ветвления: xxy10000, xx — флаг NVCZ, y — ожидаемое значение ---------

    def branch(self, op):
        off = self.fetch()
        flag = self.n
        sel = op >> 6
        if sel == 1:
            flag = self.v
        elif sel == 2:
            flag = self.c
        elif sel == 3:
            flag = self.z
        if flag == ((op >> 5) & 1):
            if off >= 128:  # знаковое смещение: -256 ≡ +65280 (mod 65536)
                self.pc = (self.pc + off + 65280) & 65535
            else:
                self.pc = (self.pc + off) & 65535

    # --- группа cc=0: управление, стек, флаги, Y-операции --------------------

    def exec_ctl(self, op):
        if op == 0:  # BRK: вектор $FFFE; нулевой вектор — останов
            vec = self.rd16(65534)
            if vec == 0:
                self.halted = True
                return
            ret = (self.pc + 1) & 65535
            self.push(ret >> 8)
            self.push(ret & 255)
            self.push(self.flags_byte(1))
            self.i = 1
            self.pc = vec
            return
        if op == 32:  # JSR
            t = self.fetch16()
            ra = (self.pc + 65535) & 65535
            self.push(ra >> 8)
            self.push(ra & 255)
            self.pc = t
            return
        if op == 64:  # RTI
            p = self.pop()
            self.set_flags(p)
            lo = self.pop()
            self.pc = lo | (self.pop() << 8)
            return
        if op == 96:  # RTS
            lo2 = self.pop()
            self.pc = ((lo2 | (self.pop() << 8)) + 1) & 65535
            return
        if op == 76:  # JMP abs
            self.pc = self.fetch16()
            return
        if op == 108:  # JMP (ind) с багом границы страницы
            p2 = self.fetch16()
            hi_ad = (p2 & 65280) | ((p2 + 1) & 255)
            self.pc = self.rd(p2) | (self.rd(hi_ad) << 8)
            return
        bbb = (op >> 2) & 7
        if bbb == 2:
            self.ctl_col2(op)
            return
        if bbb == 6:
            self.ctl_col6(op)
            return
        self.ctl_mem(op, bbb)

    # Колонка $x8: стек и инкременты Y.
    def ctl_col2(self, op):
        if op == 8:  # PHP (B=1 на стеке)
            self.push(self.flags_byte(1))
        elif op == 40:  # PLP
            p = self.pop()
            self.set_flags(p)
        elif op == 72:  # PHA
            self.push(self.a)
        elif op == 104:  # PLA
            self.a = self.pop()
            self.set_nz(self.a)
        elif op == 136:  # DEY
            self.y = (self.y + 255) & 255
            self.set_nz(self.y)
        elif op == 168:  # TAY
            self.y = self.a
            self.set_nz(self.y)
        elif op == 200:  # INY
            self.y = (self.y + 1) & 255
            self.set_nz(self.y)
        elif op == 232:  # INX
            self.x = (self.x + 1) & 255
            self.set_nz(self.x)
        else:
            self.halted = True

    # Колонка $x8+16: операции с флагами и TYA.
    def ctl_col6(self, op):
        if op == 24:  # CLC
            self.c = 0
        elif op == 56:  # SEC
            self.c = 1
        elif op == 88:  # CLI
            self.i = 0
        elif op == 120:  # SEI
            self.i = 1
        elif op == 152:  # TYA
            self.a = self.y
            self.set_nz(self.a)
        elif op == 184:  # CLV
            self.v = 0
        elif op == 216:  # CLD
            self.d = 0
        elif op == 248:  # SED
            self.d = 1
        else:
            self.halted = True

    # BIT, STY, LDY, CPY, CPX с режимами по bbb.
    def ctl_mem(self, op, bbb):
        aaa = op >> 5
        if aaa == 1 and (bbb == 1 or bbb == 3):  # BIT zp/abs
            m = self.rd(self.ea_mem(bbb, 0))
            self.n = m >> 7
            self.v = (m >> 6) & 1
            if (self.a & m) == 0:
                self.z = 1
            else:
                self.z = 0
            return
        if aaa == 4 and (bbb == 1 or bbb == 3 or bbb == 5):  # STY
            ad = self.ea_mem(bbb, 0)
            self.wr(ad, self.y)
            return
        if aaa == 5:  # LDY: #imm/zp/abs/zp,X/abs,X
            ad2 = self.ea_mem(bbb, 0)
            if self.halted:
                return
            self.y = self.rd(ad2)
            self.set_nz(self.y)
            return
        if (aaa == 6 or aaa == 7) and (bbb == 0 or bbb == 1 or bbb == 3):
            m2 = self.rd(self.ea_mem(bbb, 0))
            if aaa == 6:  # CPY
                self.cmp_gen(self.y, m2)
            else:  # CPX
                self.cmp_gen(self.x, m2)
            return
        self.halted = True

    # --- шаг ------------------------------------------------------------------

    def step(self):
        if self.halted:
            return
        before = self.pc
        op = self.fetch()
        cc = op & 3
        if cc == 1:
            self.exec_alu(op)
        elif (op & 31) == 16:
            self.branch(op)
        elif cc == 2:
            self.exec_rmw(op)
        elif cc == 0:
            self.exec_ctl(op)
        else:  # cc=3 — неофициальные опкоды
            self.halted = True
        if self.pc == before:  # jam: переход сам на себя
            self.halted = True
        self.steps = self.steps + 1


def hex_digit(v):
    if v < 10:
        return chr(v + 48)
    return chr(v + 87)  # a..f


def hex8(v):
    return hex_digit(v >> 4) + hex_digit(v & 15)


def hex16(v):
    return hex8(v >> 8) + hex8(v & 255)


def main():
    cpu = Cpu()
    data = sys.stdin.buffer.read()
    nb = 0
    for b in data:
        if nb >= 63488:
            break
        cpu.wr(LOAD + nb, b)
        nb = nb + 1
    cpu.pc = LOAD
    # Реактивная модель: единственный бесконечный цикл. Останов
    # гарантируют BRK (нулевой вектор), неофициальный опкод и jam.
    while True:
        if cpu.halted:
            break
        cpu.step()
    out = []
    out.append("A=" + hex8(cpu.a))
    out.append(" X=" + hex8(cpu.x))
    out.append(" Y=" + hex8(cpu.y))
    out.append(" SP=" + hex8(cpu.sp))
    out.append(" PC=" + hex16(cpu.pc))
    out.append(
        " P={n}{v}1x{d}{i}{z}{c} steps={s} bytes={nb}\n".format(
            n=cpu.n, v=cpu.v, d=cpu.d, i=cpu.i, z=cpu.z, c=cpu.c,
            s=cpu.steps, nb=nb
        )
    )
    out.append("0200:")
    for k in range(16):
        out.append(" " + hex8(cpu.rd(512 + k)))
    out.append("\n")
    sys.stdout.write("".join(out))


main()
