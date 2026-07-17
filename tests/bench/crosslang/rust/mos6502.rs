// Порт examples/mos6502/ 1:1 — эмулятор MOS 6502: все 151 официальный
// опкод, декодер aaabbbcc (exec_alu/exec_rmw/exec_ctl/колонки $x8),
// десятичный режим ADC/SBC (флаги десятичного SBC — от двоичного
// результата, как на NMOS), баг JMP (indirect) на границе страницы,
// jam-детектор (переход сам-на-себя), останов по BRK с нулевым вектором
// $FFFE и по неофициальному опкоду. Вход — сырые байты со stdin в $0600,
// PC=$0600, SP=$FD; отчёт (регистры/флаги/steps/bytes + 16 байт $0200)
// обязан совпасть байт-в-байт с EATLang-оригиналом.
//
// Регистры — u32 с инвариантом «байт»: маски (x + d) & 255 / & 65535
// выписаны явно, как в Cpu6502.eat; на mem — обычная индексация, маска
// & 65535 даёт LLVM снять bounds-check (часть сравнения). mem в Box,
// чтобы не грузить 64 КБ на стек.

use std::io::{self, Read, Write};

const LOAD: u32 = 1536;

struct Cpu {
    a: u32,
    x: u32,
    y: u32,
    sp: u32,
    pc: u32,
    c: u32,
    z: u32,
    i: u32,
    d: u32,
    v: u32,
    n: u32,
    halted: bool,
    steps: u32,
    mem: Box<[u8; 65536]>,
}

impl Cpu {
    // --- шина ------------------------------------------------------------

    fn rd(&self, ad: u32) -> u32 {
        self.mem[(ad & 65535) as usize] as u32
    }

    fn rd16(&self, ad: u32) -> u32 {
        self.rd(ad) | (self.rd(ad + 1) << 8)
    }

    fn wr(&mut self, ad: u32, val: u32) {
        self.mem[(ad & 65535) as usize] = (val & 255) as u8;
    }

    fn fetch(&mut self) -> u32 {
        let b: u32 = self.rd(self.pc);
        self.pc = (self.pc + 1) & 65535;
        b
    }

    fn fetch16(&mut self) -> u32 {
        let lo: u32 = self.fetch();
        let hi: u32 = self.fetch();
        lo | (hi << 8)
    }

    // --- стек ($0100..$01FF) ----------------------------------------------

    fn push(&mut self, val: u32) {
        self.wr(256 | self.sp, val);
        self.sp = (self.sp + 255) & 255;
    }

    fn pop(&mut self) -> u32 {
        self.sp = (self.sp + 1) & 255;
        self.rd(256 | self.sp)
    }

    // --- флаги -------------------------------------------------------------

    fn set_nz(&mut self, val: u32) {
        self.n = val >> 7;
        if val == 0 {
            self.z = 1;
        } else {
            self.z = 0;
        }
    }

    // Байт P: NV1BDIZC (бит 5 всегда 1, B — только на стеке).
    fn flags_byte(&self, brk: u32) -> u32 {
        (self.n << 7) | (self.v << 6) | 32 | (brk << 4)
            | (self.d << 3) | (self.i << 2) | (self.z << 1) | self.c
    }

    fn set_flags(&mut self, p: u32) {
        self.n = p >> 7;
        self.v = (p >> 6) & 1;
        self.d = (p >> 3) & 1;
        self.i = (p >> 2) & 1;
        self.z = (p >> 1) & 1;
        self.c = p & 1;
    }

    // --- адресация ---------------------------------------------------------

    // Режимы cc=1 по bbb: 0 (zp,X)  1 zp  2 #imm  3 abs  4 (zp),Y
    // 5 zp,X  6 abs,Y  7 abs,X. Для #imm операнд лежит по адресу pc.
    fn ea_alu(&mut self, bbb: u32) -> u32 {
        if bbb == 0 {
            let p: u32 = (self.fetch() + self.x) & 255;
            return self.rd(p) | (self.rd((p + 1) & 255) << 8);
        } else if bbb == 1 {
            return self.fetch();
        } else if bbb == 2 {
            let ad: u32 = self.pc;
            self.pc = (self.pc + 1) & 65535;
            return ad;
        } else if bbb == 3 {
            return self.fetch16();
        } else if bbb == 4 {
            let p2: u32 = self.fetch();
            let base: u32 = self.rd(p2) | (self.rd((p2 + 1) & 255) << 8);
            return (base + self.y) & 65535;
        } else if bbb == 5 {
            return (self.fetch() + self.x) & 255;
        } else if bbb == 6 {
            return (self.fetch16() + self.y) & 65535;
        }
        (self.fetch16() + self.x) & 65535
    }

