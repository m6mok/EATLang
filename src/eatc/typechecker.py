"""Тайпчекер и семантический анализ EATLang.

Проверяет здесь (номера — правила NASA Power of 10):
  1  — граф вызовов обязан быть DAG (рекурсия запрещена);
       побочный артефакт: точная глубина стека
  2  — границы for-циклов — константы времени компиляции
  6  — shadowing запрещён
  7  — результат вызова нельзя отбросить молча; match исчерпывающий
  10 — неиспользуемая переменная и недостижимый код — ошибки

Плюс собственно типы: никаких неявных преобразований (SPEC.md §3).
"""

from dataclasses import dataclass, field

from . import ast_nodes as ast
from .errors import EatError
from .limits import MAX_ARRAY_ELEMS, MAX_STR_CAPACITY
from .types import (
    BOOL,
    CHAR,
    I32,
    INT_RANGES,
    U8,
    U32,
    VOID,
    ArrayType,
    BoolType,
    CharType,
    EnumType,
    IntType,
    OptionType,
    ResultType,
    StructType,
    StrType,
    Type,
    compatible,
    show,
)

_INT_CASTS = {"i32": I32, "u32": U32, "u8": U8}

BUILTIN_ENUMS = {
    "IoError": ["Eof", "Fail"],
    "ParseError": ["Empty", "BadChar", "Overflow"],
}


@dataclass
class FuncSig:
    name: str
    params: list  # [(имя, Type)]
    ret: Type | None
    node: ast.FuncDecl | None = None


@dataclass
class StructInfo:
    name: str
    fields: dict
    methods: dict  # имя -> FuncSig (params без self)


@dataclass
class VarInfo:
    type: Type
    mutable: bool
    line: int
    col: int
    used: bool = False


@dataclass
class CheckResult:
    stack_depth: int = 0
    funcs: int = 0
    edges: set = field(default_factory=set)
    checker: object = None  # TypeChecker — таблицы типов для кодогенерации


BUILTINS = {
    "print": FuncSig("print", [("s", StrType(None))], None),
    "read_line": FuncSig(
        "read_line", [], ResultType(StrType(256), EnumType("IoError"))
    ),
    "parse_i32": FuncSig(
        "parse_i32",
        [("s", StrType(None))],
        ResultType(I32, EnumType("ParseError")),
    ),
}

_FORMATTABLE = (IntType, BoolType, CharType, StrType)


