"""Автосверка §8 против памяти платы (MCU_PLAN §4).

Вход: файл с отчётом `eatc build` (стек худшей цепочки), ELF и
размер RAM платы (board.mk). RAM должна вместить .data + .bss +
стек §8 — иначе сборка падает здесь, а не загадочно на железе.
"""

import re
import subprocess
import sys


def main() -> int:
    report_path, elf_path, ram_size = (
        sys.argv[1],
        sys.argv[2],
        int(sys.argv[3]),
    )
    text = open(report_path, encoding="utf-8").read()
    m = re.search(r"стек худшей цепочки ≤ (\d+) Б", text)
    if m is None:
        print("check_mem: в отчёте нет строки §8 о стеке", file=sys.stderr)
        return 1
    stack = int(m.group(1))
    out = subprocess.run(
        ["xcrun", "llvm-size", elf_path], capture_output=True, text=True
    ).stdout.splitlines()
    data, bss = (int(x) for x in out[1].split()[1:3])
    need = stack + data + bss
    verdict = "OK" if need <= ram_size else "ПЕРЕПОЛНЕНИЕ"
    print(
        f"  память платы: стек §8 {stack} + .data {data} + .bss {bss} "
        f"= {need} Б из {ram_size} Б RAM — {verdict}"
    )
    return 0 if need <= ram_size else 1


if __name__ == "__main__":
    sys.exit(main())
