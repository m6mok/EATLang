"""CLI компилятора: python -m eatc check <файлы...>."""

import sys

from .checks import check_program
from .errors import EatError
from .parser import parse_file
from .typechecker import typecheck


def cmd_check(paths: list[str]) -> int:
    failed = 0
    for path in paths:
        try:
            program = parse_file(path)
            stats = check_program(program, path)
            typed = typecheck(program, path)
        except EatError as err:
            print(err, file=sys.stderr)
            failed += 1
            continue
        print(
            f"OK {path} — funcs: {stats['funcs']}, "
            f"structs: {stats['structs']}, tests: {stats['tests']}, "
            f"stmts: {stats['stmts']}, stack depth: {typed.stack_depth}"
        )
    if failed:
        print(f"\nFAILED: {failed} из {len(paths)}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "check":
        return cmd_check(argv[1:])
    print(
        "использование: python -m eatc check <файлы.eat...>", file=sys.stderr
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
