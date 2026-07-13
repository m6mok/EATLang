"""Узлы AST EATLang (SPEC.md §4)."""

from dataclasses import dataclass, field

# Счётчик созданных узлов — парсер сверяет дельту с MAX_AST_NODES
# (SPEC §6): та же alloc-семантика, что у пула self-hosted парсера.
_alloc_count = 0


def alloc_count() -> int:
    return _alloc_count


@dataclass
class Node:
    line: int
    col: int

    def __post_init__(self) -> None:
        global _alloc_count
        _alloc_count += 1


# --- типы ---------------------------------------------------------------


@dataclass
class TypeName(Node):
    name: str  # i32, u32, u8, bool, char, имя struct/enum


@dataclass
class ArrayType(Node):
    elem: Node
    size: "Expr"


@dataclass
class StrType(Node):
    capacity: "Expr"


@dataclass
class ResultType(Node):
    ok: Node
    err: Node


@dataclass
class OptionType(Node):
    inner: Node


# --- выражения ----------------------------------------------------------


@dataclass
class Expr(Node):
    pass


@dataclass
class IntLit(Expr):
    value: int


@dataclass
class BoolLit(Expr):
    value: bool


@dataclass
class CharLit(Expr):
    value: str


@dataclass
class StrLit(Expr):
    # сегменты интерполяции: str — литеральный текст, Expr — {выражение}
    segments: list


@dataclass
class Name(Expr):
    ident: str


@dataclass
class SelfExpr(Expr):
    pass


@dataclass
class BinOp(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class UnaryOp(Expr):
    op: str  # "-" | "not" | "~"
    operand: Expr


@dataclass
class Call(Expr):
    name: str
    args: list


@dataclass
class MethodCall(Expr):
    obj: Expr
    name: str
    args: list


@dataclass
class FieldAccess(Expr):
    obj: Expr
    name: str  # поле struct или вариант enum (различает тайпчекер)


@dataclass
class Index(Expr):
    obj: Expr
    index: Expr


@dataclass
class StructLit(Expr):
    name: str
    fields: list  # [(имя, Expr)]


@dataclass
class ArrayLit(Expr):
    elems: list


@dataclass
class ArrayFill(Expr):
    value: Expr  # [значение; N] — N элементов-копий
    count: Node  # константное выражение


@dataclass
class RangeExpr(Expr):
    start: Expr
    end: Expr  # полуинтервал [start, end)


# --- инструкции ---------------------------------------------------------


@dataclass
class Stmt(Node):
    pass


@dataclass
class Block(Node):
    stmts: list


@dataclass
class LetStmt(Stmt):
    name: str
    type: Node
    value: Expr
    mutable: bool  # let → False, var → True


@dataclass
class AssignStmt(Stmt):
    target: Expr  # Name | FieldAccess | Index
    value: Expr


@dataclass
class IfStmt(Stmt):
    cond: Expr
    then: Block
    elifs: list  # [(Expr, Block)]
    els: Block | None


@dataclass
class ForStmt(Stmt):
    target: str  # имя или "_"
    iterable: Expr  # RangeExpr | выражение-массив
    body: Block


@dataclass
class LoopStmt(Stmt):
    body: Block


@dataclass
class MatchArm(Node):
    pattern: str  # Ok, Err, None, вариант enum
    binding: str | None  # имя или "_" внутри скобок
    body: Block


@dataclass
class MatchStmt(Stmt):
    subject: Expr
    arms: list


@dataclass
class ReturnStmt(Stmt):
    value: Expr | None


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class AssertStmt(Stmt):
    cond: Expr


@dataclass
class ExprStmt(Stmt):
    expr: Expr  # только вызов без результата (проверяет тайпчекер)


@dataclass
class DiscardStmt(Stmt):
    expr: Expr


# --- объявления верхнего уровня ------------------------------------------


@dataclass
class Param(Node):
    name: str  # "self" у методов
    type: Node | None  # None только у self
    mutable: bool = False  # var self — мутирующий метод


@dataclass
class FuncDecl(Node):
    name: str
    params: list
    ret: Node | None
    requires: Expr | None
    ensures: Expr | None
    body: Block
    is_method: bool = False


@dataclass
class FieldDecl(Node):
    name: str
    type: Node


@dataclass
class StructDecl(Node):
    name: str
    fields: list
    methods: list


@dataclass
class EnumDecl(Node):
    name: str
    variants: list  # [(имя, узел типа нагрузки | None)]


@dataclass
class ConstDecl(Node):
    name: str
    type: Node
    value: Expr


@dataclass
class TestBlock(Node):
    name: str
    body: Block


@dataclass
class Program(Node):
    decls: list = field(default_factory=list)
