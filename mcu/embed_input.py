"""Вход программы -> C-массив eat_input для образа МК.

У UART нет конца потока, поэтому stdin-вход программы (например,
ROM эмулятора 6502) зашивается в прошивку: сильные определения
перекрывают слабые умолчания из mcu/runtime_mcu.c.
"""

import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("использование: embed_input.py <файл входа>", file=sys.stderr)
        return 2
    data = open(sys.argv[1], "rb").read()
    body = ",".join(str(b) for b in data) if data else "0"
    print("#include <stdint.h>")
    print(f"const uint32_t eat_input_len = {len(data)};")
    print(f"const uint8_t eat_input[] = {{{body}}};")
    return 0


if __name__ == "__main__":
    sys.exit(main())
