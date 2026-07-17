/* Порт examples/mos6502/ 1:1 — эмулятор MOS 6502: все 151 официальный
 * опкод, декодер по структуре aaabbbcc, десятичный режим ADC/SBC
 * (семантика NMOS), баг JMP (indirect) на границе страницы, jam-детектор
 * и останов по BRK с нулевым вектором. Структура повторяет Cpu6502.eat:
 * та же mem[65536], те же функции rd/wr/step/exec_* с той же логикой
 * ветвлений и теми же масками (& 255 / & 65535). Нагрузка — сырой ROM
 * со stdin (грузится в $0600), REPEAT-маркера нет. Вывод обязан совпасть
 * байт-в-байт с EATLang-оригиналом (examples/mos6502/Main.eat). */
#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>

typedef struct {
    uint32_t a, x, y, sp, pc;
    uint32_t c, z, i, d, v, n;
    bool halted;
    uint32_t steps;
    uint8_t mem[65536];
} Cpu;

/* --- шина --------------------------------------------------------------- */

static uint32_t rd(Cpu *self, uint32_t ad) {
    return (uint32_t)self->mem[ad & 65535];
}

static uint32_t rd16(Cpu *self, uint32_t ad) {
    return rd(self, ad) | (rd(self, ad + 1) << 8);
}

static void wr(Cpu *self, uint32_t ad, uint32_t val) {
    self->mem[ad & 65535] = (uint8_t)(val & 255);
}

static uint32_t fetch(Cpu *self) {
    uint32_t b = rd(self, self->pc);
    self->pc = (self->pc + 1) & 65535;
    return b;
}

static uint32_t fetch16(Cpu *self) {
    uint32_t lo = fetch(self);
    uint32_t hi = fetch(self);
    return lo | (hi << 8);
}

/* --- стек ($0100..$01FF) ------------------------------------------------- */

static void push(Cpu *self, uint32_t val) {
    wr(self, 256 | self->sp, val);
    self->sp = (self->sp + 255) & 255;
}

static uint32_t pop(Cpu *self) {
    self->sp = (self->sp + 1) & 255;
    return rd(self, 256 | self->sp);
}

/* --- флаги --------------------------------------------------------------- */

static void set_nz(Cpu *self, uint32_t val) {
    self->n = val >> 7;
    if (val == 0) {
        self->z = 1;
    } else {
        self->z = 0;
    }
}

static uint32_t flags_byte(Cpu *self, uint32_t brk) {
    return (
        (self->n << 7) | (self->v << 6) | 32 | (brk << 4)
        | (self->d << 3) | (self->i << 2) | (self->z << 1) | self->c
    );
}

static void set_flags(Cpu *self, uint32_t p) {
    self->n = p >> 7;
    self->v = (p >> 6) & 1;
    self->d = (p >> 3) & 1;
    self->i = (p >> 2) & 1;
    self->z = (p >> 1) & 1;
    self->c = p & 1;
}

/* --- адресация ----------------------------------------------------------- */

static uint32_t ea_alu(Cpu *self, uint32_t bbb) {
    if (bbb == 0) {
        uint32_t p = (fetch(self) + self->x) & 255;
        return rd(self, p) | (rd(self, (p + 1) & 255) << 8);
    } else if (bbb == 1) {
        return fetch(self);
    } else if (bbb == 2) {
        uint32_t ad = self->pc;
        self->pc = (self->pc + 1) & 65535;
        return ad;
    } else if (bbb == 3) {
        return fetch16(self);
    } else if (bbb == 4) {
        uint32_t p2 = fetch(self);
        uint32_t base = rd(self, p2) | (rd(self, (p2 + 1) & 255) << 8);
        return (base + self->y) & 65535;
    } else if (bbb == 5) {
        return (fetch(self) + self->x) & 255;
    } else if (bbb == 6) {
        return (fetch16(self) + self->y) & 65535;
    }
    return (fetch16(self) + self->x) & 65535;
}

