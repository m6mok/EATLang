"""CLI компилятора.

python -m eatc check <файлы...>   — каждый файл отдельно: парсинг,
                                    проверки, типы, test-блоки
python -m eatc run <файлы...>     — check + запуск main интерпретатором
python -m eatc build <файлы...> [-o out] — check + LLVM → бинарник
python -m eatc lex <файл>         — эталонный дамп токенов (сверка
                                    с self-hosted лексером, selfhost/)
python -m eatc parse <файл>       — эталонный дамп AST (сверка
                                    с self-hosted парсером, selfhost/)
python -m eatc ir <файл>          — эталонный текстовый LLVM IR без
                                    верификатора (сверка с self-hosted
                                    эмиттером, selfhost/Ir.eat)

Модули: run/build принимают несколько файлов — одна программа с
единым пространством имён; последний файл — главный (даёт имя
бинарника). Эквивалент для self-host: cat файлов в stdin.
"""

import sys
from pathlib import Path

from .checks import check_program
from .driver import build_stream, has_imports
from .errors import EatError
from .interpreter import Interpreter
from .lexer import Lexer
from .parser import Parser, parse_file, parse_files
from .typechecker import typecheck

# --lib-корни драйвера (заполняет main из argv)
LIB_ROOTS: list = []


def _load_program(paths: list):
    """Программа из списка файлов. Единственный файл с import-блоками
    включает драйвер (docs/MODULES_PLAN.md §4): DAG модулей + Rt.eat
    конкатенируются в поток с директивами #module."""
    main = paths[-1]
    if len(paths) == 1:
        program = parse_file(main)
        if has_imports(program):
            stream = build_stream(main, LIB_ROOTS)
            tokens = Lexer(stream, main).tokenize()
            program = Parser(tokens, main).parse_program()
        return program, main
    return parse_files(paths), main


def _compile(path: str):
    program, _ = _load_program([path])
    stats = check_program(program, path)
    typed = typecheck(program, path)
    return program, stats, typed


def _compile_many(paths: list):
    program, main = _load_program(paths)
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


def cmd_run(paths: list, prog_args: list | None = None) -> int:
    try:
        program, _, _, main = _compile_many(paths)
        argv = [a.encode("utf-8") for a in (prog_args or [])]
        interp = Interpreter(program, main, argv=argv)
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

    valued = {T.INT, T.STRING, T.CHAR, T.IDENT, T.MODULE}
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


def cmd_ir(path: str, trap_codes: bool = False) -> int:
    from .codegen import emit_ir

    try:
        program = parse_file(path)
        check_program(program, path)
        typed = typecheck(program, path)
        text = emit_ir(program, typed.checker, trap_codes=trap_codes)
    except (OSError, EatError) as err:
        print(err, file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


_KIND_LABEL = {
    "overflow": "переполнение",
    "div": "деление",
    "shift": "сдвиг",
    "bounds": "границы",
    "cast": "cast",
    "requires": "requires",
    "ensures": "ensures",
    "assert": "assert",
}


def cmd_build(
    paths: list, out: str | None, trap_codes: bool = False,
    link: bool = True, release: bool = False, fold: bool = False,
) -> int:
    from .codegen import compile_binary
    from .verifier import verify

    if out is None:
        out = str(Path("build") / Path(paths[-1]).stem)
    try:
        program, _, typed, main = _compile_many(paths)
        tests = Interpreter(program, main).run_tests()
        folded = 0
        if fold:
            # ярус B (§11): свёртка вызовов с константными аргументами в
            # телах — до verify, чтобы точки [v,v] сняли проверки ниже.
            # Только build-путь; `eatc ir` не сворачивает (канон IR цел)
            from .comptime import fold_calls
            folded = fold_calls(program, typed.checker, main)
        proofs = verify(program, typed.checker)
        binary, report = compile_binary(
            program, typed.checker, main, out, trap_codes=trap_codes,
            link=link, release=release,
        )
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
    if fold:
        print(f"  ярус B: свёрнуто вызовов в литералы: {folded}")
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


def cmd_stream(path: str) -> int:
    """Печать потока драйвера: Rt + модули DAG с #module-директивами —
    вход для self-hosted компилятора (сверки Makefile)."""
    try:
        sys.stdout.write(build_stream(path, LIB_ROOTS))
    except (OSError, EatError) as err:
        print(err, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    # --trap-codes (ir/build): режим кодов вместо trap-строк —
    # метрика флеша МК; таблица кодов — комментарии в хвосте .ll
    trap_codes = "--trap-codes" in argv
    if trap_codes:
        argv = [a for a in argv if a != "--trap-codes"]
    # --lib DIR (повторяемый): корни разрешения путей import
    while "--lib" in argv:
        i = argv.index("--lib")
        if i + 1 >= len(argv):
            print("после --lib ожидается каталог", file=sys.stderr)
            return 2
        LIB_ROOTS.append(argv[i + 1])
        del argv[i:i + 2]
    # --no-bin (build): только .ll + отчёт §8, без хостовой линковки —
    # для кросс-сборок МК (extern-программы линкует make mcu)
    no_bin = "--no-bin" in argv
    if no_bin:
        argv = [a for a in argv if a != "--no-bin"]
    # --release / -r (build): LTO на линковке (clang -flto) — −29 %
    # размера ценой ~2.75 с линковки; для финальных/МК-сборок, не для
    # цикла разработки. Канон .ll и семантика не меняются
    release = "--release" in argv or "-r" in argv
    if release:
        argv = [a for a in argv if a not in ("--release", "-r")]
    # --fold (build, §11 ярус B): свёртка вызовов с константными
    # аргументами в литералы. Под флагом на время обкатки; по умолчанию
    # выключено — весь гейт и канон `eatc ir` байт-в-байт неизменны
    fold = "--fold" in argv
    if fold:
        argv = [a for a in argv if a != "--fold"]
    if len(argv) >= 2 and argv[0] == "check":
        return cmd_check(argv[1:])
    if len(argv) >= 2 and argv[0] == "run":
        # `run FILE... -- ARG...`: всё после `--` — argv программы
        # (аксиомы arg_count/arg_len/arg_byte); имя программы не входит
        rest = argv[1:]
        prog_args: list = []
        if "--" in rest:
            i = rest.index("--")
            rest, prog_args = rest[:i], rest[i + 1:]
        if rest:
            return cmd_run(rest, prog_args)
    if len(argv) == 2 and argv[0] == "lex":
        return cmd_lex(argv[1])
    if len(argv) == 2 and argv[0] == "parse":
        return cmd_parse(argv[1])
    if len(argv) == 2 and argv[0] == "sig":
        return cmd_sig(argv[1])
    if len(argv) == 2 and argv[0] == "typed":
        return cmd_typed(argv[1])
    if len(argv) == 2 and argv[0] == "ir":
        return cmd_ir(argv[1], trap_codes=trap_codes)
    if len(argv) == 2 and argv[0] == "stream":
        return cmd_stream(argv[1])
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
            return cmd_build(
                args, out, trap_codes=trap_codes, link=not no_bin,
                release=release, fold=fold,
            )
    print(
        "использование: python -m eatc "
        "(check <файлы.eat...> | run <файлы...> [-- <арг>...] | "
        "build <файлы...> [-o out] [--trap-codes] [--release|-r] [--fold] | "
        "lex <файл> | "
        "parse <файл> | ir <файл> [--trap-codes] | stream <файл>) "
        "[--lib DIR]...",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
