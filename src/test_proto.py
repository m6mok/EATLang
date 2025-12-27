#!/usr/bin/env python3
"""
Простой тест для EATLang парсера
"""

import sys
from google.protobuf import text_format

from proto.program_pb2 import Program


def simple_test():
    if len(sys.argv) != 2:
        print("Usage: python simple_test.py <prototxt_file>")
        sys.exit(1)

    prototxt_file = sys.argv[1]

    # Простой парсинг
    program = Program()
    with open(prototxt_file, "r", encoding="utf-8") as f:
        text_format.Parse(f.read(), program)

    print(program)


if __name__ == "__main__":
    simple_test()