static uint32_t ea_mem(Cpu *self, uint32_t bbb, uint32_t ry) {
    uint32_t idx = self->x;
    if (ry == 1) {
        idx = self->y;
    }
    if (bbb == 0) {
        uint32_t ad = self->pc;
        self->pc = (self->pc + 1) & 65535;
        return ad;
    } else if (bbb == 1) {
        return fetch(self);
    } else if (bbb == 3) {
        return fetch16(self);
    } else if (bbb == 5) {
        return (fetch(self) + idx) & 255;
    } else if (bbb == 7) {
        return (fetch16(self) + idx) & 65535;
    }
    self->halted = true;
    return 0;
}

/* --- АЛУ ----------------------------------------------------------------- */

static void adc_dec(Cpu *self, uint32_t m, uint32_t sum);

static void adc(Cpu *self, uint32_t m) {
    uint32_t sum = self->a + m + self->c;
    if (self->d == 1) {
        adc_dec(self, m, sum);
        return;
    }
    self->c = sum >> 8;
    self->v = ((self->a ^ sum) & (m ^ sum) & 128) >> 7;
    self->a = sum & 255;
    set_nz(self, self->a);
}

static void adc_dec(Cpu *self, uint32_t m, uint32_t sum) {
    if ((sum & 255) == 0) {
        self->z = 1;
    } else {
        self->z = 0;
    }
    uint32_t al = (self->a & 15) + (m & 15) + self->c;
    if (al >= 10) {
        al = ((al + 6) & 15) + 16;
    }
    uint32_t s = (self->a & 240) + (m & 240) + al;
    self->n = (s >> 7) & 1;
    self->v = (((self->a ^ m) ^ 255) & (self->a ^ s) & 128) >> 7;
    if (s >= 160) {
        s = s + 96;
    }
    if (s >= 256) {
        self->c = 1;
    } else {
        self->c = 0;
    }
    self->a = s & 255;
}

static void sbc(Cpu *self, uint32_t m) {
    uint32_t borrow = 1 - self->c;
    uint32_t bin = self->a + 256 - m - borrow;
    uint32_t r = bin & 255;
    self->c = bin >> 8;
    self->v = ((self->a ^ m) & (self->a ^ r) & 128) >> 7;
    set_nz(self, r);
    if (self->d == 1) {
        uint32_t al = (self->a & 15) + 16 - (m & 15) - borrow;
        uint32_t ah = (self->a >> 4) + 16 - (m >> 4);
        if (al < 16) {
            al = (al + 10) & 15;
            ah = ah - 1;
        } else {
            al = al & 15;
        }
        if (ah < 16) {
            ah = (ah + 10) & 15;
        } else {
            ah = ah & 15;
        }
        self->a = (ah << 4) | al;
    } else {
        self->a = r;
    }
}

static void cmp_gen(Cpu *self, uint32_t reg, uint32_t m) {
    uint32_t t = reg + 256 - m;
    self->c = t >> 8;
    set_nz(self, t & 255);
}

/* --- сдвиги -------------------------------------------------------------- */

static uint32_t shift_val(Cpu *self, uint32_t aaa, uint32_t val) {
    uint32_t r = 0;
    if (aaa == 0) { /* ASL */
        self->c = val >> 7;
        r = (val << 1) & 255;
    } else if (aaa == 1) { /* ROL */
        r = ((val << 1) | self->c) & 255;
        self->c = val >> 7;
    } else if (aaa == 2) { /* LSR */
        self->c = val & 1;
        r = val >> 1;
    } else { /* ROR */
        r = (val >> 1) | (self->c << 7);
        self->c = val & 1;
    }
    set_nz(self, r);
    return r;
}

/* --- группа cc=1: ORA AND EOR ADC STA LDA CMP SBC ----------------------- */

