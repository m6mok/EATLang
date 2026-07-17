"""Интерпретатор EATLang — эталон семантики до LLVM-кодогенерации.

Исполняет типизированный AST. Нарушение контракта, переполнение,
деление на ноль, выход за границы — trap (аварийная остановка с
координатами). Семантика передачи — by-value: копия на каждой точке
связывания (аргумент, let, присваивание, return).
"""

import operator
import os
import sys
import time
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


class ComptimeBudget(Exception):
    """Превышен предел шагов comptime-вычисления (§5). Ловится
    comptime-входом и превращается в ошибку компиляции; в обычном
    прогоне (step_budget=None) не возникает."""


class ComptimeDepth(Exception):
    """Превышена глубина comptime-вызовов (COMPTIME_PLAN §9.2).
    Ловится comptime-входом; вне comptime-режима не возникает."""


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


# Нечистые встроенные (аксиомы ОС + обёртки вывода): в comptime-режиме
# (§5) их вызов — trap, а не побочный эффект. Зеркало множества —
# comptime.IMPURE_BUILTINS (статическая годность) и selfhost Eval.eat.
IMPURE_AXIOMS = frozenset({
    "read_byte", "write_byte", "write_span", "write_err_byte", "exit",
    "arg_count", "arg_len", "arg_byte", "print", "write",
    "in_avail", "ticks",
    "socket_listen", "socket_accept", "socket_avail",
    "socket_read_byte", "socket_write_span", "socket_close",
})