class TypeChecker:
    def __init__(self, program: ast.Program, filename: str):
        self.program = program
        self.filename = filename
        self.consts: dict[str, tuple] = {}  # имя -> (Type, int)
        self.funcs: dict[str, FuncSig] = {}
        self.structs: dict[str, StructInfo] = {}
        self.enums: dict[str, list] = dict(BUILTIN_ENUMS)
        # enum -> {вариант: Type нагрузки | None}
        self.enum_payloads: dict[str, dict] = {
            n: {v: None for v in vs} for n, vs in BUILTIN_ENUMS.items()
        }
        self.scopes: list[dict] = []
        self.current: FuncSig | None = None
        self.current_key = ""
        self.self_type: StructType | None = None
        self.result_type: Type | None = None  # доступен только в ensures
        self.loop_depth = 0
        self.edges: set = set()

    # --- инфраструктура -------------------------------------------------

    def err(self, node: ast.Node, message: str) -> EatError:
        return EatError(self.filename, node.line, node.col, message)

    def push_scope(self) -> None:
        self.scopes.append({})

    def pop_scope(self) -> None:
        scope = self.scopes.pop()
        for name, info in scope.items():
            if not info.used and name not in ("_", "self"):
                raise EatError(
                    self.filename,
                    info.line,
                    info.col,
                    f"переменная {name} не используется (правило 10)",
                )

    def declare(self, node: ast.Node, name: str, info: VarInfo) -> None:
        if name == "_":
            return
        for scope in self.scopes:
            if name in scope:
                raise self.err(
                    node,
                    f"имя {name} уже объявлено: shadowing запрещён "
                    "(правило 6)",
                )
        if name in self.consts or name in self.funcs or name in BUILTINS:
            raise self.err(
                node,
                f"имя {name} затеняет объявление верхнего уровня (правило 6)",
            )
        self.scopes[-1][name] = info

    def lookup(self, node: ast.Node, name: str) -> VarInfo | None:
        for scope in reversed(self.scopes):
            if name in scope:
                scope[name].used = True
                return scope[name]
        return None

    # --- запуск ------------------------------------------------------------

    def run(self) -> CheckResult:
        self.collect_decls()
        self._check_type_cycles()
        if "main" not in self.funcs:
            raise EatError(
                self.filename, 1, 1, "нет функции main — точки входа"
            )
        main = self.funcs["main"]
        if main.params or main.ret is not None:
            raise self.err(
                main.node,
                "main не принимает параметров и ничего не возвращает",
            )
        for decl in self.program.decls:
            if isinstance(decl, ast.FuncDecl):
                self.check_func(decl, decl.name, None)
            elif isinstance(decl, ast.StructDecl):
                for method in decl.methods:
                    self.check_func(
                        method,
                        f"{decl.name}.{method.name}",
                        StructType(decl.name),
                    )
            elif isinstance(decl, ast.TestBlock):
                self.check_test(decl)
        depth = self.check_call_graph()
        return CheckResult(
            stack_depth=depth,
            funcs=len(self.funcs),
            edges=self.edges,
            checker=self,
        )

    # --- сбор объявлений -----------------------------------------------------

    def collect_decls(self) -> None:
        # проход 1: имена типов
        for decl in self.program.decls:
            if isinstance(decl, ast.StructDecl):
                self._declare_top(decl, decl.name)
                self.structs[decl.name] = StructInfo(decl.name, {}, {})
            elif isinstance(decl, ast.EnumDecl):
                self._declare_top(decl, decl.name)
                names = [v for v, _ in decl.variants]
                if len(set(names)) != len(names):
                    raise self.err(decl, f"enum {decl.name}: повтор варианта")
                self.enums[decl.name] = names
        # проход 2: сигнатуры, поля, константы
        for decl in self.program.decls:
            if isinstance(decl, ast.ConstDecl):
                self._declare_top(decl, decl.name)
                ctype = self.resolve(decl.type)
                value = self.const_eval(decl.value)
                self._check_int_fits(decl, ctype, value)
                self.consts[decl.name] = (ctype, value)
            elif isinstance(decl, ast.FuncDecl):
                self._declare_top(decl, decl.name)
                self.funcs[decl.name] = self._signature(decl)
            elif isinstance(decl, ast.EnumDecl):
                self.enum_payloads[decl.name] = {
                    v: (self.resolve(t) if t is not None else None)
                    for v, t in decl.variants
                }
            elif isinstance(decl, ast.StructDecl):
                info = self.structs[decl.name]
                for fdecl in decl.fields:
                    if fdecl.name in info.fields:
                        raise self.err(
                            fdecl, f"поле {fdecl.name} объявлено дважды"
                        )
                    info.fields[fdecl.name] = self.resolve(fdecl.type)
                for method in decl.methods:
                    if not method.is_method:
                        raise self.err(
                            method,
                            f"функция {method.name} внутри struct обязана "
                            "иметь self первым параметром",
                        )
                    info.methods[method.name] = self._signature(method)

    def _declare_top(self, node: ast.Node, name: str) -> None:
        taken = (
            name in self.funcs
            or name in self.structs
            or name in self.enums
            or name in self.consts
            or name in BUILTINS
            or name in _INT_CASTS
            or name in ("len", "str", "char", "Result", "Option")
        )
        if taken:
            raise self.err(node, f"имя {name} уже занято")

    def _signature(self, func: ast.FuncDecl) -> FuncSig:
        params = []
        for p in func.params:
            if p.name != "self":
                params.append((p.name, self.resolve(p.type)))
        ret = self.resolve(func.ret) if func.ret is not None else None
        return FuncSig(func.name, params, ret, func)

    def _check_type_cycles(self) -> None:
        """Значения вкладываются по значению (указателей нет): цикл
        struct/enum через поля или нагрузку — бесконечный размер."""

        def deps(t):
            if isinstance(t, (StructType, EnumType)):
                yield t.name
            elif isinstance(t, ArrayType):
                yield from deps(t.elem)
            elif isinstance(t, ResultType):
                yield from deps(t.ok)
                yield from deps(t.err)
            elif isinstance(t, OptionType):
                yield from deps(t.inner)

        def members(name):
            if name in self.structs:
                return list(self.structs[name].fields.values())
            payloads = self.enum_payloads.get(name, {})
            return [t for t in payloads.values() if t is not None]

        state: dict[str, int] = {}  # 1 — в обходе, 2 — готов

        def visit(name, node):
            if state.get(name) == 2:
                return
            if state.get(name) == 1:
                raise self.err(
                    node,
                    f"тип {name} содержит сам себя по значению — "
                    "бесконечный размер (указателей нет)",
                )
            state[name] = 1
            for t in members(name):
                for dep in deps(t):
                    visit(dep, node)
            state[name] = 2

        for decl in self.program.decls:
            if isinstance(decl, (ast.StructDecl, ast.EnumDecl)):
                visit(decl.name, decl)

    # --- разрешение типов ----------------------------------------------------

    def resolve(self, node: ast.Node) -> Type:
        if isinstance(node, ast.TypeName):
            if node.name in _INT_CASTS:
                return _INT_CASTS[node.name]
            if node.name == "bool":
                return BOOL
            if node.name == "char":
                return CHAR
            if node.name in self.structs:
                return StructType(node.name)
            if node.name in self.enums:
                return EnumType(node.name)
            raise self.err(node, f"неизвестный тип {node.name}")
        if isinstance(node, ast.ArrayType):
            size = self.const_eval(node.size)
            if not 0 < size <= MAX_ARRAY_ELEMS:
                raise self.err(
                    node, f"размер массива {size} вне (0, {MAX_ARRAY_ELEMS}]"
                )
            return ArrayType(self.resolve(node.elem), size)
        if isinstance(node, ast.StrType):
            cap = self.const_eval(node.capacity)
            if not 0 < cap <= MAX_STR_CAPACITY:
                raise self.err(
                    node, f"ёмкость строки {cap} вне (0, {MAX_STR_CAPACITY}]"
                )
            return StrType(cap)
        if isinstance(node, ast.ResultType):
            return ResultType(self.resolve(node.ok), self.resolve(node.err))
        if isinstance(node, ast.OptionType):
            return OptionType(self.resolve(node.inner))
        raise self.err(node, "некорректный тип")

    def const_eval(self, expr: ast.Expr) -> int:
        """Константное выражение (правило 2: границы известны до запуска)."""
        if isinstance(expr, ast.IntLit):
            return expr.value
        if isinstance(expr, ast.Name):
            if expr.ident in self.consts:
                return self.consts[expr.ident][1]
            raise self.err(
                expr,
                f"{expr.ident} — не константа времени компиляции (правило 2)",
            )
        if isinstance(expr, ast.UnaryOp) and expr.op == "-":
            return -self.const_eval(expr.operand)
        if isinstance(expr, ast.BinOp):
            left = self.const_eval(expr.left)
            right = self.const_eval(expr.right)
            if expr.op == "+":
                return left + right
            if expr.op == "-":
                return left - right
            if expr.op == "*":
                return left * right
            if expr.op in ("/", "%"):
                if right == 0:
                    raise self.err(expr, "деление на ноль в константе")
                return left // right if expr.op == "/" else left % right
        raise self.err(
            expr, "ожидалась константа времени компиляции (правило 2)"
        )

    # --- функции -------------------------------------------------------------

    def check_func(
        self, func: ast.FuncDecl, key: str, self_type: StructType | None
    ) -> None:
        sig = (
            self.structs[self_type.name].methods[func.name]
            if self_type is not None
            else self.funcs[func.name]
        )
        self.current = sig
        self.current_key = key
        self.self_type = self_type if func.is_method else None
        self.push_scope()
        if self.self_type is not None:
            self.scopes[-1]["self"] = VarInfo(
                self.self_type, False, func.line, func.col
            )
        for pname, ptype in sig.params:
            pnode = next(p for p in func.params if p.name == pname)
            self.declare(
                pnode, pname, VarInfo(ptype, False, pnode.line, pnode.col)
            )
        if func.requires is not None:
            self._expect_bool(func.requires, "requires")
        if func.ensures is not None:
            self.result_type = sig.ret
            self._expect_bool(func.ensures, "ensures")
            self.result_type = None
        self.check_block(func.body, new_scope=False)
        if sig.ret is not None and not self._block_returns(func.body):
            raise self.err(
                func,
                f"функция {func.name}: не все пути возвращают значение",
            )
        self.pop_scope()
        self.current = None
        self.self_type = None

    def check_test(self, test: ast.TestBlock) -> None:
        self.current = FuncSig(f"test {test.name}", [], None)
        self.current_key = f"test:{test.name}"
        self.check_block(test.body)
        self.current = None

    # --- инструкции ----------------------------------------------------------

    def check_block(self, block: ast.Block, new_scope: bool = True) -> None:
        if new_scope:
            self.push_scope()
        finished = False
        for stmt in block.stmts:
            if finished:
                raise self.err(
                    stmt, "недостижимый код после return/break (правило 10)"
                )
            self.check_stmt(stmt)
            finished = self._stmt_returns(stmt) or isinstance(
                stmt, ast.BreakStmt
            )
        if new_scope:
            self.pop_scope()

    def check_stmt(self, stmt: ast.Stmt) -> None:
        if isinstance(stmt, ast.LetStmt):
            declared = self.resolve(stmt.type)
            stmt.var_ty = declared  # для кодогенерации
            actual = self.expr(stmt.value, expected=declared)
            self._require_compatible(stmt, declared, actual)
            self.declare(
                stmt,
                stmt.name,
                VarInfo(declared, stmt.mutable, stmt.line, stmt.col),
            )
            return
        if isinstance(stmt, ast.AssignStmt):
            self.check_assign(stmt)
            return
        if isinstance(stmt, ast.IfStmt):
            self._expect_bool(stmt.cond, "условие if")
            self.check_block(stmt.then)
            for cond, blk in stmt.elifs:
                self._expect_bool(cond, "условие elif")
                self.check_block(blk)
            if stmt.els is not None:
                self.check_block(stmt.els)
            return
        if isinstance(stmt, ast.ForStmt):
            self.check_for(stmt)
            return
        if isinstance(stmt, ast.LoopStmt):
            if self.current_key != "main":
                raise self.err(
                    stmt,
                    "loop допустим только в main (правило 2: всё "
                    "остальное имеет границу)",
                )
            self.loop_depth += 1
            self.check_block(stmt.body)
            self.loop_depth -= 1
            return
        if isinstance(stmt, ast.MatchStmt):
            self.check_match(stmt)
            return
        if isinstance(stmt, ast.ReturnStmt):
            self.check_return(stmt)
            return
        if isinstance(stmt, ast.BreakStmt):
            if self.loop_depth == 0:
                raise self.err(stmt, "break вне loop")
            return
        if isinstance(stmt, ast.AssertStmt):
            self._expect_bool(stmt.cond, "assert")
            return
        if isinstance(stmt, ast.ExprStmt):
            result = self.expr(stmt.expr, allow_void=True)
            if result is not VOID:
                raise self.err(
                    stmt,
                    f"результат типа {show(result)} отброшен молча; "
                    "используйте значение или discard (правило 7)",
                )
            return
        if isinstance(stmt, ast.DiscardStmt):
            result = self.expr(stmt.expr, allow_void=True)
            if result is VOID:
                raise self.err(
                    stmt, "discard бессмыслен: функция ничего не возвращает"
                )
            return
        raise self.err(stmt, "неизвестная инструкция")

    def check_assign(self, stmt: ast.AssignStmt) -> None:
        target_type = self.expr(stmt.target)
        base = stmt.target
        while isinstance(base, (ast.FieldAccess, ast.Index)):
            base = base.obj
        if isinstance(base, ast.SelfExpr):
            raise self.err(
                stmt, "self неизменяем: параметры передаются by-value"
            )
        if not isinstance(base, ast.Name):
            raise self.err(stmt, "некорректная цель присваивания")
        info = self.lookup(base, base.ident)
        if info is None:
            raise self.err(base, f"неизвестное имя {base.ident}")
        if not info.mutable:
            raise self.err(
                stmt,
                f"{base.ident} объявлена как let — неизменяема "
                "(мутабельность — это var, осознанно)",
            )
        value = self.expr(stmt.value, expected=target_type)
        self._require_compatible(stmt, target_type, value)

    def check_for(self, stmt: ast.ForStmt) -> None:
        if isinstance(stmt.iterable, ast.RangeExpr):
            start = self.const_eval(stmt.iterable.start)
            end = self.const_eval(stmt.iterable.end)
            if end < start:
                raise self.err(
                    stmt.iterable, f"пустой диапазон {start}..{end}"
                )
            elem: Type = U32 if start >= 0 else I32
            self._check_int_fits(stmt.iterable, elem, start)
            self._check_int_fits(stmt.iterable, elem, end)
            stmt.bounds = (start, end)  # для кодогенерации
        else:
            stmt.bounds = None
            itype = self.expr(stmt.iterable)
            if isinstance(itype, ArrayType):
                elem = itype.elem
            elif isinstance(itype, StrType):
                elem = CHAR
            else:
                raise self.err(
                    stmt.iterable,
                    f"итерация возможна по диапазону, массиву или строке, "
                    f"не по {show(itype)}",
                )
        stmt.elem_ty = elem  # для кодогенерации
        self.push_scope()
        if stmt.target != "_":
            self.declare(
                stmt, stmt.target, VarInfo(elem, False, stmt.line, stmt.col)
            )
        self.check_block(stmt.body, new_scope=False)
        self.pop_scope()

    def check_match(self, stmt: ast.MatchStmt) -> None:
        subject = self.expr(stmt.subject)
        if isinstance(subject, ResultType):
            expected = {"Ok": subject.ok, "Err": subject.err}
        elif isinstance(subject, OptionType):
            expected = {"Some": subject.inner, "None": None}
        elif isinstance(subject, EnumType):
            payloads = self.enum_payloads[subject.name]
            expected = {v: payloads[v] for v in self.enums[subject.name]}
        else:
            raise self.err(
                stmt.subject,
                f"match возможен по Result, Option или enum, "
                f"не по {show(subject)}",
            )
        seen = set()
        for arm in stmt.arms:
            if arm.pattern not in expected:
                raise self.err(
                    arm,
                    f"{arm.pattern} — не вариант типа {show(subject)}",
                )
            if arm.pattern in seen:
                raise self.err(arm, f"вариант {arm.pattern} повторяется")
            seen.add(arm.pattern)
            payload = expected[arm.pattern]
            arm.payload_ty = payload  # для кодогенерации
            if arm.binding is not None and payload is None:
                raise self.err(arm, f"вариант {arm.pattern} не несёт значения")
            self.push_scope()
            if payload is not None:
                if arm.binding is None:
                    raise self.err(
                        arm,
                        f"вариант {arm.pattern} несёт значение: назовите "
                        "его или используйте _",
                    )
                if arm.binding != "_":
                    self.declare(
                        arm,
                        arm.binding,
                        VarInfo(payload, False, arm.line, arm.col),
                    )
            self.check_block(arm.body, new_scope=False)
            self.pop_scope()
        missing = set(expected) - seen
        if missing:
            raise self.err(
                stmt,
                "match не исчерпывающий, пропущено: "
                f"{', '.join(sorted(missing))} (правило 7)",
            )

    def check_return(self, stmt: ast.ReturnStmt) -> None:
        assert self.current is not None
        ret = self.current.ret
        if ret is None:
            if stmt.value is not None:
                raise self.err(
                    stmt,
                    f"функция {self.current.name} ничего не возвращает",
                )
            return
        if stmt.value is None:
            raise self.err(
                stmt,
                f"функция {self.current.name} обязана вернуть {show(ret)}",
            )
        actual = self.expr(stmt.value, expected=ret)
        self._require_compatible(stmt, ret, actual)

    # --- анализ возвратов (недостижимый код — правило 10) --------------------

    def _stmt_returns(self, stmt: ast.Stmt) -> bool:
        if isinstance(stmt, ast.ReturnStmt):
            return True
        if isinstance(stmt, ast.IfStmt):
            if stmt.els is None:
                return False
            branches = [stmt.then, stmt.els] + [b for _, b in stmt.elifs]
            return all(self._block_returns(b) for b in branches)
        if isinstance(stmt, ast.MatchStmt):
            return all(self._block_returns(a.body) for a in stmt.arms)
        return False

    def _block_returns(self, block: ast.Block) -> bool:
        return any(self._stmt_returns(s) for s in block.stmts)

    # --- выражения -----------------------------------------------------------

    def expr(
        self,
        node: ast.Expr,
        expected: Type | None = None,
        allow_void: bool = False,
    ) -> Type:
        t = self._expr(node, expected)
        node.ty = t  # аннотация для кодогенерации
        if t is VOID and not allow_void:
            raise self.err(
                node, "функция ничего не возвращает — это не значение"
            )
        return t

    def _expr(self, node: ast.Expr, expected: Type | None) -> Type:
        if isinstance(node, ast.IntLit):
            t = expected if isinstance(expected, IntType) else I32
            self._check_int_fits(node, t, node.value)
            return t
        if isinstance(node, ast.BoolLit):
            return BOOL
        if isinstance(node, ast.CharLit):
            return CHAR
        if isinstance(node, ast.StrLit):
            return self._strlit(node)
        if isinstance(node, ast.SelfExpr):
            if self.self_type is None:
                raise self.err(node, "self доступен только в методе struct")
            info = self.lookup(node, "self")
            assert info is not None
            return info.type
        if isinstance(node, ast.Name):
            return self._name(node)
        if isinstance(node, ast.UnaryOp):
            return self._unary(node, expected)
        if isinstance(node, ast.BinOp):
            return self._binop(node, expected)
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.MethodCall):
            return self._method_call(node)
        if isinstance(node, ast.FieldAccess):
            return self._field_access(node)
        if isinstance(node, ast.Index):
            return self._index(node)
        if isinstance(node, ast.StructLit):
            return self._struct_lit(node)
        if isinstance(node, ast.ArrayLit):
            return self._array_lit(node, expected)
        if isinstance(node, ast.RangeExpr):
            raise self.err(node, "диапазон допустим только в for")
        raise self.err(node, "неизвестное выражение")

    def _strlit(self, node: ast.StrLit) -> Type:
        literal_only = True
        length = 0
        for seg in node.segments:
            if isinstance(seg, str):
                length += len(seg.encode("utf-8"))
                continue
            literal_only = False
            t = self.expr(seg)
            if not isinstance(t, _FORMATTABLE):
                raise self.err(
                    seg,
                    f"{show(t)} нельзя интерполировать в строку "
                    "(нет текстового представления)",
                )
        return StrType(length if literal_only else None)

    def _name(self, node: ast.Name) -> Type:
        if node.ident == "result" and self.result_type is not None:
            return self.result_type
        info = self.lookup(node, node.ident)
        if info is not None:
            return info.type
        if node.ident in self.consts:
            return self.consts[node.ident][0]
        if node.ident in self.funcs or node.ident in BUILTINS:
            raise self.err(
                node,
                f"{node.ident} — функция, а не значение (указателей на "
                "функции нет — правило 9)",
            )
        raise self.err(node, f"неизвестное имя {node.ident}")

    def _unary(self, node: ast.UnaryOp, expected: Type | None) -> Type:
        if node.op == "not":
            self._expect_bool(node.operand, "операнд not")
            return BOOL
        operand = self.expr(node.operand, expected=expected)
        if operand != I32:
            raise self.err(
                node, f"унарный минус применим к i32, не к {show(operand)}"
            )
        return I32

    def _binop(self, node: ast.BinOp, expected: Type | None) -> Type:
        op = node.op
        if op in ("and", "or"):
            self._expect_bool(node.left, f"операнд {op}")
            self._expect_bool(node.right, f"операнд {op}")
            return BOOL
        if op in ("+", "-", "*", "/", "%"):
            hint = expected if isinstance(expected, IntType) else None
            left = self.expr(node.left, expected=hint)
            right = self.expr(node.right, expected=left)
            self._require_same(node, left, right, op)
            if not isinstance(left, IntType):
                raise self.err(
                    node, f"арифметика применима к целым, не к {show(left)}"
                )
            return left
        # сравнения
        left = self.expr(node.left)
        right = self.expr(node.right, expected=left)
        self._require_same(node, left, right, op)
        if op in ("<", "<=", ">", ">="):
            if not isinstance(left, IntType):
                raise self.err(
                    node,
                    f"порядок определён для целых, не для {show(left)}",
                )
        else:  # == !=
            comparable = (
                IntType,
                BoolType,
                CharType,
                StrType,
                EnumType,
            )
            if not isinstance(left, comparable):
                raise self.err(node, f"== не определено для {show(left)}")
            if isinstance(left, EnumType) and any(
                self.enum_payloads[left.name].values()
            ):
                raise self.err(
                    node,
                    f"{op} не определено для enum с нагрузкой — "
                    "используйте match",
                )
        return BOOL

    def _require_same(
        self, node: ast.Node, left: Type, right: Type, op: str
    ) -> None:
        if not compatible(left, right):
            raise self.err(
                node,
                f"{op}: разные типы {show(left)} и {show(right)} "
                "(неявных преобразований нет)",
            )

    def _call(self, node: ast.Call) -> Type:
        if node.name in _INT_CASTS:
            return self._cast(node)
        if node.name == "char":
            return self._char_cast(node)
        if node.name == "len":
            return self._len(node)
        sig = BUILTINS.get(node.name) or self.funcs.get(node.name)
        if sig is None:
            raise self.err(node, f"неизвестная функция {node.name}")
        self._check_args(node, sig)
        if node.name in self.funcs:
            self.edges.add((self.current_key, node.name))
        return sig.ret if sig.ret is not None else VOID

    def _cast(self, node: ast.Call) -> Type:
        if len(node.args) != 1:
            raise self.err(node, f"{node.name}(): ровно один аргумент")
        source = self.expr(node.args[0])
        if isinstance(source, CharType):
            # char — ровно один байт: код символа читается только как u8
            if node.name != "u8":
                raise self.err(
                    node,
                    f"{node.name}() не применим к char — код символа "
                    "даёт u8(c), расширяйте дальше явно",
                )
            return U8
        if not isinstance(source, IntType):
            raise self.err(
                node,
                f"{node.name}() преобразует целые, не {show(source)}",
            )
        return _INT_CASTS[node.name]

    def _char_cast(self, node: ast.Call) -> Type:
        if len(node.args) != 1:
            raise self.err(node, "char(): ровно один аргумент")
        source = self.expr(node.args[0], expected=U8)
        if source != U8:
            raise self.err(
                node,
                f"char() принимает u8, не {show(source)} "
                "(сузьте явно через u8())",
            )
        return CHAR

    def _len(self, node: ast.Call) -> Type:
        if len(node.args) != 1:
            raise self.err(node, "len(): ровно один аргумент")
        source = self.expr(node.args[0])
        if not isinstance(source, (ArrayType, StrType)):
            raise self.err(
                node,
                f"len() применим к массиву или строке, не к {show(source)}",
            )
        return U32

    def _method_call(self, node: ast.MethodCall) -> Type:
        # Enum.Variant(x) — конструктор варианта с нагрузкой
        if isinstance(node.obj, ast.Name) and node.obj.ident in self.enums:
            return self._enum_ctor(node)
        obj = self.expr(node.obj)
        if not isinstance(obj, StructType):
            raise self.err(
                node, f"метод {node.name} вызван у {show(obj)}, а не struct"
            )
        info = self.structs[obj.name]
        sig = info.methods.get(node.name)
        if sig is None:
            raise self.err(node, f"у struct {obj.name} нет метода {node.name}")
        self._check_args(node, sig)
        node.struct = obj.name  # для кодогенерации
        self.edges.add((self.current_key, f"{obj.name}.{node.name}"))
        return sig.ret if sig.ret is not None else VOID

    def _enum_ctor(self, node: ast.MethodCall) -> Type:
        ename = node.obj.ident
        if node.name not in self.enums[ename]:
            raise self.err(node, f"у enum {ename} нет варианта {node.name}")
        payload = self.enum_payloads[ename][node.name]
        if payload is None:
            raise self.err(
                node,
                f"вариант {ename}.{node.name} не несёт значения — "
                "литерал пишется без скобок",
            )
        if len(node.args) != 1:
            raise self.err(
                node,
                f"{ename}.{node.name}: ровно один аргумент "
                "(несколько значений — заверните в struct)",
            )
        actual = self.expr(node.args[0], expected=payload)
        if not compatible(payload, actual):
            raise self.err(
                node.args[0],
                f"{ename}.{node.name} несёт {show(payload)}, "
                f"передан {show(actual)}",
            )
        node.enum_ctor = ename  # для кодогенерации
        return EnumType(ename)

    def _check_args(self, node, sig: FuncSig) -> None:
        if len(node.args) != len(sig.params):
            raise self.err(
                node,
                f"{sig.name}: ожидается {len(sig.params)} аргументов, "
                f"передано {len(node.args)}",
            )
        for arg, (pname, ptype) in zip(node.args, sig.params):
            actual = self.expr(arg, expected=ptype)
            if not compatible(ptype, actual):
                raise self.err(
                    arg,
                    f"{sig.name}: параметр {pname} имеет тип {show(ptype)}, "
                    f"передан {show(actual)}",
                )

    def _field_access(self, node: ast.FieldAccess) -> Type:
        # Enum.Variant — литерал варианта
        if isinstance(node.obj, ast.Name) and node.obj.ident in self.enums:
            enum_name = node.obj.ident
            if node.name not in self.enums[enum_name]:
                raise self.err(
                    node, f"у enum {enum_name} нет варианта {node.name}"
                )
            return EnumType(enum_name)
        obj = self.expr(node.obj)
        if not isinstance(obj, StructType):
            raise self.err(node, f"у {show(obj)} нет полей (это не struct)")
        fields = self.structs[obj.name].fields
        if node.name not in fields:
            raise self.err(node, f"у struct {obj.name} нет поля {node.name}")
        return fields[node.name]

    def _index(self, node: ast.Index) -> Type:
        obj = self.expr(node.obj)
        index = self.expr(node.index, expected=U32)
        if not isinstance(index, IntType):
            raise self.err(node, f"индекс — целое, не {show(index)}")
        if isinstance(obj, ArrayType):
            return obj.elem
        if isinstance(obj, StrType):
            return CHAR
        raise self.err(
            node,
            f"индексирование применимо к массиву или строке, не к {show(obj)}",
        )

    def _struct_lit(self, node: ast.StructLit) -> Type:
        if node.name not in self.structs:
            raise self.err(node, f"неизвестный struct {node.name}")
        info = self.structs[node.name]
        given = [name for name, _ in node.fields]
        if len(set(given)) != len(given):
            raise self.err(node, "поле повторяется в литерале")
        missing = set(info.fields) - set(given)
        extra = set(given) - set(info.fields)
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"не хватает: {', '.join(sorted(missing))}")
            if extra:
                parts.append(f"лишние: {', '.join(sorted(extra))}")
            raise self.err(node, f"литерал {node.name}: {'; '.join(parts)}")
        for fname, fexpr in node.fields:
            ftype = info.fields[fname]
            actual = self.expr(fexpr, expected=ftype)
            if not compatible(ftype, actual):
                raise self.err(
                    fexpr,
                    f"поле {fname}: ожидается {show(ftype)}, "
                    f"передан {show(actual)}",
                )
        return StructType(node.name)

    def _array_lit(self, node: ast.ArrayLit, expected: Type | None) -> Type:
        elem_hint = expected.elem if isinstance(expected, ArrayType) else None
        first = self.expr(node.elems[0], expected=elem_hint)
        for e in node.elems[1:]:
            t = self.expr(e, expected=first)
            if not compatible(first, t):
                raise self.err(
                    e,
                    f"элементы массива разных типов: {show(first)} "
                    f"и {show(t)}",
                )
        if isinstance(expected, ArrayType):
            if expected.size != len(node.elems):
                raise self.err(
                    node,
                    f"массив из {len(node.elems)} элементов, а тип "
                    f"требует {expected.size}",
                )
        return ArrayType(first, len(node.elems))

    # --- вспомогательное -----------------------------------------------------

    def _expect_bool(self, expr: ast.Expr, what: str) -> None:
        t = self.expr(expr, expected=BOOL)
        if t != BOOL:
            raise self.err(expr, f"{what}: ожидается bool, найден {show(t)}")

    def _require_compatible(
        self, node: ast.Node, expected: Type, actual: Type
    ) -> None:
        if not compatible(expected, actual):
            raise self.err(
                node,
                f"ожидается {show(expected)}, получен {show(actual)} "
                "(неявных преобразований нет)",
            )

    def _check_int_fits(self, node: ast.Node, t: Type, value: int) -> None:
        if not isinstance(t, IntType):
            return
        lo, hi = INT_RANGES[t.kind]
        if not lo <= value <= hi:
            raise self.err(
                node, f"{value} не помещается в {t.kind} [{lo}, {hi}]"
            )

    # --- правило 1: DAG вызовов и глубина стека ------------------------------

    def check_call_graph(self) -> int:
        graph: dict[str, set] = {}
        for caller, callee in self.edges:
            graph.setdefault(caller, set()).add(callee)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {}
        depth: dict[str, int] = {}

        def visit(name: str, chain: list) -> int:
            state = color.get(name, WHITE)
            if state == GRAY:
                cycle = chain[chain.index(name) :] + [name]
                func = self.funcs.get(name)
                node = func.node if func and func.node else self.program
                raise self.err(
                    node,
                    "рекурсия запрещена (правило 1): цикл вызовов "
                    + " -> ".join(cycle),
                )
            if state == BLACK:
                return depth[name]
            color[name] = GRAY
            chain.append(name)
            best = 0
            for callee in graph.get(name, ()):
                best = max(best, visit(callee, chain))
            chain.pop()
            color[name] = BLACK
            depth[name] = best + 1
            return depth[name]

        for root in list(graph) + list(self.funcs):
            visit(root, [])
        return depth.get("main", 1)


def typecheck(program: ast.Program, filename: str) -> CheckResult:
    return TypeChecker(program, filename).run()