static void exec_alu(Cpu *self, uint32_t op) {
    uint32_t aaa = op >> 5;
    uint32_t bbb = (op >> 2) & 7;
    if (aaa == 4 && bbb == 2) { /* STA #imm не существует */
        self->halted = true;
        return;
    }
    uint32_t ad = ea_alu(self, bbb);
    if (self->halted) {
        return;
    }
    if (aaa == 4) { /* STA */
        wr(self, ad, self->a);
        return;
    }
    uint32_t m = rd(self, ad);
    if (aaa == 0) {
        self->a = self->a | m;
        set_nz(self, self->a);
    } else if (aaa == 1) {
        self->a = self->a & m;
        set_nz(self, self->a);
    } else if (aaa == 2) {
        self->a = self->a ^ m;
        set_nz(self, self->a);
    } else if (aaa == 3) {
        adc(self, m);
    } else if (aaa == 5) {
        self->a = m;
        set_nz(self, self->a);
    } else if (aaa == 6) {
        cmp_gen(self, self->a, m);
    } else {
        sbc(self, m);
    }
}

/* --- группа cc=2: сдвиги, STX/LDX, DEC/INC, пересылки X ------------------ */

static void rmw_impl(Cpu *self, uint32_t op);

static void exec_rmw(Cpu *self, uint32_t op) {
    uint32_t aaa = op >> 5;
    uint32_t bbb = (op >> 2) & 7;
    if (bbb == 2 || bbb == 6) {
        rmw_impl(self, op);
        return;
    }
    if (bbb == 0 && aaa != 5) { /* #imm есть только у LDX */
        self->halted = true;
        return;
    }
    uint32_t ry = 0;
    if ((aaa == 4 || aaa == 5) && (bbb == 5 || bbb == 7)) {
        ry = 1; /* STX/LDX индексируются Y */
    }
    if (aaa == 4 && bbb == 7) { /* STX abs,Y не существует */
        self->halted = true;
        return;
    }
    uint32_t ad = ea_mem(self, bbb, ry);
    if (self->halted) {
        return;
    }
    if (aaa == 4) { /* STX */
        wr(self, ad, self->x);
        return;
    }
    if (aaa == 5) { /* LDX */
        self->x = rd(self, ad);
        set_nz(self, self->x);
        return;
    }
    uint32_t m = rd(self, ad);
    if (aaa == 6) { /* DEC */
        uint32_t dv = (m + 255) & 255;
        wr(self, ad, dv);
        set_nz(self, dv);
    } else if (aaa == 7) { /* INC */
        uint32_t iv = (m + 1) & 255;
        wr(self, ad, iv);
        set_nz(self, iv);
    } else { /* ASL/ROL/LSR/ROR по памяти */
        wr(self, ad, shift_val(self, aaa, m));
    }
}

static void rmw_impl(Cpu *self, uint32_t op) {
    if (op == 10 || op == 42 || op == 74 || op == 106) {
        self->a = shift_val(self, op >> 5, self->a);
    } else if (op == 138) { /* TXA */
        self->a = self->x;
        set_nz(self, self->a);
    } else if (op == 154) { /* TXS */
        self->sp = self->x;
    } else if (op == 170) { /* TAX */
        self->x = self->a;
        set_nz(self, self->x);
    } else if (op == 186) { /* TSX */
        self->x = self->sp;
        set_nz(self, self->x);
    } else if (op == 202) { /* DEX */
        self->x = (self->x + 255) & 255;
        set_nz(self, self->x);
    } else if (op == 234) { /* NOP */
        return;
    } else {
        self->halted = true;
    }
}

/* --- ветвления ----------------------------------------------------------- */

static void branch(Cpu *self, uint32_t op) {
    uint32_t off = fetch(self);
    uint32_t flag = self->n;
    uint32_t sel = op >> 6;
    if (sel == 1) {
        flag = self->v;
    } else if (sel == 2) {
        flag = self->c;
    } else if (sel == 3) {
        flag = self->z;
    }
    if (flag == ((op >> 5) & 1)) {
        if (off >= 128) { /* знаковое смещение: -256 ≡ +65280 (mod 65536) */
            self->pc = (self->pc + off + 65280) & 65535;
        } else {
            self->pc = (self->pc + off) & 65535;
        }
    }
}

/* --- группа cc=0: управление, стек, флаги, Y-операции -------------------- */

