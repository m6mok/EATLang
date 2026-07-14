"""Интерпретатор EATLang — эталон семантики до LLVM-кодогенерации.

Исполняет типизированный AST. Нарушение контракта, переполнение,
деление на ноль, выход за границы — trap (аварийная остановка с
координатами). Семантика передачи — by-value: копия на каждой точке
связывания (аргумент, let, присваивание, return).
"""

import operator
import sys
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


# Бинарные операции без trap-путей — прямые C-функции operator.*;
# and/or (ленивость), сдвиги и деление (trap) остаются в _eval_binop.
_BINOP_FNS = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "&": operator.and_,
    "|": operator.or_,
    "^": operator.xor,
}


def _copy_value(v):
    """Копия by-value. int/bool/str неизменяемы в Python — как есть;
    рекурсивно копируются только составные (list, struct и обёртки
    с потенциально составной нагрузкой)."""
    t = type(v)
    if t is list:
        return [_copy_value(x) for x in v]
    if t is StructValue:
        return StructValue(
            v.name, {k: _copy_value(x) for k, x in v.fields.items()}
        )
    if t is Tagged:
        p = _copy_value(v.payload)
        return v if p is v.payload else Tagged(v.tag, p)
    if t is EnumValue:
        p = _copy_value(v.payload)
        return v if p is v.payload else EnumValue(v.enum, v.variant, p)
    return v


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

    def _meta(self, tnode) -> tuple:
        """(kind, cap) типа — кэш на самом узле: узлы типов
        перечитываются на каждый вызов/let горячего пути."""
        if tnode is None:
            return (None, None)
        meta = getattr(tnode, "interp_meta", None)
        if meta is None:
            meta = (self._kind(tnode), self._cap(tnode))
            tnode.interp_meta = meta
        return meta

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
        fname = getattr(node, "src_file", None) or self.filename
        return Trap(fname, node.line, node.col, message)

    def _fit(self, node, kind: str | None, value) -> None:
        if kind is None:
            return
        lo, hi = INT_RANGES[kind]
        if not lo <= value <= hi:
            raise self.trap(
                node, f"переполнение: {value} вне {kind} [{lo}, {hi}]"
            )

    def _fit_cap(self, node, cap: int | None, value) -> None:
        # Значения строк хранятся в latin-1: len == число байт.
        if cap is None or not isinstance(value, str):
            return
        if len(value) > cap:
            raise self.trap(node, f"строка длиннее ёмкости str<{cap}>")

    @staticmethod
    def _write_bytes(value: str) -> None:
        sys.stdout.buffer.write(value.encode("latin-1"))
        sys.stdout.buffer.flush()

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
                    getattr(decl, "src_file", None) or self.filename,
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
        if func.is_extern:
            raise self.trap(
                site,
                f"extern {func.name} доступен только в бинарнике "
                "(интерпретатор не линкует C)",
            )
        self.frames.append([{}])
        try:
            if self_value is not None:
                self.declare("self", Slot(self_value))
            arg_i = 0
            for param in func.params:
                if param.name == "self":
                    continue
                value = _copy_value(args[arg_i])
                arg_i += 1
                kind, cap = self._meta(param.type)
                if kind is not None:
                    self._fit(site, kind, value)
                if cap is not None:
                    self._fit_cap(site, cap, value)
                self.declare(param.name, Slot(value, kind, cap))
            req = func.requires
            # `requires true` — тривиальный контракт, не тратим eval
            if req is not None and not (
                type(req) is ast.BoolLit and req.value
            ):
                if not self.eval(req):
                    raise self.trap(
                        site, f"нарушен requires функции {func.name}"
                    )
            result = None
            try:
                self.exec_block(func.body)
            except ReturnSignal as ret:
                result = _copy_value(ret.value)
            ens = func.ensures
            if ens is not None and not (
                type(ens) is ast.BoolLit and ens.value
            ):
                self.declare("result", Slot(result))
                if not self.eval(ens):
                    raise self.trap(
                        site, f"нарушен ensures функции {func.name}"
                    )
            return result
        finally:
            # кадр снимается и при trap'е: иначе внешние finally
            # чистили бы чужие области видимости
            self.frames.pop()

    # --- инструкции --------------------------------------------------------

    def exec_block(self, block: ast.Block) -> None:
        self.push_scope()
        try:
            for stmt in block.stmts:
                self.exec_stmt(stmt)
        finally:
            self.pop_scope()

    def exec_stmt(self, stmt: ast.Stmt) -> None:
        handler = self._EXEC.get(type(stmt))
        if handler is None:
            raise self.trap(stmt, "неизвестная инструкция")
        handler(self, stmt)

    def _exec_let(self, stmt: ast.LetStmt) -> None:
        value = _copy_value(self.eval(stmt.value))
        kind, cap = self._meta(stmt.type)
        if kind is not None:
            self._fit(stmt, kind, value)
        if cap is not None:
            self._fit_cap(stmt, cap, value)
        self.declare(stmt.name, Slot(value, kind, cap))

    def _exec_if(self, stmt: ast.IfStmt) -> None:
        if self.eval(stmt.cond):
            self.exec_block(stmt.then)
            return
        for cond, blk in stmt.elifs:
            if self.eval(cond):
                self.exec_block(blk)
                return
        if stmt.els is not None:
            self.exec_block(stmt.els)

    def _exec_loop(self, stmt: ast.LoopStmt) -> None:
        try:
            while True:
                self.exec_block(stmt.body)
        except BreakSignal:
            pass

    def _exec_return(self, stmt: ast.ReturnStmt) -> None:
        value = self.eval(stmt.value) if stmt.value is not None else None
        raise ReturnSignal(value)

    def _exec_break(self, stmt: ast.BreakStmt) -> None:
        raise BreakSignal()

    def _exec_assert(self, stmt: ast.AssertStmt) -> None:
        if not self.eval(stmt.cond):
            raise self.trap(stmt, "assert не выполнен")

    def _exec_expr(self, stmt) -> None:
        self.eval(stmt.expr)

    def exec_assign(self, stmt: ast.AssignStmt) -> None:
        value = _copy_value(self.eval(stmt.value))
        target = stmt.target
        if type(target) is ast.Name:
            slot = self.slot(target, target.ident)
            if slot.kind is not None:
                self._fit(stmt, slot.kind, value)
            if slot.cap is not None:
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
        # скоупы витка (переменная цикла + тело) создаются один раз
        # и переиспользуются: не 2 dict-аллокации на каждый виток
        frame = self.frames[-1]
        loop_scope: dict = {}
        body_scope: dict = {}
        frame.append(loop_scope)
        frame.append(body_scope)
        target = stmt.target
        stmts = stmt.body.stmts
        exec_stmt = self.exec_stmt
        tslot = None
        if target != "_":
            tslot = Slot(None)
            loop_scope[target] = tslot
        try:
            for item in items:
                if tslot is not None:
                    tslot.value = _copy_value(item)
                body_scope.clear()
                for s in stmts:
                    exec_stmt(s)
        except BreakSignal:
            pass  # break привязан к внутреннему циклу — этому
        finally:
            frame.pop()
            frame.pop()

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
                self.declare(arm.binding, Slot(_copy_value(payload)))
            try:
                self.exec_block(arm.body)
            finally:
                self.pop_scope()
            return
        raise self.trap(stmt, f"нет ветки match для {tag}")

    # --- выражения -----------------------------------------------------------

    def eval(self, node: ast.Expr):
        handler = self._EVAL.get(type(node))
        if handler is None:
            raise self.trap(node, "неизвестное выражение")
        return handler(self, node)

    def _eval_lit(self, node):
        return node.value

    def _eval_self(self, node: ast.SelfExpr):
        return self.slot(node, "self").value

    def _eval_name(self, node: ast.Name):
        if getattr(node, "ctor", None) is not None:
            return Tagged("None", None)
        return self.slot(node, node.ident).value

    def _eval_methodcall(self, node: ast.MethodCall):
        # Enum.Variant(x) — конструктор варианта с нагрузкой
        if isinstance(node.obj, ast.Name) and node.obj.ident in self.enums:
            payload = _copy_value(self.eval(node.args[0]))
            return EnumValue(node.obj.ident, node.name, payload)
        obj = self.eval(node.obj)
        assert isinstance(obj, StructValue)
        method = self.structs[obj.name].methods[node.name]
        args = [self.eval(a) for a in node.args]
        # var self: метод мутирует получателя — передаём сам объект
        var_self = bool(method.params) and method.params[0].mutable
        return self.call_func(
            method, args, obj if var_self else _copy_value(obj), node
        )

    def _eval_fieldaccess(self, node: ast.FieldAccess):
        if isinstance(node.obj, ast.Name) and node.obj.ident in self.enums:
            return EnumValue(node.obj.ident, node.name)
        obj = self.eval(node.obj)
        assert isinstance(obj, StructValue)
        return obj.fields[node.name]

    def _eval_index(self, node: ast.Index):
        obj = self.eval(node.obj)
        index = self.eval(node.index)
        self._check_bounds(node, obj, index)
        return obj[index]

    def _eval_structlit(self, node: ast.StructLit):
        rt = self.structs[node.name]
        fields = {}
        for fname, fexpr in node.fields:
            value = _copy_value(self.eval(fexpr))
            kind, cap = rt.fields[fname]
            self._fit(fexpr, kind, value)
            self._fit_cap(fexpr, cap, value)
            fields[fname] = value
        return StructValue(node.name, fields)

    def _eval_arraylit(self, node: ast.ArrayLit):
        return [_copy_value(self.eval(e)) for e in node.elems]

    def _eval_arrayfill(self, node: ast.ArrayFill):
        value = self.eval(node.value)
        return [_copy_value(value) for _ in range(node.size)]

    def _eval_str(self, node: ast.StrLit) -> str:
        # Строка — байты (как в рантайме): литерал из исходника
        # переводится в latin-1-представление, где 1 символ == 1 байт.
        parts = []
        for seg in node.segments:
            if isinstance(seg, str):
                parts.append(seg.encode("utf-8").decode("latin-1"))
                continue
            value = self.eval(seg)
            if isinstance(value, bool):
                parts.append("true" if value else "false")
            else:
                parts.append(str(value))
        result = "".join(parts)
        # ёмкость рантайма: собранная строка не длиннее str<256>
        if len(result) > 256:
            raise self.trap(node, "строка длиннее ёмкости str<256>")
        return result

    def _eval_unary(self, node: ast.UnaryOp):
        value = self.eval(node.operand)
        if node.op == "not":
            return not value
        if node.op == "~":
            # инверсия в ширине типа: ~x == маска - x, из типа не выходит
            mask = INT_RANGES[node.operand.ty.kind][1]
            return value ^ mask
        result = -value
        self._fit(node, node.ty.kind, result)
        return result

    def _eval_binop(self, node: ast.BinOp):
        op = node.op
        if op == "and":
            return self.eval(node.left) and self.eval(node.right)
        if op == "or":
            return self.eval(node.left) or self.eval(node.right)
        left = self.eval(node.left)
        right = self.eval(node.right)
        fn = _BINOP_FNS.get(op)
        if fn is not None:
            return fn(left, right)
        if op in ("<<", ">>"):
            return self._shift(node, op, left, right)
        if op == "/":
            return self._trunc_div(node, left, right)
        return self._trunc_mod(node, left, right)

    def _shift(self, node, op: str, left: int, right: int) -> int:
        kind = node.left.ty.kind
        width = {"u8": 8, "u16": 16, "u64": 64}.get(kind, 32)
        if right >= width:
            raise self.trap(node, f"сдвиг на {right} ≥ ширины {kind}")
        return left << right if op == "<<" else left >> right

    @staticmethod
    def _tdiv(left: int, right: int) -> int:
        # усечение к нулю в целых: float-путь терял точность на 64 битах
        q = abs(left) // abs(right)
        return -q if (left < 0) != (right < 0) else q

    def _trunc_div(self, node, left: int, right: int) -> int:
        if right == 0:
            raise self.trap(node, "деление на ноль")
        return self._tdiv(left, right)

    def _trunc_mod(self, node, left: int, right: int) -> int:
        if right == 0:
            raise self.trap(node, "деление на ноль (остаток)")
        return left - self._tdiv(left, right) * right

    def _check_bounds(self, node, obj, index: int) -> None:
        if not 0 <= index < len(obj):
            raise self.trap(
                node,
                f"индекс {index} вне границ [0, {len(obj)})",
            )

    # --- вызовы --------------------------------------------------------------

    def _eval_call(self, node: ast.Call):
        # конструкторы Ok/Err/Some — значение с тегом (SPEC §5.3)
        if getattr(node, "ctor", None) is not None:
            return Tagged(node.ctor, _copy_value(self.eval(node.args[0])))
        args = [self.eval(a) for a in node.args]
        name = node.name
        if name == "print":
            self._write_bytes(args[0] + "\n")
            return None
        if name == "write":
            self._write_bytes(args[0])
            return None
        if name == "read_byte":
            data = sys.stdin.buffer.read(1)
            if not data:
                return Tagged("Err", EnumValue("IoError", "Eof"))
            return Tagged("Ok", data[0])
        if name == "write_byte":
            self._write_bytes(chr(args[0]))
            return None
        if name == "write_span":
            obj, off, ln = args
            if off + ln > len(obj):
                raise self.trap(node, "write_span вне границ массива")
            self._write_bytes("".join(chr(b) for b in obj[off:off + ln]))
            return None
        if name == "write_err_byte":
            sys.stderr.buffer.write(bytes([args[0]]))
            sys.stderr.buffer.flush()
            return None
        if name == "exit":
            raise SystemExit(args[0])
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

    # --- диспетчеры (type(node) -> метод, вместо цепочек isinstance) --------

    _EVAL = {
        ast.IntLit: _eval_lit,
        ast.BoolLit: _eval_lit,
        ast.CharLit: _eval_lit,
        ast.StrLit: _eval_str,
        ast.SelfExpr: _eval_self,
        ast.Name: _eval_name,
        ast.UnaryOp: _eval_unary,
        ast.BinOp: _eval_binop,
        ast.Call: _eval_call,
        ast.MethodCall: _eval_methodcall,
        ast.FieldAccess: _eval_fieldaccess,
        ast.Index: _eval_index,
        ast.StructLit: _eval_structlit,
        ast.ArrayLit: _eval_arraylit,
        ast.ArrayFill: _eval_arrayfill,
    }

    _EXEC = {
        ast.LetStmt: _exec_let,
        ast.AssignStmt: exec_assign,
        ast.IfStmt: _exec_if,
        ast.ForStmt: exec_for,
        ast.LoopStmt: _exec_loop,
        ast.MatchStmt: exec_match,
        ast.ReturnStmt: _exec_return,
        ast.BreakStmt: _exec_break,
        ast.AssertStmt: _exec_assert,
        ast.ExprStmt: _exec_expr,
        ast.DiscardStmt: _exec_expr,
    }
