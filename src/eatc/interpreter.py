"""Интерпретатор EATLang — эталон семантики до LLVM-кодогенерации.

Исполняет типизированный AST. Нарушение контракта, переполнение,
деление на ноль, выход за границы — trap (аварийная остановка с
координатами). Семантика передачи — by-value: копия на каждой точке
связывания (аргумент, let, присваивание, return).
"""

import sys
from copy import deepcopy
from dataclasses import dataclass

from . import ast_nodes as ast
from .errors import EatError
from .types import INT_RANGES


class Trap(EatError):
    def __init__(self, filename, line, col, message):
        super().__init__(filename, line, col, f"trap: {message}")


class ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


class BreakSignal(Exception):
    pass


@dataclass
class Slot:
    value: object
    kind: str | None = None  # "i32" | "u32" | "u8" для проверки диапазона
    cap: int | None = None  # ёмкость str<N>


@dataclass(frozen=True)
class EnumValue:
    enum: str
    variant: str
    payload: object = None


@dataclass(frozen=True)
class Tagged:  # Ok/Err/Some/None
    tag: str
    payload: object


@dataclass
class StructValue:
    name: str
    fields: dict


@dataclass
class StructRT:
    fields: dict  # имя -> (kind, cap)
    methods: dict  # имя -> ast.FuncDecl