    // Режимы cc=0/2 по bbb: 0 #imm  1 zp  3 abs  5 zp,idx  7 abs,idx.
    // ry=1 — индексирование Y (STX/LDX): zp,Y и abs,Y.
    fn ea_mem(&mut self, bbb: u32, ry: u32) -> u32 {
        let mut idx: u32 = self.x;
        if ry == 1 {
            idx = self.y;
        }
        if bbb == 0 {
            let ad: u32 = self.pc;
            self.pc = (self.pc + 1) & 65535;
            return ad;
        } else if bbb == 1 {
            return self.fetch();
        } else if bbb == 3 {
            return self.fetch16();
        } else if bbb == 5 {
            return (self.fetch() + idx) & 255;
        } else if bbb == 7 {
            return (self.fetch16() + idx) & 65535;
        }
        self.halted = true;
        0
    }

    // --- АЛУ ----------------------------------------------------------------

    fn adc(&mut self, m: u32) {
        let sum: u32 = self.a + m + self.c;
        if self.d == 1 {
            self.adc_dec(m, sum);
            return;
        }
        self.c = sum >> 8;
        self.v = ((self.a ^ sum) & (m ^ sum) & 128) >> 7;
        self.a = sum & 255;
        let a = self.a;
        self.set_nz(a);
    }

    // Десятичный ADC (NMOS): Z — от двоичной суммы, N/V — после
    // коррекции младшей тетрады, C — после коррекции старшей.
    fn adc_dec(&mut self, m: u32, sum: u32) {
        if (sum & 255) == 0 {
            self.z = 1;
        } else {
            self.z = 0;
        }
        let mut al: u32 = (self.a & 15) + (m & 15) + self.c;
        if al >= 10 {
            al = ((al + 6) & 15) + 16;
        }
        let mut s: u32 = (self.a & 240) + (m & 240) + al;
        self.n = (s >> 7) & 1;
        self.v = (((self.a ^ m) ^ 255) & (self.a ^ s) & 128) >> 7;
        if s >= 160 {
            s = s + 96;
        }
        if s >= 256 {
            self.c = 1;
        } else {
            self.c = 0;
        }
        self.a = s & 255;
    }

    // SBC: флаги NZVC всегда от двоичного результата (NMOS);
    // в десятичном режиме корректируется только аккумулятор.
    fn sbc(&mut self, m: u32) {
        let borrow: u32 = 1 - self.c;
        let bin: u32 = self.a + 256 - m - borrow;
        let r: u32 = bin & 255;
        self.c = bin >> 8;
        self.v = ((self.a ^ m) & (self.a ^ r) & 128) >> 7;
        self.set_nz(r);
        if self.d == 1 {
            let mut al: u32 = (self.a & 15) + 16 - (m & 15) - borrow;
            let mut ah: u32 = (self.a >> 4) + 16 - (m >> 4);
            if al < 16 {
                al = (al + 10) & 15;
                ah = ah - 1;
            } else {
                al = al & 15;
            }
            if ah < 16 {
                ah = (ah + 10) & 15;
            } else {
                ah = ah & 15;
            }
            self.a = (ah << 4) | al;
        } else {
            self.a = r;
        }
    }

    fn cmp_gen(&mut self, reg: u32, m: u32) {
        let t: u32 = reg + 256 - m;
        self.c = t >> 8;
        self.set_nz(t & 255);
    }

    // --- сдвиги (значение -> результат, C и NZ ставятся) --------------------

    fn shift_val(&mut self, aaa: u32, val: u32) -> u32 {
        let mut r: u32 = 0;
        if aaa == 0 {
            // ASL
            self.c = val >> 7;
            r = (val << 1) & 255;
        } else if aaa == 1 {
            // ROL
            r = ((val << 1) | self.c) & 255;
            self.c = val >> 7;
        } else if aaa == 2 {
            // LSR
            self.c = val & 1;
            r = val >> 1;
        } else {
            // ROR
            r = (val >> 1) | (self.c << 7);
            self.c = val & 1;
        }
        self.set_nz(r);
        r
    }

    // --- группа cc=1: ORA AND EOR ADC STA LDA CMP SBC ------------------------

