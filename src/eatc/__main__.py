"""CLI компилятора.

python -m eatc check <файлы...>  — компиляция: парсинг, проверки,
                                   типы, исполнение test-блоков
python -m eatc run <файл>        — check + запуск main
"""

import sys

from .checks import check_program
from .errors import EatError
from .interpreter import Interpreter
from .parser import parse_file
from .typechecker import typecheck


def _compile(path: str):
    program = parse_file(path)
    stats = check_program(program, path)
    typed = typecheck(program, path)
    return program, stats, typed


def cmd_check(paths: list[str]) -> int:
    failed = 0
    for path in paths:
        try:
            program, stats, typed = _compile(path)
            tests = Interpreter(program, path).run_tests()
        except EatError as err:
            print(err, file=sys.stderr)
            failed += 1
            continue
        print(
            f"OK {path} — funcs: {stats['funcs']}, "
            f"structs: {stats['structs']}, stmts: {stats['stmts']}, "
            f"stack depth: {typed.stack_depth}, "
            f"tests passed: {len(tests)}"
        )
    if failed:
        print(f"\nFAILED: {failed} из {len(paths)}", file=sys.stderr)
        return 1
    return 0


def cmd_run(path: str) -> int:
    try:
        program, _, _ = _compile(path)
        interp = Interpreter(program, path)
        interp.run_tests()
        interp.run_main()
    except EatError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "check":
        return cmd_check(argv[1:])
    if len(argv) == 2 and argv[0] == "run":
        return cmd_run(argv[1])
    print(
        "использование: python -m eatc (check <файлы.eat...> | run <файл>)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