static void ctl_col2(Cpu *self, uint32_t op);
static void ctl_col6(Cpu *self, uint32_t op);
static void ctl_mem(Cpu *self, uint32_t op, uint32_t bbb);

static void exec_ctl(Cpu *self, uint32_t op) {
    if (op == 0) { /* BRK: вектор $FFFE; нулевой вектор — останов */
        uint32_t vec = rd16(self, 65534);
        if (vec == 0) {
            self->halted = true;
            return;
        }
        uint32_t ret = (self->pc + 1) & 65535;
        push(self, ret >> 8);
        push(self, ret & 255);
        push(self, flags_byte(self, 1));
        self->i = 1;
        self->pc = vec;
        return;
    }
    if (op == 32) { /* JSR */
        uint32_t t = fetch16(self);
        uint32_t ra = (self->pc + 65535) & 65535;
        push(self, ra >> 8);
        push(self, ra & 255);
        self->pc = t;
        return;
    }
    if (op == 64) { /* RTI */
        uint32_t p = pop(self);
        set_flags(self, p);
        uint32_t lo = pop(self);
        self->pc = lo | (pop(self) << 8);
        return;
    }
    if (op == 96) { /* RTS */
        uint32_t lo2 = pop(self);
        self->pc = ((lo2 | (pop(self) << 8)) + 1) & 65535;
        return;
    }
    if (op == 76) { /* JMP abs */
        self->pc = fetch16(self);
        return;
    }
    if (op == 108) { /* JMP (ind) с багом границы страницы */
        uint32_t p2 = fetch16(self);
        uint32_t hi_ad = (p2 & 65280) | ((p2 + 1) & 255);
        self->pc = rd(self, p2) | (rd(self, hi_ad) << 8);
        return;
    }
    uint32_t bbb = (op >> 2) & 7;
    if (bbb == 2) {
        ctl_col2(self, op);
        return;
    }
    if (bbb == 6) {
        ctl_col6(self, op);
        return;
    }
    ctl_mem(self, op, bbb);
}

static void ctl_col2(Cpu *self, uint32_t op) {
    if (op == 8) { /* PHP (B=1 на стеке) */
        push(self, flags_byte(self, 1));
    } else if (op == 40) { /* PLP */
        uint32_t p = pop(self);
        set_flags(self, p);
    } else if (op == 72) { /* PHA */
        push(self, self->a);
    } else if (op == 104) { /* PLA */
        self->a = pop(self);
        set_nz(self, self->a);
    } else if (op == 136) { /* DEY */
        self->y = (self->y + 255) & 255;
        set_nz(self, self->y);
    } else if (op == 168) { /* TAY */
        self->y = self->a;
        set_nz(self, self->y);
    } else if (op == 200) { /* INY */
        self->y = (self->y + 1) & 255;
        set_nz(self, self->y);
    } else if (op == 232) { /* INX */
        self->x = (self->x + 1) & 255;
        set_nz(self, self->x);
    } else {
        self->halted = true;
    }
}

static void ctl_col6(Cpu *self, uint32_t op) {
    if (op == 24) { /* CLC */
        self->c = 0;
    } else if (op == 56) { /* SEC */
        self->c = 1;
    } else if (op == 88) { /* CLI */
        self->i = 0;
    } else if (op == 120) { /* SEI */
        self->i = 1;
    } else if (op == 152) { /* TYA */
        self->a = self->y;
        set_nz(self, self->a);
    } else if (op == 184) { /* CLV */
        self->v = 0;
    } else if (op == 216) { /* CLD */
        self->d = 0;
    } else if (op == 248) { /* SED */
        self->d = 1;
    } else {
        self->halted = true;
    }
}