    fn exec_alu(&mut self, op: u32) {
        let aaa: u32 = op >> 5;
        let bbb: u32 = (op >> 2) & 7;
        if aaa == 4 && bbb == 2 {
            // STA #imm не существует
            self.halted = true;
            return;
        }
        let ad: u32 = self.ea_alu(bbb);
        if self.halted {
            return;
        }
        if aaa == 4 {
            // STA
            self.wr(ad, self.a);
            return;
        }
        let m: u32 = self.rd(ad);
        if aaa == 0 {
            self.a = self.a | m;
            let a = self.a;
            self.set_nz(a);
        } else if aaa == 1 {
            self.a = self.a & m;
            let a = self.a;
            self.set_nz(a);
        } else if aaa == 2 {
            self.a = self.a ^ m;
            let a = self.a;
            self.set_nz(a);
        } else if aaa == 3 {
            self.adc(m);
        } else if aaa == 5 {
            self.a = m;
            let a = self.a;
            self.set_nz(a);
        } else if aaa == 6 {
            let a = self.a;
            self.cmp_gen(a, m);
        } else {
            self.sbc(m);
        }
    }

    // --- группа cc=2: сдвиги, STX/LDX, DEC/INC, пересылки X ------------------

    fn exec_rmw(&mut self, op: u32) {
        let aaa: u32 = op >> 5;
        let bbb: u32 = (op >> 2) & 7;
        if bbb == 2 || bbb == 6 {
            self.rmw_impl(op);
            return;
        }
        if bbb == 0 && aaa != 5 {
            // #imm есть только у LDX
            self.halted = true;
            return;
        }
        let mut ry: u32 = 0;
        if (aaa == 4 || aaa == 5) && (bbb == 5 || bbb == 7) {
            ry = 1; // STX/LDX индексируются Y
        }
        if aaa == 4 && bbb == 7 {
            // STX abs,Y не существует
            self.halted = true;
            return;
        }
        let ad: u32 = self.ea_mem(bbb, ry);
        if self.halted {
            return;
        }
        if aaa == 4 {
            // STX
            self.wr(ad, self.x);
            return;
        }
        if aaa == 5 {
            // LDX
            self.x = self.rd(ad);
            let x = self.x;
            self.set_nz(x);
            return;
        }
        let m: u32 = self.rd(ad);
        if aaa == 6 {
            // DEC
            let dv: u32 = (m + 255) & 255;
            self.wr(ad, dv);
            self.set_nz(dv);
        } else if aaa == 7 {
            // INC
            let iv: u32 = (m + 1) & 255;
            self.wr(ad, iv);
            self.set_nz(iv);
        } else {
            // ASL/ROL/LSR/ROR по памяти
            let sv = self.shift_val(aaa, m);
            self.wr(ad, sv);
        }
    }

    // Однобайтовые опкоды колонки cc=2: xA и xA+16.
    fn rmw_impl(&mut self, op: u32) {
        if op == 10 || op == 42 || op == 74 || op == 106 {
            self.a = self.shift_val(op >> 5, self.a);
        } else if op == 138 {
            // TXA
            self.a = self.x;
            let a = self.a;
            self.set_nz(a);
        } else if op == 154 {
            // TXS
            self.sp = self.x;
        } else if op == 170 {
            // TAX
            self.x = self.a;
            let x = self.x;
            self.set_nz(x);
        } else if op == 186 {
            // TSX
            self.x = self.sp;
            let x = self.x;
            self.set_nz(x);
        } else if op == 202 {
            // DEX
            self.x = (self.x + 255) & 255;
            let x = self.x;
            self.set_nz(x);
        } else if op == 234 {
            // NOP
            return;
        } else {
            self.halted = true;
        }
    }

    // --- ветвления: xxy10000, xx — флаг NVCZ, y — ожидаемое значение ---------

    fn branch(&mut self, op: u32) {
        let off: u32 = self.fetch();
        let mut flag: u32 = self.n;
        let sel: u32 = op >> 6;
        if sel == 1 {
            flag = self.v;
        } else if sel == 2 {
            flag = self.c;
        } else if sel == 3 {
            flag = self.z;
        }
        if flag == ((op >> 5) & 1) {
            if off >= 128 {
                // знаковое смещение: -256 ≡ +65280 (mod 65536)
                self.pc = (self.pc + off + 65280) & 65535;
            } else {
                self.pc = (self.pc + off) & 65535;
            }
        }
    }

