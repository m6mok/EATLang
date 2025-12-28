from argparse import ArgumentParser, Namespace
from collections.abc import Iterable
from enum import Enum
from typing import Optional

from google.protobuf.text_format import Parse, ParseError

from proto.program_pb2 import (
    Program,
    Do,
    FuncDo,
    Def,
    Elif,
    Set,
    Using,
    LoopCondition,
    IfCondition,
    Else,
)


class LogLevel(Enum):
    NONE = 0
    ERROR = 1
    INFO = 2
    DEBUG = 3


class Logger:
    def __init__(self, log_level: LogLevel = LogLevel.NONE):
        self.log_level = log_level
        self._indent_level = 0
        self._indent_count = 1
        self._indent_string = "│ "
        self._buffer = []
        self._should_buffer = False

    def set_level(self, log_level: LogLevel) -> None:
        self.log_level = log_level

    @property
    def indent_level(self) -> int:
        return self._indent_level

    def indent(self) -> None:
        self._indent_level += 1

    def dedent(self) -> None:
        if self._indent_level > 0:
            self._indent_level -= 1

    def start_buffering(self) -> None:
        self._should_buffer = True
        self._buffer.clear()

    def stop_buffering(self) -> None:
        if self._buffer:
            print("\n".join(self._buffer))
        self._should_buffer = False
        self._buffer.clear()

    def _format_message(self, prefix: str, message: str, indent_offset: int = 0) -> str:
        indent = self._indent_level + indent_offset
        return f"[{prefix}] {self._indent_string * self._indent_count * indent}{message}"

    def _log(self, prefix: str, message: str, min_level: LogLevel, indent_offset: int = 0) -> None:
        if self.log_level.value < min_level.value:
            return

        formatted = self._format_message(prefix, message, indent_offset)

        if self._should_buffer:
            self._buffer.append(formatted)
        else:
            print(formatted)

    def error(self, message: str, indent_offset: int = 0) -> None:
        self._log("ERR", message, LogLevel.ERROR, indent_offset)

    def parser(self, message: str, indent_offset: int = 0) -> None:
        self._log("PRS", message, LogLevel.INFO, indent_offset)

    def linter(self, message: str, indent_offset: int = 0) -> None:
        self._log("LNT", message, LogLevel.INFO, indent_offset)

    def program(self, message: str, indent_offset: int = 0) -> None:
        self._log("PRG", message, LogLevel.INFO, indent_offset)

    def debug(self, message: str, indent_offset: int = 0) -> None:
        self._log("DBG", message, LogLevel.DEBUG, indent_offset)

    def connection(self) -> str:
        return "".join((
            "├",
            "─" * (self._indent_count * len(self._indent_string) - 1),
        ))

    def line(self) -> str:
        return "".join((
            "└",
            "─" * (self._indent_count * len(self._indent_string) - 1),
        ))

    def section(self, title: str, min_level: LogLevel = LogLevel.INFO) -> None:
        if self.log_level.value >= min_level.value:
            print(f"\n{'='*60}")
            print(f"{title.upper():^60}")
            print(f"{'='*60}\n")


class LintState:
    def __init__(self) -> None:
        self.vars = {}


