"""Канонический дамп AST — эталон для self-hosted парсера (selfhost/).

Формат: préorder, одна строка на узел, отступ 2 пробела на уровень:

    {kind} [{line}:{col}] [name=X|val=X|op=X] [доп. поля]

Узлы без собственной позиции в AST (кортежи Python: варианты enum,
elif-ветки, поля struct-литералов, сегменты строк, обёртки
ret/requires/ensures/else) печатаются без {line}:{col}.
Значения (val=) экранируются как в дампе токенов `eatc lex`.
"""

from . import ast_nodes as ast


def _esc(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\0", "\\0")
    )


class Dumper:
    def __init__(self):
        self.lines: list[str] = []

    def emit(self, depth: int, text: str) -> None:
        self.lines.append("  " * depth + text)

    def ann(self, node) -> str:
        """Хук аннотаций (типизированный дамп переопределяет)."""
        return ""

    # --- программа и объявления ------------------------------------------

    def program(self, node: ast.Program) -> list[str]:
        self.emit(0, f"program {node.line}:{node.col}")
        for decl in node.decls:
            self.decl(1, decl)
        return self.lines

    def decl(self, d: int, node) -> None:
        if isinstance(node, ast.FuncDecl):
            self.func(d, node)
        elif isinstance(node, ast.StructDecl):
            self.emit(d, f"struct {node.line}:{node.col} name={node.name}")
            for f in node.fields:
                self.emit(d + 1, f"field {f.line}:{f.col} name={f.name}")
                self.type_(d + 2, f.type)
            for m in node.methods:
                self.func(d + 1, m)
        elif isinstance(node, ast.EnumDecl):
            self.emit(d, f"enum {node.line}:{node.col} name={node.name}")
            for vname, payload in node.variants:
                self.emit(d + 1, f"variant name={vname}")
                if payload is not None:
                    self.type_(d + 2, payload)
        elif isinstance(node, ast.ConstDecl):
            self.emit(d, f"const {node.line}:{node.col} name={node.name}")
            self.type_(d + 1, node.type)
            self.expr(d + 1, node.value)
        elif isinstance(node, ast.TestBlock):
            self.emit(d, f"test {node.line}:{node.col} name={node.name}")
            self.block(d + 1, node.body)
        else:
            raise AssertionError(f"неизвестное объявление: {node}")

    def func(self, d: int, node: ast.FuncDecl) -> None:
        method = 1 if node.is_method else 0
        self.emit(
            d,
            f"func {node.line}:{node.col} name={node.name} method={method}",
        )
        for p in node.params:
            mut = 1 if p.mutable else 0
            self.emit(d + 1, f"param {p.line}:{p.col} name={p.name} mut={mut}")
            if p.type is not None:
                self.type_(d + 2, p.type)
        if node.ret is not None:
            self.emit(d + 1, "ret")
            self.type_(d + 2, node.ret)
        if node.requires is not None:
            self.emit(d + 1, "requires")
            self.expr(d + 2, node.requires)
        if node.ensures is not None:
            self.emit(d + 1, "ensures")
            self.expr(d + 2, node.ensures)
        self.block(d + 1, node.body)

    # --- типы --------------------------------------------------------------

    def type_(self, d: int, node) -> None:
        if isinstance(node, ast.TypeName):
            self.emit(d, f"typename {node.line}:{node.col} name={node.name}")
        elif isinstance(node, ast.ArrayType):
            self.emit(d, f"arraytype {node.line}:{node.col}")
            self.type_(d + 1, node.elem)
            self.expr(d + 1, node.size)
        elif isinstance(node, ast.StrType):
            self.emit(d, f"strtype {node.line}:{node.col}")
            self.expr(d + 1, node.capacity)
        elif isinstance(node, ast.ResultType):
            self.emit(d, f"resulttype {node.line}:{node.col}")
            self.type_(d + 1, node.ok)
            self.type_(d + 1, node.err)
        elif isinstance(node, ast.OptionType):
            self.emit(d, f"optiontype {node.line}:{node.col}")
            self.type_(d + 1, node.inner)
        else:
            raise AssertionError(f"неизвестный тип: {node}")

    # --- блоки и инструкции --------------------------------------------

    def block(self, d: int, node: ast.Block) -> None:
        self.emit(d, f"block {node.line}:{node.col}")
        for stmt in node.stmts:
            self.stmt(d + 1, stmt)

    def stmt(self, d: int, node) -> None:
        pos = f"{node.line}:{node.col}"
        if isinstance(node, ast.LetStmt):
            mut = 1 if node.mutable else 0
            self.emit(d, f"let {pos} name={node.name} mut={mut}{self.ann(node)}")
            self.type_(d + 1, node.type)
            self.expr(d + 1, node.value)
        elif isinstance(node, ast.AssignStmt):
            self.emit(d, f"assign {pos}")
            self.expr(d + 1, node.target)
            self.expr(d + 1, node.value)
        elif isinstance(node, ast.IfStmt):
            self.emit(d, f"if {pos}")
            self.expr(d + 1, node.cond)
            self.block(d + 1, node.then)
            for cond, blk in node.elifs:
                self.emit(d + 1, "elif")
                self.expr(d + 2, cond)
                self.block(d + 2, blk)
            if node.els is not None:
                self.emit(d + 1, "else")
                self.block(d + 2, node.els)
        elif isinstance(node, ast.ForStmt):
            self.emit(d, f"for {pos} name={node.target}{self.ann(node)}")
            self.expr(d + 1, node.iterable)
            self.block(d + 1, node.body)
        elif isinstance(node, ast.LoopStmt):
            self.emit(d, f"loop {pos}")
            self.block(d + 1, node.body)
        elif isinstance(node, ast.MatchStmt):
            self.emit(d, f"match {pos}")
            self.expr(d + 1, node.subject)
            for arm in node.arms:
                bind = "" if arm.binding is None else f" bind={arm.binding}"
                self.emit(
                    d + 1,
                    f"arm {arm.line}:{arm.col} name={arm.pattern}{bind}"
                    + self.ann(arm),
                )
                self.block(d + 2, arm.body)
        elif isinstance(node, ast.ReturnStmt):
            self.emit(d, f"return {pos}")
            if node.value is not None:
                self.expr(d + 1, node.value)
        elif isinstance(node, ast.BreakStmt):
            self.emit(d, f"break {pos}")
        elif isinstance(node, ast.AssertStmt):
            self.emit(d, f"assert {pos}")
            self.expr(d + 1, node.cond)
        elif isinstance(node, ast.ExprStmt):
            self.emit(d, f"exprstmt {pos}")
            self.expr(d + 1, node.expr)
        elif isinstance(node, ast.DiscardStmt):
            self.emit(d, f"discard {pos}")
            self.expr(d + 1, node.expr)
        else:
            raise AssertionError(f"неизвестная инструкция: {node}")

    # --- выражения ----------------------------------------------------

    def expr(self, d: int, node) -> None:
        pos = f"{node.line}:{node.col}"
        if isinstance(node, ast.IntLit):
            self.emit(d, f"int {pos} val={node.value}")
        elif isinstance(node, ast.BoolLit):
            val = "true" if node.value else "false"
            self.emit(d, f"bool {pos} val={val}")
        elif isinstance(node, ast.CharLit):
            self.emit(d, f"char {pos} val={_esc(node.value)}")
        elif isinstance(node, ast.StrLit):
            self.emit(d, f"str {pos}")
            for seg in node.segments:
                if isinstance(seg, str):
                    self.emit(d + 1, f"seg val={_esc(seg)}")
                else:
                    self.expr(d + 1, seg)
        elif isinstance(node, ast.Name):
            self.emit(d, f"name {pos} val={node.ident}")
        elif isinstance(node, ast.SelfExpr):
            self.emit(d, f"self {pos}")
        elif isinstance(node, ast.BinOp):
            self.emit(d, f"binop {pos} op={node.op}")
            self.expr(d + 1, node.left)
            self.expr(d + 1, node.right)
        elif isinstance(node, ast.UnaryOp):
            self.emit(d, f"unary {pos} op={node.op}")
            self.expr(d + 1, node.operand)
        elif isinstance(node, ast.Call):
            self.emit(d, f"call {pos} name={node.name}")
            for a in node.args:
                self.expr(d + 1, a)
        elif isinstance(node, ast.MethodCall):
            self.emit(d, f"method {pos} name={node.name}")
            self.expr(d + 1, node.obj)
            for a in node.args:
                self.expr(d + 1, a)
        elif isinstance(node, ast.FieldAccess):
            self.emit(d, f"member {pos} name={node.name}")
            self.expr(d + 1, node.obj)
        elif isinstance(node, ast.Index):
            self.emit(d, f"index {pos}")
            self.expr(d + 1, node.obj)
            self.expr(d + 1, node.index)
        elif isinstance(node, ast.StructLit):
            self.emit(d, f"structlit {pos} name={node.name}")
            for fname, fexpr in node.fields:
                self.emit(d + 1, f"fld name={fname}")
                self.expr(d + 2, fexpr)
        elif isinstance(node, ast.ArrayLit):
            self.emit(d, f"arraylit {pos}")
            for e in node.elems:
                self.expr(d + 1, e)
        elif isinstance(node, ast.ArrayFill):
            self.emit(d, f"arrayfill {pos}")
            self.expr(d + 1, node.value)
            self.expr(d + 1, node.count)
        elif isinstance(node, ast.RangeExpr):
            self.emit(d, f"range {pos}")
            self.expr(d + 1, node.start)
            self.expr(d + 1, node.end)
        else:
            raise AssertionError(f"неизвестное выражение: {node}")


def dump_program(program: ast.Program) -> list[str]:
    return Dumper().program(program)
