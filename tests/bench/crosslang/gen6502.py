"""Генератор нагрузочного ROM для макробенча mos6502
(docs/plans/CROSSLANG_BENCH_PLAN.md, этап 3).

Программа 6502 (загрузка в $0600, как examples/mos6502/Main.eat):
четыре вложенных счётчика — внутренний zp $11 (256 итераций DEC/BNE),
средний Y (--middle итераций), внешний X (--outer итераций),
самый внешний zp $12 (--top итераций); тело внутреннего витка мешает
бегущую контрольную сумму в zp $10 (EOR по счётчику + ADC константы).
По исчерпании — контрольная сумма и счётчики в $0200.., BRK с нулевым
вектором = детерминированный останов эмулятора.

Шагов эмулятора ~ top * outer * middle * 256 * 7 — размер нагрузки
задаётся параметрами. Использованы только официальные опкоды.

Запуск: python tests/bench/crosslang/gen6502.py --top 8 --outer 32 \
        --middle 255 -o build/bench/crosslang/heavy.rom
"""

import argparse
from pathlib import Path


def assemble(outer: int, middle: int, top: int) -> bytes:
    assert 1 <= outer <= 255 and 1 <= middle <= 255 and 1 <= top <= 255
    rom = bytearray()

    def emit(*bs):
        rom.extend(bs)

    # $0600: LDA #0; STA $10 (сумма); STA $11 (внутренний счётчик);
    #        LDA #top; STA $12 (самый внешний счётчик)
    emit(0xA9, 0x00)          # LDA #$00
    emit(0x85, 0x10)          # STA $10
    emit(0x85, 0x11)          # STA $11
    emit(0xA9, top)           # LDA #top
    emit(0x85, 0x12)          # STA $12
    # top:    LDX #outer
    top_at = len(rom)
    emit(0xA2, outer)         # LDX #outer
    # outer:  LDY #middle
    outer_at = len(rom)
    emit(0xA0, middle)        # LDY #middle
    # middle: (внутренний цикл: 256 витков DEC $11 до нуля)
    middle_at = len(rom)
    # inner:  LDA $10; EOR $11; CLC; ADC #$1D; STA $10; DEC $11;
    #         BNE inner
    inner_at = len(rom)
    emit(0xA5, 0x10)          # LDA $10
    emit(0x45, 0x11)          # EOR $11
    emit(0x18)                # CLC
    emit(0x69, 0x1D)          # ADC #$1D
    emit(0x85, 0x10)          # STA $10
    emit(0xC6, 0x11)          # DEC $11
    emit(0xD0, (inner_at - (len(rom) + 2)) & 0xFF)   # BNE inner
    #         DEY; BNE middle
    emit(0x88)                # DEY
    emit(0xD0, (middle_at - (len(rom) + 2)) & 0xFF)  # BNE middle
    #         DEX; BNE outer
    emit(0xCA)                # DEX
    emit(0xD0, (outer_at - (len(rom) + 2)) & 0xFF)   # BNE outer
    #         DEC $12; BNE top (переход дальний — через JMP)
    emit(0xC6, 0x12)          # DEC $12
    emit(0xF0, 0x03)          # BEQ +3 (мимо JMP)
    emit(0x4C, (0x0600 + top_at) & 0xFF,
         ((0x0600 + top_at) >> 8) & 0xFF)            # JMP top
    # финал: сумма и счётчики → $0200.., BRK (вектор $FFFE нулевой)
    emit(0xA5, 0x10)          # LDA $10
    emit(0x8D, 0x00, 0x02)    # STA $0200
    emit(0xA9, outer)         # LDA #outer
    emit(0x8D, 0x01, 0x02)    # STA $0201
    emit(0xA9, middle)        # LDA #middle
    emit(0x8D, 0x02, 0x02)    # STA $0202
    emit(0x00)                # BRK
    return bytes(rom)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=1)
    ap.add_argument("--outer", type=int, default=32)
    ap.add_argument("--middle", type=int, default=255)
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(assemble(args.outer, args.middle, args.top))
    steps = args.top * args.outer * args.middle * 256 * 7
    print(f"{out}: {out.stat().st_size} байт, ~{steps / 1e6:.1f}M шагов")


if __name__ == "__main__":
    main()
