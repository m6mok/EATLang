"""Типизированный дамп AST — эталон для self-hosted фазы 3b
(selfhost/Check.eat, `eatc typed`).

Дамп `eatc parse` + аннотации тайпчекера:

- каждое типизированное выражение — суффикс ` :: {тип}`;
- let — тип переменной, for — тип элемента (и `bounds=a..b` у
  диапазона), arm — тип нагрузки варианта;
- футер: `stack {глубина}` и рёбра графа вызовов
  `edge {вызывающий} -> {вызываемый}` (сортированы).
"""

from . import ast_nodes as ast
from .astdump import Dumper
from .checks import check_program
from .typechecker import typecheck
from .types import show


class TypedDumper(Dumper):
    def expr(self, d: int, node) -> None:
        i = len(self.lines)
        super().expr(d, node)
        if hasattr(node, "ty"):
            self.lines[i] += f" :: {show(node.ty)}"

    def ann(self, node) -> str:
        if isinstance(node, ast.LetStmt):
            return f" :: {show(node.var_ty)}"
        if isinstance(node, ast.ForStmt):
            text = f" :: {show(node.elem_ty)}"
            if node.bounds is not None:
                text += f" bounds={node.bounds[0]}..{node.bounds[1]}"
            return text
        if isinstance(node, ast.MatchArm):
            if node.payload_ty is not None:
                return f" :: {show(node.payload_ty)}"
        return ""


def dump_typed(program: ast.Program, filename: str) -> list[str]:
    check_program(program, filename)
    result = typecheck(program, filename)
    lines = TypedDumper().program(program)
    lines.append(f"stack {result.stack_depth}")
    for caller, callee in sorted(result.edges):
        lines.append(f"edge {caller} -> {callee}")
    return lines
