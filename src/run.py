from argparse import ArgumentParser, Namespace
from collections.abc import Iterable
from ast import parse

from google.protobuf.text_format import Parse, ParseError

from proto.program_pb2 import (
    Program,
    Do,
    FuncDo,
    Def,
    Set,
    Using,
    LoopCondition,
    IfCondition,
    Else,
)


PARSER = "PARS"
LINTER = "LINT"
PROGRAM = "PROG"
DEBUG = "DEBG"


class LintState:
    def __init__(self) -> None:
        self.vars = {}


def pprint(
    prefix: str = "",
    message=None,
    log_level: int = 0,
    indent: int = 0,
    *,
    do_print: bool = True,
    indent_size: int = 1,
    indent_string: str = "| ",
    stack: list[str] = [],
    release_stack: bool = False,
) -> str | None:
    if release_stack and len(stack) > 0:
        print("\n".join(stack))
        stack.clear()

    line = f"[{prefix}] {indent_string * indent_size * indent}{message}"
    if do_print:
        if (
            prefix == PARSER and log_level > 1 or
            prefix == LINTER and log_level > 1 or
            prefix == DEBUG and log_level > 2
        ):
            stack.append(line)
    else:
        return line


def get_args() -> Namespace:
    parser = ArgumentParser(
        description="Пример программы с парсингом аргументов"
    )

    parser.add_argument(
        "--log-level",
        type=int,
        default=0,
        help=(
            "Уровень логирования."
            "0 - ничего, 1 - ошибки, "
            "2 - информативное, 3 - дебаг"
        )
    )
    parser.add_argument(
        "filepath",
        help="Путь до файла для обработки"
    )

    return parser.parse_args()