    // --- группа cc=0: управление, стек, флаги, Y-операции --------------------

    fn exec_ctl(&mut self, op: u32) {
        if op == 0 {
            // BRK: вектор $FFFE; нулевой вектор — останов
            let vec: u32 = self.rd16(65534);
            if vec == 0 {
                self.halted = true;
                return;
            }
            let ret: u32 = (self.pc + 1) & 65535;
            self.push(ret >> 8);
            self.push(ret & 255);
            let fb = self.flags_byte(1);
            self.push(fb);
            self.i = 1;
            self.pc = vec;
            return;
        }
        if op == 32 {
            // JSR
            let t: u32 = self.fetch16();
            let ra: u32 = (self.pc + 65535) & 65535;
            self.push(ra >> 8);
            self.push(ra & 255);
            self.pc = t;
            return;
        }
        if op == 64 {
            // RTI
            let p: u32 = self.pop();
            self.set_flags(p);
            let lo: u32 = self.pop();
            self.pc = lo | (self.pop() << 8);
            return;
        }
        if op == 96 {
            // RTS
            let lo2: u32 = self.pop();
            self.pc = ((lo2 | (self.pop() << 8)) + 1) & 65535;
            return;
        }
        if op == 76 {
            // JMP abs
            self.pc = self.fetch16();
            return;
        }
        if op == 108 {
            // JMP (ind) с багом границы страницы
            let p2: u32 = self.fetch16();
            let hi_ad: u32 = (p2 & 65280) | ((p2 + 1) & 255);
            self.pc = self.rd(p2) | (self.rd(hi_ad) << 8);
            return;
        }
        let bbb: u32 = (op >> 2) & 7;
        if bbb == 2 {
            self.ctl_col2(op);
            return;
        }
        if bbb == 6 {
            self.ctl_col6(op);
            return;
        }
        self.ctl_mem(op, bbb);
    }

    // Колонка $x8: стек и инкременты Y.
    fn ctl_col2(&mut self, op: u32) {
        if op == 8 {
            // PHP (B=1 на стеке)
            let fb = self.flags_byte(1);
            self.push(fb);
        } else if op == 40 {
            // PLP
            let p: u32 = self.pop();
            self.set_flags(p);
        } else if op == 72 {
            // PHA
            self.push(self.a);
        } else if op == 104 {
            // PLA
            self.a = self.pop();
            let a = self.a;
            self.set_nz(a);
        } else if op == 136 {
            // DEY
            self.y = (self.y + 255) & 255;
            let y = self.y;
            self.set_nz(y);
        } else if op == 168 {
            // TAY
            self.y = self.a;
            let y = self.y;
            self.set_nz(y);
        } else if op == 200 {
            // INY
            self.y = (self.y + 1) & 255;
            let y = self.y;
            self.set_nz(y);
        } else if op == 232 {
            // INX
            self.x = (self.x + 1) & 255;
            let x = self.x;
            self.set_nz(x);
        } else {
            self.halted = true;
        }
    }

    // Колонка $x8+16: операции с флагами и TYA.
    fn ctl_col6(&mut self, op: u32) {
        if op == 24 {
            // CLC
            self.c = 0;
        } else if op == 56 {
            // SEC
            self.c = 1;
        } else if op == 88 {
            // CLI
            self.i = 0;
        } else if op == 120 {
            // SEI
            self.i = 1;
        } else if op == 152 {
            // TYA
            self.a = self.y;
            let a = self.a;
            self.set_nz(a);
        } else if op == 184 {
            // CLV
            self.v = 0;
        } else if op == 216 {
            // CLD
            self.d = 0;
        } else if op == 248 {
            // SED
            self.d = 1;
        } else {
            self.halted = true;
        }
    }