def get_args() -> Namespace:
    parser = ArgumentParser(
        description="Пример программы с парсингом аргументов"
    )

    parser.add_argument(
        "--log-level",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help=(
            "Уровень логирования. "
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
    logger: Logger,
) -> Optional[str]:
    logger.section("Parsing Program")
    logger.parser(f"Reading file: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        try:
            Parse(f.read(), program)
            logger.parser("Program parsed successfully")
            return None
        except ParseError as pe:
            error_msg = f"Parse error: {pe}"
            logger.error(error_msg)
            return error_msg


def lint_using(
    using: Iterable[Using],
    state: LintState,
    logger: Logger,
) -> None:
    logger.linter("using")
    logger.indent()

    for el in using:
        shape: Optional[str] = None
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
            logger.debug("Name is not defined")
            continue

        if el.HasField("shape"):
            if shape is None:
                shape = el.shape
            else:
                logger.debug(f"Shape already defined: `{shape}`, found `{el.shape}`")
                continue
        elif shape is None:
            logger.debug(f"Shape is not defined for: `{el.name}`")
            continue

        msg += ": " + shape
        if el.HasField("cluster"):
            msg += f"[{el.cluster}]"

        logger.linter(msg)

    logger.dedent()
    logger.linter(logger.line())


def lint_set(
    set_cmd: Iterable[Set],
    state: LintState,
    logger: Logger,
) -> None:
    logger.linter("set")
    logger.indent()

    for line in set_cmd:
        msg = ""
        if line.HasField("eval"):
            msg = f"`{line.var}` eval `{line.eval}`"
        elif line.HasField("cast"):
            msg = f"`{line.var}` cast from `{line.cast}`"
        elif line.HasField("format"):
            msg = f"`{line.var}` format by `{line.format}`"
        elif line.HasField("i32"):
            state.vars[line.var] = int(line.i32)
            msg = f"{line.var}: i32 = {line.i32}"
        elif line.HasField("ui32"):
            state.vars[line.var] = int(line.ui32)
            msg = f"{line.var}: ui32 = {line.ui32}"
        elif line.HasField("char"):
            state.vars[line.var] = line.char
            msg = f"{line.var}: char = {line.char}"

        logger.linter(msg)

    logger.dedent()


def lint_if(
    _if: IfCondition,
    state: LintState,
    logger: Logger,
) -> None:
    msg = f"if `{_if.true}` "

    if _if.HasField("call"):
        logger.linter(msg + f"call {_if.call}")
    elif _if.HasField("ret"):
        logger.linter(msg + f"ret {_if.ret}")
    elif _if.HasField("alias"):
        logger.linter(msg + f"alias {_if.alias}")
    if len(_elif := getattr(_if, "elif")) > 0:
        lint_elif(_elif, state, logger)


def lint_while(
    _while: LoopCondition,
    state: LintState,
    logger: Logger,
) -> None:
    logger.linter(f"while {_while.true}")
    logger.indent()
    logger.linter(f"call {_while.call}")
    logger.dedent()


def lint_until(
    _until: LoopCondition,
    state: LintState,
    logger: Logger,
) -> None:
    logger.linter(f"until {_until.true}")
    logger.indent()
    logger.linter(f"call {_until.call}")
    logger.dedent()


def lint_elif(
    _elif: Iterable[Elif],
    state: LintState,
    logger: Logger,
) -> None:
    for line in _elif:
        msg = f"elif `{line.true}` "

        if line.HasField("call"):
            logger.linter(msg + f"call {line.call}")
        elif line.HasField("ret"):
            logger.linter(msg + f"ret {line.ret}")
        elif line.HasField("alias"):
            logger.linter(msg + f"alias {line.alias}")


def lint_else(
    _else: Else,
    state: LintState,
    logger: Logger,
) -> None:
    if _else.HasField("call"):
        logger.linter(f"else call {_else.call}")
    elif _else.HasField("ret"):
        logger.linter(f"else ret {_else.ret}")
    elif _else.HasField("alias"):
        logger.linter(f"else alias {_else.alias}")


def lint_do(
    do: Iterable[Do],
    state: LintState,
    logger: Logger,
) -> None:
    logger.linter("do")
    logger.indent()

    for i, el in enumerate(do):
        if el.HasField("commence"):
            logger.linter(f"commence `{el.commence}`")

        if len(el.set) > 0:
            lint_set(el.set, state, logger)

        if (_if := getattr(el, "if")).true != "":
            lint_if(_if, state, logger)
        elif (_while := getattr(el, "while")).true != "":
            lint_while(_while, state, logger)
        elif el.HasField("until"):
            lint_until(el.until, state, logger)
        elif el.HasField("call"):
            logger.linter(f"call: {el.call}")

        if (_else := getattr(el, "else")) is not None:
            lint_else(_else, state, logger)

        if el.HasField("conclude"):
            logger.linter(f"conclude `{el.conclude}`")

        if i == len(do) - 1:
            logger.linter(logger.line())
        else:
            logger.linter(logger.connection())

    logger.dedent()
    logger.linter(logger.line())


def lint_func_do(
    func_do: Iterable[FuncDo],
    state: LintState,
    logger: Logger,
) -> None:
    logger.indent()

    for i, el in enumerate(func_do):
        if el.HasField("commence"):
            logger.linter(f"commence `{el.commence}`")

        if len(el.set) > 0:
            lint_set(el.set, state, logger)

        if (_if := getattr(el, "if")).true != "":
            lint_if(_if, state, logger)
        elif (_while := getattr(el, "while")).true != "":
            lint_while(_while, state, logger)
        elif el.HasField("until"):
            lint_until(el.until, state, logger)
        elif el.HasField("call"):
            logger.linter(f"Call: {el.call}")

        if (_else := getattr(el, "else")) is not None:
            lint_else(_else, state, logger)

        if el.HasField("conclude"):
            logger.linter(f"conclude `{el.conclude}`")

        if i == len(func_do) - 1:
            logger.linter(logger.line())
        else:
            logger.linter(logger.connection())

    logger.dedent()


def lint_def(
    _def: Iterable[Def],
    state: LintState,
    logger: Logger,
) -> None:
    logger.linter("def")
    logger.indent()

    for i, el in enumerate(_def):
        if el.HasField("named"):
            logger.linter(f"named `{el.named}`")

        if el.HasField("calling"):
            logger.linter(f"calling `{el.calling}`")

        if el.HasField("receiving"):
            logger.linter(f"reveiving `{el.receiving}`")

        if len(func_do := el.do) > 0:
            lint_func_do(func_do, state, logger)

        if i == len(_def) - 1:
            logger.linter(logger.line())
        else:
            logger.linter(logger.connection())

    logger.dedent()
    logger.linter(logger.line())


def lint_program(
    p: Program,
    logger: Logger,
) -> Optional[str]:
    logger.section("Linting Program")
    state = LintState()

    try:
        if p.HasField("name"):
            logger.linter(f"name `{p.name}`")

        if p.HasField("version"):
            logger.linter(f"version `{p.version}`")

        if len(using := p.using) > 0:
            lint_using(using, state, logger)

        if len(_def := getattr(p, "def")) > 0:
            lint_def(_def, state, logger)

        if len(do := p.do) > 0:
            lint_do(do, state, logger)

        logger.linter("Linting completed successfully")
        return None

    except Exception as e:
        error_msg = f"Linting error: {e}"
        logger.error(error_msg)
        return error_msg


def process_program(p: Program, logger: Logger) -> Optional[str]:
    logger.section("Processing Program")
    logger.program("Program processing completed")
    return None


def main(args: Namespace) -> None:
    log_level = LogLevel(args.log_level)
    logger = Logger(log_level)

    logger.debug(f"Program filepath: `{args.filepath}`")

    program = Program()

    # Parse program with buffered output
    logger.start_buffering()
    result = parse_program(program, args.filepath, logger)
    logger.stop_buffering()

    if result is not None:
        logger.error(f"Program parsing failed: {result}")
        return

    # Lint program with buffered output
    logger.start_buffering()
    result = lint_program(program, logger)
    logger.stop_buffering()

    if result is not None:
        logger.error(f"Program linting failed: {result}")
        return

    # Process program with buffered output
    logger.start_buffering()
    result = process_program(program, logger)
    logger.stop_buffering()

    if result is not None:
        logger.error(f"Program processing failed: {result}")
        return

    logger.program("Program execution completed successfully")


if __name__ == "__main__":
    main(get_args())