def parse_program(
    program: Program,
    filepath: str,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            Parse(f.read(), program)
        except ParseError as pe:
            return "\n" + pprint(
                PARSER,
                str(pe),
                log_level,
                indent + 1,
                do_print=False,
            )


def lint_using(
    using: Iterable[Using],
    state: LintState,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    pprint(LINTER, "using", log_level, indent)

    for el in using:
        shape: str | None = None
        msg: str

        if el.HasField("i32"):
            msg = el.i32
            shape = "i32"
        elif el.HasField("ui32"):
            msg = el.ui32
            shape = "ui32"
        elif el.HasField("char"):
            msg = el.char
            shape = "char"
        elif el.HasField("name"):
            msg = el.name
        else:
            pprint(LINTER, "Name is not defined", log_level, indent + 1)
            continue
        if el.HasField("shape"):
            if shape is None:
                shape = el.shape
            else:
                pprint(
                    LINTER,
                    f"Shape already defined: `{shape}`, found `{el.shape}`",
                    log_level,
                    indent + 1,
                )
                continue
        elif shape is None:
            pprint(
                LINTER,
                f"Shape is not defined for: `{el.name}`",
                log_level,
                indent + 1,
            )
            continue
        msg += ": " + shape
        if el.HasField("cluster"):
            msg += f"[{el.cluster}]"
        pprint(LINTER, msg, log_level, indent + 1)


def lint_set(
    set: Iterable[Set],
    state: LintState,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    pprint(LINTER, "set", log_level, indent)
    for line in set:
        msg = ""
        if line.HasField("eval"):
            msg += f"`{line.var}` eval `{line.eval}`"
        elif line.HasField("cast"):
            msg += f"`{line.var}` cast from `{line.cast}`"
        elif line.HasField("format"):
            msg += f"`{line.var}` format by `{line.format}`"
        elif line.HasField("i32"):
            state.vars[line.var] = int(line.i32)
            msg += f"{line.var}: i32 = {line.i32}"
        elif line.HasField("ui32"):
            state.vars[line.var] = int(line.ui32)
            msg += f"{line.var}: ui32 = {line.ui32}"
        elif line.HasField("char"):
            state.vars[line.var] = line.char
            msg += f"{line.var}: char = {line.char}"
        pprint(LINTER, msg, log_level, indent + 1)


def lint_if(
    _if: IfCondition,
    state: LintState,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    pprint(LINTER, "if", log_level, indent)
    pprint(LINTER, f"true: {_if.true}", log_level, indent + 1)
    if _if.HasField("call"):
        pprint(LINTER, f"call: {_if.call}", log_level, indent + 1)
    elif _if.HasField("ret"):
        pprint(LINTER, f"ret: {_if.ret}", log_level, indent + 1)
    elif _if.HasField("alias"):
        pprint(LINTER, f"alias: {_if.alias}", log_level, indent + 1)


def lint_while(
    _while: LoopCondition,
    state: LintState,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    pprint(LINTER, "while", log_level, indent)
    pprint(LINTER, f"true: {_while.true}", log_level, indent + 1)
    pprint(LINTER, f"call: {_while.call}", log_level, indent + 1)


def lint_until(
    _until: LoopCondition,
    state: LintState,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    pprint(LINTER, "until", log_level, indent)
    if _until.HasField("true"):
        pprint(LINTER, f"true: {_until.true}", log_level, indent + 1)
    elif _until.HasField("false"):
        pprint(LINTER, f"false: {_until.false}", log_level, indent + 1)
    if _until.HasField("call"):
        pprint(LINTER, f"call: {_until.call}", log_level, indent + 1)


def lint_else(
    _else: Iterable[Else],
    state: LintState,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    pprint(LINTER, "else", log_level, indent)
    for line in _else:
        if line.HasField("call"):
            pprint(LINTER, f"call: {line.call}", log_level, indent + 1)
        elif line.HasField("ret"):
            pprint(LINTER, f"ret: {line.ret}", log_level, indent + 1)
        elif line.HasField("alias"):
            pprint(LINTER, f"alias: {line.alias}", log_level, indent + 1)


def lint_do(
    do: Iterable[Do],
    state: LintState,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    pprint(LINTER, "do", log_level, indent)

    do_size = len(do)

    for i, el in enumerate(do):
        if el.HasField("commence"):
            pprint(LINTER, f"commence `{el.commence}`", log_level, indent + 1)
        if len(el.set) > 0:
            lint_set(el.set, state, log_level, indent + 1)
        if (_if := getattr(el, "if")).true != "":
            lint_if(_if, state, log_level, indent + 1)
        elif (_while := getattr(el, "while")).true != "":
            lint_while(_while, state, log_level, indent + 1)
        elif el.HasField("until"):
            lint_until(el.until, state, log_level, indent + 1)
        elif el.HasField("call"):
            pprint(LINTER, f"call: {el.call}", log_level, indent + 1)
        if len(_else := getattr(el, "else")) > 0:
            lint_else(_else, state, log_level, indent + 1)
        if el.HasField("conclude"):
            pprint(LINTER, f"conclude `{el.conclude}`", log_level, indent + 1)
        if i + 1 < do_size:
            pprint(LINTER, "|-", log_level, indent)


def lint_func_do(
    func_do: Iterable[FuncDo],
    state: LintState,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    func_do_size = len(func_do)

    for i, el in enumerate(func_do):
        if el.HasField("commence"):
            pprint(LINTER, f"commence: `{el.commence}`", log_level, indent + 1)
        if len(el.set) > 0:
            lint_set(el.set, state, log_level, indent + 1)
        if (_if := getattr(el, "if")).true != "":
            lint_if(_if, state, log_level, indent + 1)
        elif (_while := getattr(el, "while")).true != "":
            lint_while(_while, state, log_level, indent + 1)
        elif el.HasField("until"):
            lint_until(el.until, state, log_level, indent + 1)
        elif el.HasField("call"):
            pprint(LINTER, el.call, log_level, indent + 1)
        if len(_else := getattr(el, "else")) > 0:
            lint_else(_else, state, log_level, indent + 1)
        if el.HasField("conclude"):
            pprint(LINTER, f"conclude: `{el.conclude}`", log_level, indent + 1)
        if i + 1 < func_do_size:
            pprint(LINTER, "|-", log_level, indent)


def lint_def(
    _def: Iterable[Def],
    state: LintState,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    pprint(LINTER, "def", log_level, indent)
    for el in _def:
        if el.HasField("name"):
            pprint(LINTER, f"void `{el.name}`", log_level, indent + 1)
        if el.HasField("calling"):
            pprint(LINTER, f"calling `{el.calling}`", log_level, indent + 1)
        if el.HasField("receive"):
            pprint(LINTER, f"receive `{el.receive}`", log_level, indent + 1)
        if len(func_do := el.do) > 0:
            lint_func_do(func_do, state, log_level, indent + 1)


def lint_program(
    p: Program,
    log_level: int = 0,
    indent: int = 0,
) -> str | None:
    state = LintState()

    if p.HasField("name"):
        pprint(LINTER, f"name: `{p.name}`", log_level, indent + 1)

    if p.HasField("version"):
        pprint(LINTER, f"version: `{p.version}`", log_level, indent + 1)

    if len(using := p.using) > 0:
        lint_using(using, state, log_level, indent + 1)

    if len(_def := getattr(p, "def")) > 0:
        lint_def(_def, state, log_level, indent + 1)

    if len(do := p.do) > 0:
        lint_do(do, state, log_level, indent + 1)


def process_program(p: Program, debug: bool = False) -> str | None:
    pass


def main(args: Namespace) -> None:
    ll: int = args.log_level
    indent: int = 0

    pprint(DEBUG, f"Program filepath: `{args.filepath}`", ll, indent)
    pprint(release_stack=True)

    program = Program()

    result = parse_program(program, args.filepath, ll)
    if result is None:
        pprint(PARSER, "Program parsed successfully", ll, indent)
        pprint(release_stack=True)
    else:
        pprint(DEBUG, f"Program parsed with error: {result}", ll, indent)
        return

    result = lint_program(program, ll)
    if result is None:
        pprint(LINTER, "Program linted successfully")
        pprint(release_stack=True)
    else:
        pprint(DEBUG, f"Program linted with error: {result}", ll, indent)
        return

    result = process_program(program, ll)
    if result is None:
        pprint(DEBUG, "Program ended successfully", ll, indent)
        pprint(release_stack=True)
    else:
        pprint(DEBUG, f"Program ended with error: {result}", ll, indent)
        return


if __name__ == "__main__":
    main(get_args())
    pprint(release_stack=True)