    // BIT, STY, LDY, CPY, CPX с режимами по bbb.
    fn ctl_mem(&mut self, op: u32, bbb: u32) {
        let aaa: u32 = op >> 5;
        if aaa == 1 && (bbb == 1 || bbb == 3) {
            // BIT zp/abs
            let ea = self.ea_mem(bbb, 0);
            let m: u32 = self.rd(ea);
            self.n = m >> 7;
            self.v = (m >> 6) & 1;
            if (self.a & m) == 0 {
                self.z = 1;
            } else {
                self.z = 0;
            }
            return;
        }
        if aaa == 4 && (bbb == 1 || bbb == 3 || bbb == 5) {
            // STY
            let ad: u32 = self.ea_mem(bbb, 0);
            self.wr(ad, self.y);
            return;
        }
        if aaa == 5 {
            // LDY: #imm/zp/abs/zp,X/abs,X
            let ad2: u32 = self.ea_mem(bbb, 0);
            if self.halted {
                return;
            }
            self.y = self.rd(ad2);
            let y = self.y;
            self.set_nz(y);
            return;
        }
        if (aaa == 6 || aaa == 7) && (bbb == 0 || bbb == 1 || bbb == 3) {
            let ea = self.ea_mem(bbb, 0);
            let m2: u32 = self.rd(ea);
            if aaa == 6 {
                // CPY
                let y = self.y;
                self.cmp_gen(y, m2);
            } else {
                // CPX
                let x = self.x;
                self.cmp_gen(x, m2);
            }
            return;
        }
        self.halted = true;
    }

    // --- шаг ------------------------------------------------------------------

    fn step(&mut self) {
        if self.halted {
            return;
        }
        let before: u32 = self.pc;
        let op: u32 = self.fetch();
        let cc: u32 = op & 3;
        if cc == 1 {
            self.exec_alu(op);
        } else if (op & 31) == 16 {
            self.branch(op);
        } else if cc == 2 {
            self.exec_rmw(op);
        } else if cc == 0 {
            self.exec_ctl(op);
        } else {
            // cc=3 — неофициальные опкоды
            self.halted = true;
        }
        if self.pc == before {
            // jam: переход сам на себя
            self.halted = true;
        }
        self.steps = self.steps + 1;
    }
}

// Свежий процессор после «сброса»: SP=$FD, регистры и память — нули.
fn cpu_new() -> Cpu {
    Cpu {
        a: 0,
        x: 0,
        y: 0,
        sp: 253,
        pc: 0,
        c: 0,
        z: 0,
        i: 0,
        d: 0,
        v: 0,
        n: 0,
        halted: false,
        steps: 0,
        mem: Box::new([0u8; 65536]),
    }
}

// --- печать hex (lib/Hex.eat): регистр букв — строчный a..f ------------------

fn hex_digit(v: u32) -> char {
    if v < 10 {
        (v as u8 + 48) as char
    } else {
        (v as u8 + 87) as char // a..f
    }
}

fn write_hex8(out: &mut String, v: u32) {
    out.push(hex_digit(v >> 4));
    out.push(hex_digit(v & 15));
}

fn write_hex16(out: &mut String, v: u32) {
    write_hex8(out, v >> 8);
    write_hex8(out, v & 255);
}

fn main() {
    let mut input: Vec<u8> = Vec::new();
    io::stdin().read_to_end(&mut input).expect("read stdin");

    let mut cpu: Cpu = cpu_new();
    let mut nb: u32 = 0;
    let mut eof: bool = false;
    let mut it = input.into_iter();
    for _ in 0..63488u32 {
        if !eof {
            match it.next() {
                Some(b) => {
                    cpu.wr(LOAD + nb, b as u32);
                    nb = nb + 1;
                }
                None => {
                    eof = true;
                }
            }
        }
    }
    cpu.pc = LOAD;
    // Реактивная модель: единственный бесконечный цикл — в main.
    // Останов гарантируют BRK (нулевой вектор), неофициальный опкод
    // и jam-детектор перехода сам-на-себя.
    loop {
        if cpu.halted {
            break;
        }
        cpu.step();
    }

    let mut out = String::new();
    out.push_str("A=");
    write_hex8(&mut out, cpu.a);
    out.push_str(" X=");
    write_hex8(&mut out, cpu.x);
    out.push_str(" Y=");
    write_hex8(&mut out, cpu.y);
    out.push_str(" SP=");
    write_hex8(&mut out, cpu.sp);
    out.push_str(" PC=");
    write_hex16(&mut out, cpu.pc);
    out.push_str(&format!(
        " P={}{}1x{}{}{}{} steps={} bytes={}\n",
        cpu.n, cpu.v, cpu.d, cpu.i, cpu.z, cpu.c, cpu.steps, nb
    ));
    out.push_str("0200:");
    for k in 0..16u32 {
        out.push(' ');
        write_hex8(&mut out, cpu.rd(512 + k));
    }
    out.push('\n');

    let stdout = io::stdout();
    let mut lock = stdout.lock();
    lock.write_all(out.as_bytes()).expect("write stdout");
    lock.flush().expect("flush");
}
