"""Лексер EATLang.

Конец строки — конец инструкции, поэтому NEWLINE — значимый токен.
Внутри ( ) и [ ] переводы строк подавляются. Подряд идущие NEWLINE
схлопываются в один.
"""

from .errors import CapacityError, EatError
from .limits import MAX_TOKENS_PER_FILE
from .tokens import KEYWORDS, T, Token

_TWO_CHAR = {
    "->": T.ARROW,
    "..": T.DOTDOT,
    "==": T.EQ,
    "!=": T.NE,
    "<=": T.LE,
    ">=": T.GE,
}

_ONE_CHAR = {
    "(": T.LPAREN,
    ")": T.RPAREN,
    "{": T.LBRACE,
    "}": T.RBRACE,
    "[": T.LBRACKET,
    "]": T.RBRACKET,
    "<": T.LT,
    ">": T.GT,
    "=": T.ASSIGN,
    ",": T.COMMA,
    ":": T.COLON,
    ";": T.SEMI,
    ".": T.DOT,
    "+": T.PLUS,
    "-": T.MINUS,
    "*": T.STAR,
    "/": T.SLASH,
    "%": T.PERCENT,
}

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'", "0": "\0"}


class Lexer:
    def __init__(
        self, source: str, filename: str, line: int = 1, col: int = 1
    ):
        self.src = source
        self.filename = filename
        self.pos = 0
        self.line = line
        self.col = col
        self.depth = 0  # вложенность ( ) и [ ]
        self.tokens: list[Token] = []

    def error(self, message: str) -> EatError:
        return EatError(self.filename, self.line, self.col, message)

    def _peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.src[i] if i < len(self.src) else ""

    def _advance(self) -> str:
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _emit(self, type_: T, value: str, line: int, col: int) -> None:
        if len(self.tokens) >= MAX_TOKENS_PER_FILE:
            raise CapacityError(
                self.filename,
                line,
                col,
                "токенов в файле",
                MAX_TOKENS_PER_FILE,
            )
        self.tokens.append(Token(type_, value, line, col))

    def _emit_newline(self, line: int, col: int) -> None:
        if self.depth > 0:
            return
        if self.tokens and self.tokens[-1].type != T.NEWLINE:
            self._emit(T.NEWLINE, "\\n", line, col)

    def tokenize(self) -> list[Token]:
        while self.pos < len(self.src):
            ch = self._peek()
            line, col = self.line, self.col

            if ch == "\n":
                self._advance()
                self._emit_newline(line, col)
                continue
            if ch in " \t\r":
                self._advance()
                continue
            if ch == "#":
                while self.pos < len(self.src) and self._peek() != "\n":
                    self._advance()
                continue
            if ch == '"':
                self._lex_string(line, col)
                continue
            if ch == "'":
                self._lex_char(line, col)
                continue
            if ch.isdigit():
                self._lex_int(line, col)
                continue
            if ch.isalpha() or ch == "_":
                self._lex_word(line, col)
                continue

            two = self._peek() + self._peek(1)
            if two in _TWO_CHAR:
                self._advance()
                self._advance()
                self._emit(_TWO_CHAR[two], two, line, col)
                continue
            if ch in _ONE_CHAR:
                self._advance()
                if ch in "([":
                    self.depth += 1
                elif ch in ")]":
                    self.depth = max(0, self.depth - 1)
                self._emit(_ONE_CHAR[ch], ch, line, col)
                continue

            raise self.error(f"неожиданный символ {ch!r}")

        self._emit_newline(self.line, self.col)
        self._emit(T.EOF, "", self.line, self.col)
        return self.tokens

    def _lex_string(self, line: int, col: int) -> None:
        self._advance()  # открывающая кавычка
        chars: list[str] = []
        while True:
            if self.pos >= len(self.src) or self._peek() == "\n":
                raise self.error("незакрытая строка")
            ch = self._advance()
            if ch == '"':
                break
            if ch == "\\":
                esc = self._advance() if self.pos < len(self.src) else ""
                if esc not in _ESCAPES:
                    raise self.error(
                        f"неизвестная escape-последовательность \\{esc}"
                    )
                chars.append(_ESCAPES[esc])
            else:
                chars.append(ch)
        self._emit(T.STRING, "".join(chars), line, col)

    def _lex_char(self, line: int, col: int) -> None:
        self._advance()  # открывающий апостроф
        if self.pos >= len(self.src):
            raise self.error("незакрытый символьный литерал")
        ch = self._advance()
        if ch == "\\":
            esc = self._advance() if self.pos < len(self.src) else ""
            if esc not in _ESCAPES:
                raise self.error(
                    f"неизвестная escape-последовательность \\{esc}"
                )
            ch = _ESCAPES[esc]
        if self.pos >= len(self.src) or self._advance() != "'":
            raise self.error("ожидался закрывающий апостроф")
        if len(ch.encode("utf-8")) != 1:
            raise self.error(
                f"символ {ch!r} не помещается в один байт (char — байт)"
            )
        self._emit(T.CHAR, ch, line, col)

    def _lex_int(self, line: int, col: int) -> None:
        digits: list[str] = []
        while self.pos < len(self.src) and self._peek().isdigit():
            digits.append(self._advance())
        if self._peek().isalpha() or self._peek() == "_":
            raise self.error("идентификатор не может начинаться с цифры")
        self._emit(T.INT, "".join(digits), line, col)

    def _lex_word(self, line: int, col: int) -> None:
        chars: list[str] = []
        while self.pos < len(self.src) and (
            self._peek().isalnum() or self._peek() == "_"
        ):
            chars.append(self._advance())
        word = "".join(chars)
        self._emit(KEYWORDS.get(word, T.IDENT), word, line, col)