static void ctl_mem(Cpu *self, uint32_t op, uint32_t bbb) {
    uint32_t aaa = op >> 5;
    if (aaa == 1 && (bbb == 1 || bbb == 3)) { /* BIT zp/abs */
        uint32_t m = rd(self, ea_mem(self, bbb, 0));
        self->n = m >> 7;
        self->v = (m >> 6) & 1;
        if ((self->a & m) == 0) {
            self->z = 1;
        } else {
            self->z = 0;
        }
        return;
    }
    if (aaa == 4 && (bbb == 1 || bbb == 3 || bbb == 5)) { /* STY */
        uint32_t ad = ea_mem(self, bbb, 0);
        wr(self, ad, self->y);
        return;
    }
    if (aaa == 5) { /* LDY: #imm/zp/abs/zp,X/abs,X */
        uint32_t ad2 = ea_mem(self, bbb, 0);
        if (self->halted) {
            return;
        }
        self->y = rd(self, ad2);
        set_nz(self, self->y);
        return;
    }
    if ((aaa == 6 || aaa == 7) && (bbb == 0 || bbb == 1 || bbb == 3)) {
        uint32_t m2 = rd(self, ea_mem(self, bbb, 0));
        if (aaa == 6) { /* CPY */
            cmp_gen(self, self->y, m2);
        } else { /* CPX */
            cmp_gen(self, self->x, m2);
        }
        return;
    }
    self->halted = true;
}

/* --- шаг ----------------------------------------------------------------- */

static void step(Cpu *self) {
    if (self->halted) {
        return;
    }
    uint32_t before = self->pc;
    uint32_t op = fetch(self);
    uint32_t cc = op & 3;
    if (cc == 1) {
        exec_alu(self, op);
    } else if ((op & 31) == 16) {
        branch(self, op);
    } else if (cc == 2) {
        exec_rmw(self, op);
    } else if (cc == 0) {
        exec_ctl(self, op);
    } else { /* cc=3 — неофициальные опкоды */
        self->halted = true;
    }
    if (self->pc == before) { /* jam: переход сам на себя */
        self->halted = true;
    }
    self->steps = self->steps + 1;
}

/* --- вывод (lib/Hex.eat: строчные a..f) ---------------------------------- */

static char hex_digit(uint32_t v) {
    if (v < 10) {
        return (char)(v + 48);
    }
    return (char)(v + 87); /* a..f */
}

static void write_hex8(uint32_t v) {
    putchar(hex_digit(v >> 4));
    putchar(hex_digit(v & 15));
}

static void write_hex16(uint32_t v) {
    write_hex8(v >> 8);
    write_hex8(v & 255);
}

/* --- точка входа: ROM со stdin в $0600, PC=$0600, SP=$FD ----------------- */

#define LOAD 1536u

int main(void) {
    Cpu cpu;
    cpu.a = 0; cpu.x = 0; cpu.y = 0; cpu.sp = 253; cpu.pc = 0;
    cpu.c = 0; cpu.z = 0; cpu.i = 0; cpu.d = 0; cpu.v = 0; cpu.n = 0;
    cpu.halted = false; cpu.steps = 0;
    for (uint32_t j = 0; j < 65536u; j++) {
        cpu.mem[j] = 0;
    }
    uint32_t nb = 0;
    bool eof = false;
    for (uint32_t k = 0; k < 63488u; k++) {
        if (!eof) {
            int ch = getchar();
            if (ch == EOF) {
                eof = true;
            } else {
                wr(&cpu, LOAD + nb, (uint32_t)(ch & 255));
                nb = nb + 1;
            }
        }
    }
    cpu.pc = LOAD;
    for (;;) {
        if (cpu.halted) {
            break;
        }
        step(&cpu);
    }
    printf("A=");
    write_hex8(cpu.a);
    printf(" X=");
    write_hex8(cpu.x);
    printf(" Y=");
    write_hex8(cpu.y);
    printf(" SP=");
    write_hex8(cpu.sp);
    printf(" PC=");
    write_hex16(cpu.pc);
    printf(" P=%u%u1x%u%u%u%u steps=%u bytes=%u\n",
           cpu.n, cpu.v, cpu.d, cpu.i, cpu.z, cpu.c, cpu.steps, nb);
    printf("0200:");
    for (uint32_t k = 0; k < 16u; k++) {
        printf(" ");
        write_hex8(rd(&cpu, 512 + k));
    }
    printf("\n");
    return 0;
}