def _expr_has_call(node) -> bool:
    """Есть ли Call/MethodCall в поддереве выражения (для отсрочки
    comptime-констант в _collect: их значение вычисляется после сбора
    сигнатур)."""
    if node is None:
        return False
    if isinstance(node, (ast.Call, ast.MethodCall)):
        return True
    for attr in ("operand", "left", "right", "obj", "index"):
        if _expr_has_call(getattr(node, attr, None)):
            return True
    for lst in ("args",):
        for c in getattr(node, lst, None) or ():
            if _expr_has_call(c):
                return True
    return False


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
    def __init__(
        self, program: ast.Program, filename: str, argv: list | None = None
    ):
        self.program = program
        self.filename = filename
        # аргументы командной строки программы (argv без имени),
        # каждый — bytes; наполняет cmd_run из хвоста после `--`
        self.argv: list = list(argv) if argv else []
        # часы ticks() (ASYNC_PLAN, ярус 0): первый вызов — 0; режим
        # виртуальных часов (EAT_TICKS=virt) — счётчик вызовов, чтобы
        # интерпретатор и бинарник тикали одинаково в make verify
        self._ticks_virt: bool | None = None
        self._ticks_val: int = 0
        self._ticks_base: int | None = None
        # сокеты (HTTP_PLAN §5): транскрипт EAT_NET либо живой режим,
        # ленивое состояние как у часов ticks
        self._net = None
        self.consts: dict[str, Slot] = {}
        self.funcs: dict[str, ast.FuncDecl] = {}
        self.structs: dict[str, StructRT] = {}
        self.enums: dict[str, list] = {
            "IoError": ["Eof", "Fail"],
            "ParseError": ["Empty", "BadChar", "Overflow"],
        }
        self.frames: list[list[dict]] = []
        # бюджет comptime (§5): None — обычный прогон без счёта; иначе
        # каждый eval/exec_stmt инкрементит steps, превышение —
        # ComptimeBudget. Шаг фиксирован в SPEC §6 (паритет с Eval.eat).
        self.step_budget: int | None = None
        self.steps: int = 0
        # comptime-режим: аксиомы ОС недоступны (trap); ставится вокруг
        # вычисления const-из-вызовов (§5). _const_pending — comptime-
        # константы (значение содержит вызов): вычисляются лениво по
        # обращению, чтобы порядок объявлений не влиял.
        self._comptime_mode: bool = False
        self._comptime_depth: int = 0
        self._const_pending: dict = {}
        self._const_resolving: set = set()
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
                # comptime-константа (значение через вызов) — отложить:
                # тела функций читаются как есть, порядок объявлений не
                # должен влиять; вычисляется лениво (_resolve_pending_const)
                if _expr_has_call(decl.value):
                    self._const_pending[decl.name] = decl
                    continue
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
            name = expr.ident
            if name in self._const_resolving:
                raise self.trap(expr, f"цикл в comptime-константе {name}")
            if name not in self.consts and name in self._const_pending:
                self._resolve_pending_const(name)
            return self.consts[name].value
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
        if isinstance(expr, ast.Call):
            # comptime-вызов (§5): чистая функция с константными
            # аргументами — вычисляется в comptime-режиме (бюджет шагов +
            # аксиомы недоступны). Ярус A: только скаляр.
            args = [self._const_eval(a) for a in expr.args]
            return self._comptime_call(self.funcs[expr.name], args, expr)
        raise self.trap(expr, "не константа")

    def _resolve_pending_const(self, name: str) -> None:
        """Ленивое вычисление отложенной comptime-константы. Cycle-guard:
        значение const во время вычисления помечено None — повторный
        вход по имени = цикл const->...->const (правило 1 покрывает
        только func->func)."""
        decl = self._const_pending.pop(name)
        kind = self._kind(decl.type)
        self._const_resolving.add(name)
        try:
            value = self._const_eval_ct(decl.value, kind)
        finally:
            self._const_resolving.discard(name)
        self._fit(decl, kind, value)
        self.consts[name] = Slot(value, kind)

    def _const_eval_ct(self, expr: ast.Expr, kind: str | None):
        """const-выражение comptime-константы (§9 COMPTIME_PLAN):
        строгая по-операционная семантика — каждая операция фитится к
        типу объявляемой константы (узлы const-значений не типизированы,
        гомогенность к типу константы), деление trunc, шаги не
        считаются. Обычные const'ы (без вызовов) идут прежним путём."""
        if isinstance(expr, ast.IntLit):
            return expr.value
        if isinstance(expr, ast.Name):
            name = expr.ident
            if name in self._const_resolving:
                raise self.trap(
                    expr, f"цикл в comptime-константе {name}"
                )
            if name not in self.consts and name in self._const_pending:
                self._resolve_pending_const(name)
            return self.consts[name].value
        if isinstance(expr, ast.UnaryOp):
            if expr.op != "-":
                raise self.trap(expr, "не константа")
            value = -self._const_eval_ct(expr.operand, kind)
            self._fit_ct(expr, kind, value)
            return value
        if isinstance(expr, ast.BinOp):
            left = self._const_eval_ct(expr.left, kind)
            right = self._const_eval_ct(expr.right, kind)
            op = expr.op
            if op in ("+", "-", "*"):
                value = {"+": left + right, "-": left - right,
                         "*": left * right}[op]
                self._fit_ct(expr, kind, value)
                return value
            if op in ("/", "%"):
                if right == 0:
                    raise self.trap(expr, "деление на ноль")
                if kind in ("i32", "i64") and right == -1 \
                        and left == INT_RANGES[kind][0]:
                    raise self.trap(expr, f"переполнение {kind}")
                return (self._tdiv(left, right) if op == "/"
                        else left - self._tdiv(left, right) * right)
        if isinstance(expr, ast.Call):
            if expr.name in INT_RANGES:
                # каст в const-выражении: чек диапазона, текст кодогена
                value = self._const_eval_ct(expr.args[0], kind)
                lo, hi = INT_RANGES[expr.name]
                if not lo <= value <= hi:
                    raise self.trap(
                        expr, f"переполнение при {expr.name}()"
                    )
                return value
            func = self.funcs.get(expr.name)
            if func is None:
                raise self.trap(
                    expr, f"неизвестная функция {expr.name}"
                )
            if func.ret is None:
                raise self.trap(
                    expr,
                    "функция ничего не возвращает — это не значение",
                )
            args = [self._const_eval_ct(a, kind) for a in expr.args]
            return self._comptime_call(func, args, expr)
        raise self.trap(expr, "не константа")

    def _fit_ct(self, node, kind: str | None, value) -> None:
        if kind is None:
            return
        lo, hi = INT_RANGES[kind]
        if not lo <= value <= hi:
            raise self.trap(node, f"переполнение {kind}")

    def _comptime_call(self, func: ast.FuncDecl, args: list, site):
        """Вызов чистой функции на компиляции: бюджет шагов + запрет
        аксиом. Бюджет — на верхнеуровневый вызов (§9.2): вложенный
        _comptime_call (ленивая резолюция const внутри тела) НЕ
        сбрасывает счётчик — шаги копятся в бюджете корня."""
        prev_mode = self._comptime_mode
        fresh = self.step_budget is None
        from .limits import MAX_COMPTIME_STEPS
        self._comptime_mode = True
        if fresh:
            self.step_budget = MAX_COMPTIME_STEPS
            self.steps = 0
        try:
            return self.call_func(func, args, None, site)
        finally:
            self._comptime_mode = prev_mode
            if fresh:
                self.step_budget = None
                self.steps = 0

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
        if name in self._const_resolving:
            raise self.trap(node, f"цикл в comptime-константе {name}")
        if name not in self.consts and name in self._const_pending:
            self._resolve_pending_const(name)  # comptime-const по доступу
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
        copy_args: bool = True,
    ):
        if func.is_extern:
            raise self.trap(
                site,
                f"extern {func.name} доступен только в бинарнике "
                "(интерпретатор не линкует C)",
            )
        self.frames.append([{}])
        try:
            if self._comptime_mode:
                from .limits import MAX_COMPTIME_CALL_DEPTH
                self._comptime_depth += 1
                if self._comptime_depth > MAX_COMPTIME_CALL_DEPTH:
                    raise ComptimeDepth()
            if self_value is not None:
                self.declare("self", Slot(self_value))
            arg_i = 0
            for param in func.params:
                if param.name == "self":
                    continue
                value = _copy_value(args[arg_i]) if copy_args else args[arg_i]
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
            if self._comptime_mode:
                self._comptime_depth -= 1

    # --- инструкции --------------------------------------------------------

    def exec_block(self, block: ast.Block) -> None:
        self.push_scope()
        try:
            for stmt in block.stmts:
                self.exec_stmt(stmt)
        finally:
            self.pop_scope()

    def exec_stmt(self, stmt: ast.Stmt) -> None:
        if self.step_budget is not None:
            self.steps += 1
            if self.steps > self.step_budget:
                raise ComptimeBudget()
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
                if self.step_budget is not None:
                    self.steps += 1
                    if self.steps > self.step_budget:
                        raise ComptimeBudget()
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
                # виток цикла — шаг comptime: иначе тугой цикл с
                # пустым/дешёвым телом не тратил бы бюджет (§5)
                if self.step_budget is not None:
                    self.steps += 1
                    if self.steps > self.step_budget:
                        raise ComptimeBudget()
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
        if self.step_budget is not None:
            self.steps += 1
            if self.steps > self.step_budget:
                raise ComptimeBudget()
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
        # получатель без копии: без var self тайпчекер запрещает мутацию
        # self и параметров — на время вызова вся достижимая память
        # вызывающего заморожена, копия ненаблюдаема. При var self
        # аргументы копируются: аргумент может алиасить внутренности
        # мутируемого self (s.m(s.arr))
        var_self = bool(method.params) and method.params[0].mutable
        return self.call_func(method, args, obj, node, copy_args=var_self)

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
        if self._comptime_mode:  # текст кодогена (§9.1)
            lo, hi = INT_RANGES[node.ty.kind]
            if not lo <= result <= hi:
                raise self.trap(node, f"переполнение {node.ty.kind}")
            return result
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
            result = fn(left, right)
            if self._comptime_mode and op in ("+", "-", "*"):
                # строгая по-операционная семантика (§9.1 COMPTIME_PLAN):
                # comptime == бинарник; тексты — кодогена
                lo, hi = INT_RANGES[node.ty.kind]
                if not lo <= result <= hi:
                    raise self.trap(node, f"переполнение {node.ty.kind}")
            return result
        if op in ("<<", ">>"):
            return self._shift(node, op, left, right)
        if op == "/":
            return self._trunc_div(node, left, right)
        return self._trunc_mod(node, left, right)

    def _shift(self, node, op: str, left: int, right: int) -> int:
        kind = node.left.ty.kind
        width = {"u8": 8, "u16": 16, "u64": 64}.get(kind, 32)
        if right >= width:
            if self._comptime_mode:  # текст кодогена (§9.1)
                raise self.trap(node, f"сдвиг ≥ ширины {kind}")
            raise self.trap(node, f"сдвиг на {right} ≥ ширины {kind}")
        if op == "<<" and self._comptime_mode:
            # семантика бинарника: shl усечён по ширине (LLVM wrap)
            return (left << right) & INT_RANGES[kind][1]
        return left << right if op == "<<" else left >> right

    @staticmethod
    def _tdiv(left: int, right: int) -> int:
        # усечение к нулю в целых: float-путь терял точность на 64 битах
        q = abs(left) // abs(right)
        return -q if (left < 0) != (right < 0) else q

    def _div_edge(self, node, left: int, right: int) -> None:
        """Строгий режим (§9.1): INT_MIN/(-1) знаковых — переполнение,
        как edge-проверка кодогена перед sdiv/srem."""
        kind = node.ty.kind
        if kind in ("i32", "i64") and right == -1 \
                and left == INT_RANGES[kind][0]:
            raise self.trap(node, f"переполнение {kind}")

    def _trunc_div(self, node, left: int, right: int) -> int:
        if right == 0:
            raise self.trap(node, "деление на ноль")
        if self._comptime_mode:
            self._div_edge(node, left, right)
        return self._tdiv(left, right)

    def _trunc_mod(self, node, left: int, right: int) -> int:
        if right == 0:
            if self._comptime_mode:  # текст кодогена — общий с делением
                raise self.trap(node, "деление на ноль")
            raise self.trap(node, "деление на ноль (остаток)")
        if self._comptime_mode:
            self._div_edge(node, left, right)
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
        if self._comptime_mode and name in IMPURE_AXIOMS:
            # защита: даже при обходе годности аксиома не даёт побочного
            # эффекта на компиляции — trap → ошибка компиляции (§5)
            raise self.trap(
                node, f"аксиома {name} недоступна в comptime"
            )
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
        if name == "arg_count":
            return len(self.argv)
        if name == "arg_len":
            i = args[0]
            if i >= len(self.argv):
                raise self.trap(node, "arg_len вне границ argv")
            return len(self.argv[i])
        if name == "arg_byte":
            i, j = args
            if i >= len(self.argv):
                raise self.trap(node, "arg_byte вне границ argv")
            if j >= len(self.argv[i]):
                raise self.trap(node, "arg_byte вне границ аргумента")
            return self.argv[i][j]
        if name == "in_avail":
            return self._in_avail()
        if name == "ticks":
            return self._ticks()
        if name == "socket_listen":
            return self._net_ref().listen(args[0])
        if name == "socket_accept":
            return self._net_ref().accept(args[0])
        if name == "socket_avail":
            return self._net_ref().avail(args[0])
        if name == "socket_read_byte":
            return self._net_ref().read_byte(args[0])
        if name == "socket_write_span":
            fd, obj, off, ln = args
            if off + ln > len(obj):
                raise self.trap(
                    node, "socket_write_span вне границ массива"
                )
            return self._net_ref().write_span(fd, obj[off:off + ln])
        if name == "socket_close":
            self._net_ref().close(args[0])
            return None
        if name == "len":
            return len(args[0])
        if name == "char":
            return chr(args[0])
        if name in INT_RANGES:
            if isinstance(args[0], str):  # u8(char): код байта
                return ord(args[0])
            if self._comptime_mode:  # текст кодогена (§9.1)
                lo, hi = INT_RANGES[name]
                if not lo <= args[0] <= hi:
                    raise self.trap(node, f"переполнение при {name}()")
                return args[0]
            self._fit(node, name, args[0])
            return args[0]
        # у обычных функций все параметры немутабельны — аргументы без копий
        return self.call_func(self.funcs[name], args, None, node, copy_args=False)

    def _in_avail(self) -> int:
        """in_avail(): сколько байт stdin читается без блокировки.
        Файл — размер минус логическая позиция (зеркало ftello поверх
        stdio-буфера шима: детерминизм make verify); пайп/tty —
        FIONREAD, живой режим (недооценка на буфер допустима, SPEC §7).
        Потолок — u32."""
        import fcntl
        import stat as stat_mod
        import struct
        import termios
        buf = sys.stdin.buffer
        try:
            fd = buf.fileno()
            st = os.fstat(fd)
            if stat_mod.S_ISREG(st.st_mode):
                avail = st.st_size - buf.tell()
            else:
                raw = fcntl.ioctl(fd, termios.FIONREAD, b"\x00" * 4)
                avail = struct.unpack("i", raw)[0]
        except (OSError, ValueError):
            return 0
        if avail <= 0:
            return 0
        return min(avail, 0xFFFFFFFF)

    def _ticks(self) -> int:
        """ticks(): монотонные миллисекунды, первый вызов — 0.
        EAT_TICKS=virt — виртуальные часы: +1 на вызов (решение D2
        ASYNC_PLAN): паритет с бинарником без знания о витках loop."""
        if self._ticks_virt is None:
            self._ticks_virt = os.environ.get("EAT_TICKS") == "virt"
        if self._ticks_virt:
            val = self._ticks_val
            self._ticks_val += 1
            return val
        now = time.monotonic_ns() // 1000000
        if self._ticks_base is None:
            self._ticks_base = now
        return now - self._ticks_base

    def _net_ref(self):
        """Сокеты (HTTP_PLAN §5): EAT_NET=<файл> — транскрипт (сверка),
        иначе живой режим. Ленивая инициализация, как часы ticks."""
        if self._net is None:
            path = os.environ.get("EAT_NET")
            if path:
                self._net = _NetTranscript(self, path)
            else:
                self._net = _NetLive(self)
        return self._net

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


