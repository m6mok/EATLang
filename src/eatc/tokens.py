"""Токены EATLang."""

from dataclasses import dataclass
from enum import Enum, auto


class T(Enum):
    # литералы и имена
    INT = auto()
    STRING = auto()
    CHAR = auto()
    IDENT = auto()

    # ключевые слова
    FUNC = auto()
    LET = auto()
    VAR = auto()
    CONST = auto()
    STRUCT = auto()
    ENUM = auto()
    TEST = auto()
    IF = auto()
    ELIF = auto()
    ELSE = auto()
    FOR = auto()
    IN = auto()
    LOOP = auto()
    MATCH = auto()
    RETURN = auto()
    BREAK = auto()
    ASSERT = auto()
    REQUIRES = auto()
    ENSURES = auto()
    DISCARD = auto()
    SELF = auto()
    TRUE = auto()
    FALSE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()

    # пунктуация и операторы
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    LT = auto()
    GT = auto()
    LE = auto()
    GE = auto()
    EQ = auto()
    NE = auto()
    ASSIGN = auto()
    COMMA = auto()
    COLON = auto()
    SEMI = auto()
    DOT = auto()
    DOTDOT = auto()
    ARROW = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    AMP = auto()
    PIPE = auto()
    CARET = auto()
    SHL = auto()
    SHR = auto()
    TILDE = auto()

    NEWLINE = auto()
    EOF = auto()


KEYWORDS = {
    "func": T.FUNC,
    "let": T.LET,
    "var": T.VAR,
    "const": T.CONST,
    "struct": T.STRUCT,
    "enum": T.ENUM,
    "test": T.TEST,
    "if": T.IF,
    "elif": T.ELIF,
    "else": T.ELSE,
    "for": T.FOR,
    "in": T.IN,
    "loop": T.LOOP,
    "match": T.MATCH,
    "return": T.RETURN,
    "break": T.BREAK,
    "assert": T.ASSERT,
    "requires": T.REQUIRES,
    "ensures": T.ENSURES,
    "discard": T.DISCARD,
    "self": T.SELF,
    "true": T.TRUE,
    "false": T.FALSE,
    "and": T.AND,
    "or": T.OR,
    "not": T.NOT,
}


@dataclass(frozen=True)
class Token:
    type: T
    value: str
    line: int
    col: int
