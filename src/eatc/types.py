"""Представление типов EATLang (SPEC.md §3)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Type:
    pass


@dataclass(frozen=True)
class IntType(Type):
    kind: str  # "i32" | "u32" | "u16" | "u8" | "u64" | "i64"


@dataclass(frozen=True)
class BoolType(Type):
    pass


@dataclass(frozen=True)
class CharType(Type):
    pass


@dataclass(frozen=True)
class StrType(Type):
    # None — ёмкость статически неизвестна (интерполированный литерал);
    # проверка ёмкости в 0.0.1 откладывается до рантайма (trap)
    capacity: int | None


@dataclass(frozen=True)
class ArrayType(Type):
    elem: Type
    size: int


@dataclass(frozen=True)
class StructType(Type):
    name: str


@dataclass(frozen=True)
class EnumType(Type):
    name: str


@dataclass(frozen=True)
class ResultType(Type):
    ok: Type
    err: Type


@dataclass(frozen=True)
class OptionType(Type):
    inner: Type


@dataclass(frozen=True)
class VoidType(Type):
    pass


I32 = IntType("i32")
U32 = IntType("u32")
U16 = IntType("u16")
U8 = IntType("u8")
U64 = IntType("u64")
I64 = IntType("i64")
BOOL = BoolType()
CHAR = CharType()
VOID = VoidType()

INT_RANGES = {
    "i32": (-(2**31), 2**31 - 1),
    "u32": (0, 2**32 - 1),
    "u16": (0, 65535),
    "u8": (0, 255),
    "u64": (0, 2**64 - 1),
    "i64": (-(2**63), 2**63 - 1),
}


def compatible(expected: Type, actual: Type) -> bool:
    """Совместимость типов. Неявных преобразований нет; единственное
    послабление 0.0.1 — ёмкость строк сверяется в рантайме."""
    if isinstance(expected, StrType) and isinstance(actual, StrType):
        return True
    return expected == actual


def show(t: Type) -> str:
    if isinstance(t, IntType):
        return t.kind
    if isinstance(t, BoolType):
        return "bool"
    if isinstance(t, CharType):
        return "char"
    if isinstance(t, StrType):
        return f"str<{t.capacity}>" if t.capacity is not None else "str<?>"
    if isinstance(t, ArrayType):
        return f"[{show(t.elem)}; {t.size}]"
    if isinstance(t, StructType):
        return t.name
    if isinstance(t, EnumType):
        return t.name
    if isinstance(t, ResultType):
        return f"Result<{show(t.ok)}, {show(t.err)}>"
    if isinstance(t, OptionType):
        return f"Option<{show(t.inner)}>"
    if isinstance(t, VoidType):
        return "void"
    return "?"