NO_CONN = 0xFFFFFFFF


def _shim_trap(msg: str):
    """Trap на границе аксиом (контракт fd, кривой сценарий): зеркало
    eat_trap шима — сообщение без координат в stderr, код 1. Тексты —
    байт-в-байт с runtime.c."""
    sys.stdout.flush()
    sys.stderr.buffer.write((msg + "\n").encode("utf-8"))
    sys.stderr.flush()
    raise SystemExit(1)


class _NetTranscript:
    """Сокеты в режиме сверки (HTTP_PLAN §5, решение H2): записанный
    транскрипт EAT_NET — текстовые события `accept` / `data <fd>
    <байты>` / `close <fd>`, потребляются по порядку. Зеркало разбора
    и семантики сокетной секции runtime.c: дескрипторы детерминированы
    (слушатель 3, соединения 4, 5, ...), данные «в пути» применяются
    до ближайшего accept (net_advance), чтение без готовых данных —
    детерминированный trap (суррогат вечной блокировки)."""

    def __init__(self, it, path):
        self.it = it
        self.events = []      # (kind 0|1|2, fd, payload bytes)
        self.ev_next = 0
        self.conns = []       # [queue bytearray, peer_closed, prog_closed]
        self.listener_open = False
        self._parse(path)

    def _fail(self):
        _shim_trap("EAT_NET: неверный сценарий")

    def _parse(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self._fail()
        i, n = 0, len(data)
        while i < n:
            c = data[i]
            if c == 0x0A:
                i += 1
                continue
            if c == 0x23:  # '#' — комментарий до конца строки
                while i < n and data[i] != 0x0A:
                    i += 1
                continue
            j = i
            while j < n and data[j] not in (0x0A, 0x20):
                j += 1
            word = data[i:j]
            i = j
            tail_sp = i < n and data[i] == 0x20
            if word == b"accept":
                if tail_sp:
                    self._fail()
                self.events.append((0, 0, b""))
                continue
            if word not in (b"data", b"close"):
                self._fail()
            if not tail_sp:
                self._fail()
            i += 1
            fd, nd = 0, 0
            while i < n and 0x30 <= data[i] <= 0x39:
                fd = fd * 10 + (data[i] - 0x30)
                nd += 1
                i += 1
            if nd == 0:
                self._fail()
            if word == b"close":
                if i < n and data[i] != 0x0A:
                    self._fail()
                self.events.append((2, fd, b""))
                continue
            if i >= n or data[i] != 0x20:
                self._fail()
            i += 1
            payload = bytearray()
            while i < n and data[i] != 0x0A:
                b = data[i]
                if b == 0x5C:  # '\'
                    i += 1
                    e = data[i] if i < n else -1
                    if e == ord("r"):
                        payload.append(0x0D)
                    elif e == ord("n"):
                        payload.append(0x0A)
                    elif e == ord("t"):
                        payload.append(0x09)
                    elif e == 0x5C:
                        payload.append(0x5C)
                    elif e == ord("x"):
                        h = data[i + 1:i + 3].decode("ascii", "replace")
                        i += 2
                        try:
                            payload.append(int(h, 16))
                        except ValueError:
                            self._fail()
                    else:
                        self._fail()
                else:
                    payload.append(b)
                i += 1
            self.events.append((1, fd, bytes(payload)))

    def _advance(self):
        """Применить пассивные события (data/close) до ближайшего
        accept: темп поступления задаёт сценарий."""
        while self.ev_next < len(self.events):
            kind, fd, payload = self.events[self.ev_next]
            if kind == 0:
                break
            if fd < 4 or fd - 4 >= len(self.conns):
                self._fail()
            conn = self.conns[fd - 4]
            if kind == 2:
                conn[1] = True
            elif payload:
                conn[0].extend(payload)
            self.ev_next += 1

    def _slot(self, fd):
        if fd < 4 or fd - 4 >= len(self.conns) or self.conns[fd - 4][2]:
            _shim_trap("socket: неверный дескриптор")
        return self.conns[fd - 4]

    def listen(self, port):
        self.listener_open = True
        return Tagged("Ok", 3)

    def accept(self, fd):
        if fd != 3 or not self.listener_open:
            _shim_trap("socket: неверный дескриптор")
        self._advance()
        if (
            self.ev_next < len(self.events)
            and self.events[self.ev_next][0] == 0
        ):
            self.ev_next += 1
            self.conns.append([bytearray(), False, False])
            return 4 + len(self.conns) - 1
        return NO_CONN

    def avail(self, fd):
        conn = self._slot(fd)
        self._advance()
        if conn[0]:
            return min(len(conn[0]), 0xFFFFFFFF)
        return 1 if conn[1] else 0

    def read_byte(self, fd):
        conn = self._slot(fd)
        self._advance()
        if conn[0]:
            return Tagged("Ok", conn[0].pop(0))
        if conn[1]:
            return Tagged("Err", EnumValue("IoError", "Eof"))
        _shim_trap("socket_read_byte без готовых данных")

    def write_span(self, fd, data):
        self._slot(fd)
        self.it._write_bytes("".join(chr(b) for b in data))
        return len(data)

    def close(self, fd):
        if fd == 3:
            self.listener_open = False
            return
        if fd < 4 or fd - 4 >= len(self.conns):
            _shim_trap("socket: неверный дескриптор")
        # идемпотентно: повторный close слота — no-op
        self.conns[fd - 4][2] = True


class _NetLive:
    """Живой режим (make serve, вне гейта сверки): реальные
    неблокирующие сокеты — зеркало живой ветки runtime.c."""

    def __init__(self, it):
        self.it = it
        self.socks = {}  # fd ядра -> socket

    def listen(self, port):
        import socket as so
        try:
            s = so.socket(so.AF_INET, so.SOCK_STREAM)
            s.setsockopt(so.SOL_SOCKET, so.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.listen(16)
            s.setblocking(False)
        except OSError:
            return Tagged("Err", EnumValue("IoError", "Fail"))
        self.socks[s.fileno()] = s
        return Tagged("Ok", s.fileno())

    def accept(self, fd):
        sock = self.socks.get(fd)
        if sock is None:
            _shim_trap("socket: неверный дескриптор")
        try:
            conn, _ = sock.accept()
        except (BlockingIOError, InterruptedError):
            return NO_CONN
        except OSError:
            _shim_trap("socket: неверный дескриптор")
        conn.setblocking(False)
        self.socks[conn.fileno()] = conn
        return conn.fileno()

    def avail(self, fd):
        import fcntl
        import select
        import struct
        import termios
        if fd not in self.socks:
            return 0
        try:
            raw = fcntl.ioctl(fd, termios.FIONREAD, b"\x00" * 4)
            n = struct.unpack("i", raw)[0]
        except OSError:
            n = 0
        if n > 0:
            return min(n, 0xFFFFFFFF)
        r, _, _ = select.select([fd], [], [], 0)
        return 1 if r else 0

    def read_byte(self, fd):
        import select
        sock = self.socks.get(fd)
        if sock is None:
            _shim_trap("socket: неверный дескриптор")
        while True:
            try:
                b = sock.recv(1)
            except (BlockingIOError, InterruptedError):
                # страж avail не сработал — блокирующая семантика
                select.select([fd], [], [])
                continue
            except OSError:
                return Tagged("Err", EnumValue("IoError", "Fail"))
            if b:
                return Tagged("Ok", b[0])
            return Tagged("Err", EnumValue("IoError", "Eof"))

    def write_span(self, fd, data):
        sock = self.socks.get(fd)
        if sock is None:
            _shim_trap("socket: неверный дескриптор")
        if not data:
            return 0
        try:
            return sock.send(bytes(data))
        except (BlockingIOError, InterruptedError):
            return 0
        except OSError:
            # пир умер: байты некому слать — считаем принятыми,
            # закрытие сервер увидит по Err(Eof) чтения
            return len(data)

    def close(self, fd):
        sock = self.socks.pop(fd, None)
        if sock is not None:
            sock.close()
