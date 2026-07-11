"""CLI компилятора.

python -m eatc check <файлы...>   — каждый файл отдельно: парсинг,
                                    проверки, типы, test-блоки
python -m eatc run <файлы...>     — check + запуск main интерпретатором
python -m eatc build <файлы...> [-o out] — check + LLVM → бинарник
python -m eatc lex <файл>         — эталонный дамп токенов (сверка
                                    с self-hosted лексером, selfhost/)
python -m eatc parse <файл>       — эталонный дамп AST (сверка
                                    с self-hosted парсером, selfhost/)

Модули: run/build принимают несколько файлов — одна программа с
единым пространством имён; последний файл — главный (даёт имя
бинарника). Эквивалент для self-host: cat файлов в stdin.
"""

import sys
from pathlib import Path

from .checks import check_program
from .errors import EatError
from .interpreter import Interpreter
from .parser import parse_file, parse_files
from .typechecker import typecheck


def _compile(path: str):
    program = parse_file(path)
    stats = check_program(program, path)
    typed = typecheck(program, path)
    return program, stats, typed


def _compile_many(paths: list):
    main = paths[-1]
    program = parse_files(paths)
    stats = check_program(program, main)
    typed = typecheck(program, main)
    return program, stats, typed, main


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


def cmd_run(paths: list) -> int:
    try:
        program, _, _, main = _compile_many(paths)
        interp = Interpreter(program, main)
        interp.run_tests()
        interp.run_main()
    except EatError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


def _esc_value(value: str) -> str:
    """Экранирование значения токена для построчного дампа."""
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\0", "\\0")
    )


def cmd_lex(path: str) -> int:
    from .lexer import Lexer
    from .tokens import T

    valued = {T.INT, T.STRING, T.CHAR, T.IDENT}
    try:
        source = Path(path).read_text(encoding="utf-8")
        tokens = Lexer(source, path).tokenize()
    except (OSError, EatError) as err:
        print(err, file=sys.stderr)
        return 1
    for tok in tokens:
        line = f"{tok.line}:{tok.col} {tok.type.name}"
        if tok.type in valued:
            line += f" {_esc_value(tok.value)}"
        print(line)
    return 0


def cmd_parse(path: str) -> int:
    from .astdump import dump_program

    try:
        program = parse_file(path)
    except (OSError, EatError) as err:
        print(err, file=sys.stderr)
        return 1
    for line in dump_program(program):
        print(line)
    return 0


def cmd_sig(path: str) -> int:
    from .sigdump import dump_signatures

    try:
        program = parse_file(path)
        lines = dump_signatures(program, path)
    except (OSError, EatError) as err:
        print(err, file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


def cmd_typed(path: str) -> int:
    from .typeddump import dump_typed

    try:
        program = parse_file(path)
        lines = dump_typed(program, path)
    except (OSError, EatError) as err:
        print(err, file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


_KIND_LABEL = {
    "overflow": "переполнение",
    "div": "деление",
    "bounds": "границы",
    "cast": "cast",
    "requires": "requires",
    "ensures": "ensures",
    "assert": "assert",
}


def cmd_build(paths: list, out: str | None) -> int:
    from .codegen import compile_binary
    from .verifier import verify

    if out is None:
        out = str(Path("build") / Path(paths[-1]).stem)
    try:
        program, _, typed, main = _compile_many(paths)
        tests = Interpreter(program, main).run_tests()
        proofs = verify(program, typed.checker)
        binary, report = compile_binary(program, typed.checker, main, out)
    except EatError as err:
        print(err, file=sys.stderr)
        return 1
    print(
        f"OK {binary} — stack depth: {typed.stack_depth}, "
        f"tests passed: {len(tests)}"
    )
    left = proofs["total"] - proofs["proven"]
    print(
        f"  верификация: доказано {proofs['proven']} из "
        f"{proofs['total']} проверок ({left} остаётся в рантайме)"
    )
    detail = ", ".join(
        f"{_KIND_LABEL[k]}: {v[0]}/{v[1]}"
        for k, v in sorted(proofs["by_kind"].items())
    )
    if detail:
        print(f"    {detail}")
    print(
        f"  память (§8): стек худшей цепочки ≤ {report['stack_bytes']} Б, "
        f"статические данные {report['globals_bytes']} Б"
    )
    for key, size in sorted(report["frames"].items(), key=lambda kv: -kv[1]):
        print(f"    кадр {key}: {size} Б")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "check":
        return cmd_check(argv[1:])
    if len(argv) >= 2 and argv[0] == "run":
        return cmd_run(argv[1:])
    if len(argv) == 2 and argv[0] == "lex":
        return cmd_lex(argv[1])
    if len(argv) == 2 and argv[0] == "parse":
        return cmd_parse(argv[1])
    if len(argv) == 2 and argv[0] == "sig":
        return cmd_sig(argv[1])
    if len(argv) == 2 and argv[0] == "typed":
        return cmd_typed(argv[1])
    if len(argv) >= 2 and argv[0] == "build":
        args = argv[1:]
        out = None
        if "-o" in args:
            i = args.index("-o")
            if i + 1 >= len(args) or i + 1 != len(args) - 1:
                print("после -o ожидается имя бинарника", file=sys.stderr)
                return 2
            out = args[i + 1]
            args = args[:i]
        if args:
            return cmd_build(args, out)
    print(
        "использование: python -m eatc "
        "(check <файлы.eat...> | run <файлы...> | "
        "build <файлы...> [-o out] | lex <файл> | parse <файл>)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