class Interpreter:
    def __init__(self, program: ast.Program, filename: str):
        self.program = program
        self.filename = filename
        self.consts: dict[str, Slot] = {}
        self.funcs: dict[str, ast.FuncDecl] = {}
        self.structs: dict[str, StructRT] = {}
        self.enums: dict[str, list] = {
            "IoError": ["Eof", "Fail"],
            "ParseError": ["Empty", "BadChar", "Overflow"],
        }
        self.frames: list[list[dict]] = []
        self._collect()

    # --- подготовка -----------------------------------------------------

    def _collect(self) -> None:
        for decl in self.program.decls:
            if isinstance(decl, ast.EnumDecl):
                self.enums[decl.name] = [v for v, _ in decl.variants]
            elif isinstance(decl, ast.StructDecl):
                fields = {
                    f.name: (self._kind(f.type), self._cap(f.type))
                    for f in decl.fields
                }
                methods = {m.name: m for m in decl.methods}
                self.structs[decl.name] = StructRT(fields, methods)
            elif isinstance(decl, ast.FuncDecl):
                self.funcs[decl.name] = decl
        for decl in self.program.decls:
            if isinstance(decl, ast.ConstDecl):
                value = self._const_eval(decl.value)
                kind = self._kind(decl.type)
                self._fit(decl, kind, value)
                self.consts[decl.name] = Slot(value, kind)

    def _kind(self, tnode) -> str | None:
        if isinstance(tnode, ast.TypeName) and tnode.name in INT_RANGES:
            return tnode.name
        return None

    def _cap(self, tnode) -> int | None:
        if isinstance(tnode, ast.StrType):
            return self._const_eval(tnode.capacity)
        return None

    def _const_eval(self, expr: ast.Expr) -> int:
        if isinstance(expr, ast.IntLit):
            return expr.value
        if isinstance(expr, ast.Name):
            return self.consts[expr.ident].value
        if isinstance(expr, ast.UnaryOp):
            return -self._const_eval(expr.operand)
        if isinstance(expr, ast.BinOp):
            left = self._const_eval(expr.left)
            right = self._const_eval(expr.right)
            return {
                "+": lambda: left + right,
                "-": lambda: left - right,
                "*": lambda: left * right,
                "/": lambda: self._trunc_div(expr, left, right),
                "%": lambda: self._trunc_mod(expr, left, right),
            }[expr.op]()
        raise self.trap(expr, "не константа")

    # --- ошибки и хранение ---------------------------------------------

    def trap(self, node: ast.Node, message: str) -> Trap:
        return Trap(self.filename, node.line, node.col, message)

    def _fit(self, node, kind: str | None, value) -> None:
        if kind is None:
            return
        lo, hi = INT_RANGES[kind]
        if not lo <= value <= hi:
            raise self.trap(
                node, f"переполнение: {value} вне {kind} [{lo}, {hi}]"
            )

    def _fit_cap(self, node, cap: int | None, value) -> None:
        if cap is None or not isinstance(value, str):
            return
        if len(value.encode("utf-8")) > cap:
            raise self.trap(node, f"строка длиннее ёмкости str<{cap}>")

    def push_scope(self) -> None:
        self.frames[-1].append({})

    def pop_scope(self) -> None:
        self.frames[-1].pop()

    def declare(self, name: str, slot: Slot) -> None:
        if name != "_":
            self.frames[-1][-1][name] = slot

    def slot(self, node: ast.Node, name: str) -> Slot:
        for scope in reversed(self.frames[-1]):
            if name in scope:
                return scope[name]
        if name in self.consts:
            return self.consts[name]
        raise self.trap(node, f"нет переменной {name}")

    # --- запуск -----------------------------------------------------------

    def run_main(self) -> None:
        self.call_func(self.funcs["main"], [], None, self.funcs["main"])

    def run_tests(self) -> list[str]:
        passed = []
        for decl in self.program.decls:
            if not isinstance(decl, ast.TestBlock):
                continue
            self.frames.append([{}])
            try:
                self.exec_block(decl.body)
            except EatError as err:
                raise EatError(
                    self.filename,
                    decl.line,
                    decl.col,
                    f"test {decl.name} провален: {err.message}",
                ) from err
            finally:
                self.frames.pop()
            passed.append(decl.name)
        return passed

    # --- вызов функции -------------------------------------------------------

    def call_func(
        self,
        func: ast.FuncDecl,
        args: list,
        self_value,
        site: ast.Node,
    ):
        self.frames.append([{}])
        if self_value is not None:
            self.declare("self", Slot(self_value))
        arg_i = 0
        for param in func.params:
            if param.name == "self":
                continue
            value = deepcopy(args[arg_i])
            arg_i += 1
            kind = self._kind(param.type)
            cap = self._cap(param.type)
            self._fit(site, kind, value)
            self._fit_cap(site, cap, value)
            self.declare(param.name, Slot(value, kind, cap))
        if func.requires is not None:
            if not self.eval(func.requires):
                raise self.trap(site, f"нарушен requires функции {func.name}")
        result = None
        try:
            self.exec_block(func.body)
        except ReturnSignal as ret:
            result = deepcopy(ret.value)
        if func.ensures is not None:
            self.declare("result", Slot(result))
            if not self.eval(func.ensures):
                raise self.trap(site, f"нарушен ensures функции {func.name}")
        self.frames.pop()
        return result

    # --- инструкции --------------------------------------------------------

    def exec_block(self, block: ast.Block) -> None:
        self.push_scope()
        try:
            for stmt in block.stmts:
                self.exec_stmt(stmt)
        finally:
            self.pop_scope()

    def exec_stmt(self, stmt: ast.Stmt) -> None:
        if isinstance(stmt, ast.LetStmt):
            value = deepcopy(self.eval(stmt.value))
            kind = self._kind(stmt.type)
            cap = self._cap(stmt.type)
            self._fit(stmt, kind, value)
            self._fit_cap(stmt, cap, value)
            self.declare(stmt.name, Slot(value, kind, cap))
            return
        if isinstance(stmt, ast.AssignStmt):
            self.exec_assign(stmt)
            return
        if isinstance(stmt, ast.IfStmt):
            if self.eval(stmt.cond):
                self.exec_block(stmt.then)
                return
            for cond, blk in stmt.elifs:
                if self.eval(cond):
                    self.exec_block(blk)
                    return
            if stmt.els is not None:
                self.exec_block(stmt.els)
            return
        if isinstance(stmt, ast.ForStmt):
            self.exec_for(stmt)
            return
        if isinstance(stmt, ast.LoopStmt):
            try:
                while True:
                    self.exec_block(stmt.body)
            except BreakSignal:
                return
        if isinstance(stmt, ast.MatchStmt):
            self.exec_match(stmt)
            return
        if isinstance(stmt, ast.ReturnStmt):
            value = self.eval(stmt.value) if stmt.value is not None else None
            raise ReturnSignal(value)
        if isinstance(stmt, ast.BreakStmt):
            raise BreakSignal()
        if isinstance(stmt, ast.AssertStmt):
            if not self.eval(stmt.cond):
                raise self.trap(stmt, "assert не выполнен")
            return
        if isinstance(stmt, (ast.ExprStmt, ast.DiscardStmt)):
            self.eval(stmt.expr)
            return
        raise self.trap(stmt, "неизвестная инструкция")

    def exec_assign(self, stmt: ast.AssignStmt) -> None:
        value = deepcopy(self.eval(stmt.value))
        target = stmt.target
        if isinstance(target, ast.Name):
            slot = self.slot(target, target.ident)
            self._fit(stmt, slot.kind, value)
            self._fit_cap(stmt, slot.cap, value)
            slot.value = value
            return
        if isinstance(target, ast.FieldAccess):
            obj = self.eval(target.obj)
            assert isinstance(obj, StructValue)
            kind, cap = self.structs[obj.name].fields[target.name]
            self._fit(stmt, kind, value)
            self._fit_cap(stmt, cap, value)
            obj.fields[target.name] = value
            return
        if isinstance(target, ast.Index):
            obj = self.eval(target.obj)
            index = self.eval(target.index)
            self._check_bounds(target, obj, index)
            obj[index] = value
            return
        raise self.trap(stmt, "некорректная цель присваивания")

    def exec_for(self, stmt: ast.ForStmt) -> None:
        if isinstance(stmt.iterable, ast.RangeExpr):
            start = self._const_eval(stmt.iterable.start)
            end = self._const_eval(stmt.iterable.end)
            items = range(start, end)
        else:
            items = self.eval(stmt.iterable)
        for item in items:
            self.push_scope()
            self.declare(stmt.target, Slot(deepcopy(item)))
            try:
                self.exec_block(stmt.body)
            finally:
                self.pop_scope()

    def exec_match(self, stmt: ast.MatchStmt) -> None:
        subject = self.eval(stmt.subject)
        if isinstance(subject, Tagged):
            tag, payload = subject.tag, subject.payload
        else:
            assert isinstance(subject, EnumValue)
            tag, payload = subject.variant, subject.payload
        for arm in stmt.arms:
            if arm.pattern != tag:
                continue
            self.push_scope()
            if arm.binding is not None:
                self.declare(arm.binding, Slot(deepcopy(payload)))
            try:
                self.exec_block(arm.body)
            finally:
                self.pop_scope()
            return
        raise self.trap(stmt, f"нет ветки match для {tag}")

    # --- выражения -----------------------------------------------------------

    def eval(self, node: ast.Expr):
        if isinstance(node, ast.IntLit):
            return node.value
        if isinstance(node, ast.BoolLit):
            return node.value
        if isinstance(node, ast.CharLit):
            return node.value
        if isinstance(node, ast.StrLit):
            return self._eval_str(node)
        if isinstance(node, ast.SelfExpr):
            return self.slot(node, "self").value
        if isinstance(node, ast.Name):
            return self.slot(node, node.ident).value
        if isinstance(node, ast.UnaryOp):
            return self._eval_unary(node)
        if isinstance(node, ast.BinOp):
            return self._eval_binop(node)
        if isinstance(node, ast.Call):
            return self._eval_call(node)
        if isinstance(node, ast.MethodCall):
            # Enum.Variant(x) — конструктор варианта с нагрузкой
            if isinstance(node.obj, ast.Name) and node.obj.ident in self.enums:
                payload = deepcopy(self.eval(node.args[0]))
                return EnumValue(node.obj.ident, node.name, payload)
            obj = self.eval(node.obj)
            assert isinstance(obj, StructValue)
            method = self.structs[obj.name].methods[node.name]
            args = [self.eval(a) for a in node.args]
            return self.call_func(method, args, deepcopy(obj), node)
        if isinstance(node, ast.FieldAccess):
            if isinstance(node.obj, ast.Name) and node.obj.ident in self.enums:
                return EnumValue(node.obj.ident, node.name)
            obj = self.eval(node.obj)
            assert isinstance(obj, StructValue)
            return obj.fields[node.name]
        if isinstance(node, ast.Index):
            obj = self.eval(node.obj)
            index = self.eval(node.index)
            self._check_bounds(node, obj, index)
            return obj[index]
        if isinstance(node, ast.StructLit):
            rt = self.structs[node.name]
            fields = {}
            for fname, fexpr in node.fields:
                value = deepcopy(self.eval(fexpr))
                kind, cap = rt.fields[fname]
                self._fit(fexpr, kind, value)
                self._fit_cap(fexpr, cap, value)
                fields[fname] = value
            return StructValue(node.name, fields)
        if isinstance(node, ast.ArrayLit):
            return [deepcopy(self.eval(e)) for e in node.elems]
        raise self.trap(node, "неизвестное выражение")

    def _eval_str(self, node: ast.StrLit) -> str:
        parts = []
        for seg in node.segments:
            if isinstance(seg, str):
                parts.append(seg)
                continue
            value = self.eval(seg)
            if isinstance(value, bool):
                parts.append("true" if value else "false")
            else:
                parts.append(str(value))
        return "".join(parts)

    def _eval_unary(self, node: ast.UnaryOp):
        value = self.eval(node.operand)
        if node.op == "not":
            return not value
        result = -value
        self._fit(node, "i32", result)
        return result

    def _eval_binop(self, node: ast.BinOp):
        op = node.op
        if op == "and":
            return self.eval(node.left) and self.eval(node.right)
        if op == "or":
            return self.eval(node.left) or self.eval(node.right)
        left = self.eval(node.left)
        right = self.eval(node.right)
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return self._trunc_div(node, left, right)
        return self._trunc_mod(node, left, right)

    def _trunc_div(self, node, left: int, right: int) -> int:
        if right == 0:
            raise self.trap(node, "деление на ноль")
        return int(left / right)

    def _trunc_mod(self, node, left: int, right: int) -> int:
        if right == 0:
            raise self.trap(node, "деление на ноль (остаток)")
        return left - int(left / right) * right

    def _check_bounds(self, node, obj, index: int) -> None:
        if not 0 <= index < len(obj):
            raise self.trap(
                node,
                f"индекс {index} вне границ [0, {len(obj)})",
            )

    # --- вызовы --------------------------------------------------------------

    def _eval_call(self, node: ast.Call):
        args = [self.eval(a) for a in node.args]
        name = node.name
        if name == "print":
            print(args[0], flush=True)
            return None
        if name == "write":
            sys.stdout.write(args[0])
            sys.stdout.flush()
            return None
        if name == "read_byte":
            data = sys.stdin.buffer.read(1)
            if not data:
                return Tagged("Err", EnumValue("IoError", "Eof"))
            return Tagged("Ok", data[0])
        if name == "read_line":
            line = sys.stdin.readline()
            if line == "":
                return Tagged("Err", EnumValue("IoError", "Eof"))
            line = line.rstrip("\n")
            if len(line.encode("utf-8")) > 256:
                raise self.trap(node, "ввод длиннее str<256>")
            return Tagged("Ok", line)
        if name == "parse_i32":
            return self._parse_i32(args[0])
        if name == "len":
            return len(args[0])
        if name == "char":
            return chr(args[0])
        if name in INT_RANGES:
            if isinstance(args[0], str):  # u8(char): код байта
                return ord(args[0])
            self._fit(node, name, args[0])
            return args[0]
        return self.call_func(self.funcs[name], args, None, node)

    def _parse_i32(self, s: str) -> Tagged:
        text = s.strip()

        def err(variant: str) -> Tagged:
            return Tagged("Err", EnumValue("ParseError", variant))

        if not text:
            return err("Empty")
        body = text[1:] if text[0] in "+-" else text
        if not body.isdigit():
            return err("BadChar")
        value = int(text)
        lo, hi = INT_RANGES["i32"]
        if not lo <= value <= hi:
            return err("Overflow")
        return Tagged("Ok", value)
