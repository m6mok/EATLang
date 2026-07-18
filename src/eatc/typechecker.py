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
from .errors import CapacityError, EatError
from .limits import (
    MAX_ARRAY_ELEMS,
    MAX_IMPORT_BINDS,
    MAX_MODULE_PATH,
    MAX_MODULES,
    MAX_STR_CAPACITY,
)
from .types import (
    BOOL,
    CHAR,
    I32,
    I64,
    INT_RANGES,
    U8,
    U16,
    U32,
    U64,
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


class _Deferred(Exception):
    """constexpr_eval встретил вызов или ещё не вычисленную comptime-
    константу (§5). В constexpr-декларации — сигнал отложить до фазы 3.5;
    в размере/границе массива — ловится и переводится в ошибку (ярус A
    разрешает вызовы только в constexpr-декларациях)."""


_INT_CASTS = {
    "i32": I32,
    "u32": U32,
    "u16": U16,
    "u8": U8,
    "u64": U64,
    "i64": I64,
}

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
    var_self: bool = False  # метод с let self — мутирует получателя


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
    "write": FuncSig("write", [("s", StrType(None))], None),
    # read_line/parse_i32 — библиотечные (lib/Io.eat, lib/Parse.eat,
    # этап 2 модулей); в ядре — только аксиома read_byte
    "read_byte": FuncSig(
        "read_byte", [], ResultType(U8, EnumType("IoError"))
    ),
    "write_byte": FuncSig("write_byte", [("b", U8)], None),
    # сигнатура-заглушка для правила 6: настоящая проверка — _write_span
    # (размер массива — свободный параметр, как у len)
    "write_span": FuncSig(
        "write_span",
        [("a", ArrayType(U8, 0)), ("off", U32), ("len", U32)],
        None,
    ),
    "write_err_byte": FuncSig("write_err_byte", [("b", U8)], None),
    "exit": FuncSig("exit", [("code", U32)], None),
    # аргументы командной строки (argv без имени программы): байтовые
    # аксиомы, layout-agnostic (шим отдаёт байты, str собирает lib/Args).
    # arg_len/arg_byte — trap при выходе за границы (как индекс массива)
    "arg_count": FuncSig("arg_count", [], U32),
    "arg_len": FuncSig("arg_len", [("i", U32)], U32),
    "arg_byte": FuncSig("arg_byte", [("i", U32), ("j", U32)], U8),
    # кооперативная асинхронность (ASYNC_PLAN, ярус 0): неблокирующий
    # опрос stdin и монотонные миллисекунды — аксиомы без trap-границ
    # (аргументов нет, результат — полный диапазон типа)
    "in_avail": FuncSig("in_avail", [], U32),
    "ticks": FuncSig("ticks", [], U64),
    # сокеты (HTTP_PLAN §5, решение H1): «данных нет» — socket_avail /
    # сентинел NO_CONN у accept, встроенный IoError не расширяется;
    # socket_write_span — спецпуть _socket_write_span (свободный размер
    # массива, как write_span)
    "socket_listen": FuncSig(
        "socket_listen", [("port", U16)], ResultType(U32, EnumType("IoError"))
    ),
    "socket_accept": FuncSig("socket_accept", [("fd", U32)], U32),
    "socket_avail": FuncSig("socket_avail", [("fd", U32)], U32),
    "socket_read_byte": FuncSig(
        "socket_read_byte", [("fd", U32)], ResultType(U8, EnumType("IoError"))
    ),
    "socket_close": FuncSig("socket_close", [("fd", U32)], None),
}

_FORMATTABLE = (IntType, BoolType, CharType, StrType)


def _is_exit_stmt(stmt) -> bool:
    """call-statement exit(...): управление не возвращается (правило 10)."""
    return (
        isinstance(stmt, ast.ExprStmt)
        and isinstance(stmt.expr, ast.Call)
        and stmt.expr.name == "exit"
    )


class TypeChecker:
    def __init__(self, program: ast.Program, filename: str):
        self.program = program
        self.filename = filename
        self.constexprs: dict[str, tuple] = {}  # имя -> (Type, int|None)
        # comptime-константы (§5, ярус A): значение через вызов —
        # вычисляется в фазе 3.5 (после типизации всех тел). До того в
        # self.constexprs лежит (Type, None) — использование в размере/границе
        # массива (constexpr_eval вне constexpr-декларации) даёт _Deferred → ошибка.
        self._deferred_constexprs: list = []
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
        self.break_counts: list[int] = []  # break'ов у каждого активного цикла
        self.exit_seen = False  # exit: не более одного на программу
        self.edges: set = set()
        # --- модули (docs/MODULES_PLAN.md §3): границы — ModuleMark ------
        # id 0 — безымянный сегмент до первой директивы (Rt, склейка cat):
        # его имена видимы всем; id 1.. — именованные модули
        self.module_paths: list[str] = []
        self.module_of_path: dict[str, int] = {}
        self.decl_module: dict[int, int] = {}  # id(узла) -> модуль
        self.exports: dict[int, dict] = {}  # модуль -> {публичное: внутр.}
        self.imports: dict[tuple, str] = {}  # (модуль, локальное) -> внутр.
        self.import_bind: dict[tuple, ast.Bind] = {}
        self.import_used: dict[tuple, bool] = {}
        self.name_module: dict[str, int] = {}  # внутр. имя -> владелец
        self.current_module = 0

    # --- инфраструктура -------------------------------------------------

    def err(self, node: ast.Node, message: str) -> EatError:
        fname = getattr(node, "src_file", None) or self.filename
        return EatError(fname, node.line, node.col, message)

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
        if name in self.constexprs or name in self.funcs or name in BUILTINS:
            raise self.err(
                node,
                f"имя {name} затеняет объявление верхнего уровня (правило 6)",
            )
        if (self.current_module, name) in self.imports:
            raise self.err(
                node,
                f"имя {name} затеняет импортированное имя (правило 6)",
            )
        self.scopes[-1][name] = info

    def lookup(self, node: ast.Node, name: str) -> VarInfo | None:
        for scope in reversed(self.scopes):
            if name in scope:
                scope[name].used = True
                return scope[name]
        return None

    def _is_local(self, name: str) -> bool:
        return any(name in scope for scope in self.scopes)

    # --- модули (docs/MODULES_PLAN.md §3) --------------------------------

    def collect_modules(self) -> None:
        """Один проход по потоку: границы модулей, export- и
        import-блоки. Порядок enforce'ит сам проход: import находит
        источник, только если тот уже встретился («модуль раньше по
        потоку» — компилятор перепроверяет драйвер)."""
        cur = 0
        for decl in self.program.decls:
            self.decl_module[id(decl)] = cur
            if isinstance(decl, ast.ModuleMark):
                if decl.path in self.module_of_path:
                    raise self.err(decl, f"модуль {decl.path} в потоке дважды")
                if len(decl.path.encode("utf-8")) > MAX_MODULE_PATH:
                    raise CapacityError(
                        self.filename, decl.line, decl.col,
                        "длина пути модуля", MAX_MODULE_PATH,
                    )
                if len(self.module_paths) >= MAX_MODULES:
                    raise CapacityError(
                        self.filename, decl.line, decl.col,
                        "модулей в программе", MAX_MODULES,
                    )
                self.module_paths.append(decl.path)
                cur = len(self.module_paths)
                self.module_of_path[decl.path] = cur
                self.decl_module[id(decl)] = cur
            elif isinstance(decl, ast.ExportBlock):
                self._stamp_module(decl, cur)
                # в безымянном сегменте (склейка cat) export инертен:
                # интерфейс закрепляет драйвер, ставя #module
                if cur == 0:
                    continue
                binds: dict[str, str] = {}
                for b in decl.binds:
                    pub = b.alias or b.name
                    if pub in binds:
                        raise self.err(
                            b, f"имя {pub} экспортируется дважды"
                        )
                    binds[pub] = b.name
                self.exports[cur] = binds
            elif isinstance(decl, ast.ImportBlock):
                self._stamp_module(decl, cur)
                self._collect_import(decl, cur)
            else:
                self._stamp_module(decl, cur)

    def _collect_import(self, decl: ast.ImportBlock, cur: int) -> None:
        src = self.module_of_path.get(decl.path)
        if src is None:
            raise self.err(
                decl,
                f'import из "{decl.path}": модуль не встретился раньше '
                "по потоку (порядок и пути собирает драйвер — "
                "docs/MODULES_PLAN.md §4)",
            )
        exported = self.exports.get(src, {})
        for b in decl.binds:
            local = b.alias or b.name
            key = (cur, local)
            if key in self.imports:
                raise self.err(
                    b,
                    f"имя {local} уже импортировано — коллизия лечится as",
                )
            if len(self.imports) >= MAX_IMPORT_BINDS:
                raise CapacityError(
                    self.filename, b.line, b.col,
                    "импортированных имён", MAX_IMPORT_BINDS,
                )
            if b.name not in exported:
                raise self.err(
                    b, f"модуль {decl.path} не экспортирует {b.name}"
                )
            self.imports[key] = exported[b.name]
            self.import_bind[key] = b
            self.import_used[key] = False

    def _stamp_module(self, obj, cur: int) -> None:
        """Атрибуция ошибок и trap-сообщений: узлы именованного модуля
        получают его канонический путь как src_file (координаты уже
        пофайловые — лексер сбросил счёт на директиве)."""
        if cur == 0:
            return
        path = self.module_paths[cur - 1]
        from dataclasses import fields as dc_fields

        def stamp(node):
            if isinstance(node, ast.Node):
                if getattr(node, "src_file", None) is None:
                    node.src_file = path
                for f in dc_fields(node):
                    stamp(getattr(node, f.name))
            elif isinstance(node, (list, tuple)):
                for item in node:
                    stamp(item)

        stamp(obj)

    def check_module_interfaces(self) -> None:
        """Проверки экспорта после сбора деклараций: имя существует и
        принадлежит модулю; типы и контракты интерфейса замкнуты (§3)."""
        for mod, binds in self.exports.items():
            for pub, internal in binds.items():
                owner = self.name_module.get(internal)
                node = self._export_bind_node(mod, pub)
                if owner is None or owner != mod:
                    raise self.err(
                        node,
                        f"export {internal}: в модуле "
                        f"{self.module_paths[mod - 1]} нет такого "
                        "объявления (func/struct/enum/constexpr)",
                    )
                self._check_export_closure(mod, internal, node)
        for key in list(self.imports):
            mod, local = key
            b = self.import_bind[key]
            owner = self.name_module.get(local)
            if owner is not None and owner in (0, mod):
                raise self.err(
                    b,
                    f"импортированное имя {local} совпадает с объявлением — "
                    "коллизия лечится as",
                )
            if (
                local in BUILTINS
                or local in _INT_CASTS
                or local in ("len", "str", "char", "Result", "Option", "bool")
                or local in ("Ok", "Err", "Some", "None")
            ):
                raise self.err(
                    b, f"импортированное имя {local} затеняет встроенное"
                )

    def _export_bind_node(self, mod: int, pub: str) -> ast.Node:
        for decl in self.program.decls:
            if (
                isinstance(decl, ast.ExportBlock)
                and self.decl_module.get(id(decl)) == mod
            ):
                for b in decl.binds:
                    if (b.alias or b.name) == pub:
                        return b
        return self.program

    def _check_export_closure(
        self, mod: int, internal: str, node: ast.Node
    ) -> None:
        """Тип из сигнатуры/контракта экспортированной единицы обязан
        быть экспортирован сам — иначе клиент не может ни объявить
        значение, ни проверить requires (§3.4)."""
        exported = set(self.exports[mod].values())

        def check_type(t, what):
            for name in self._type_names(t):
                if (
                    self.name_module.get(name) == mod
                    and name not in exported
                ):
                    raise self.err(
                        node,
                        f"тип {name} в интерфейсе экспортированного "
                        f"{what} не экспортирован модулем",
                    )

        def check_contract(expr, what):
            if expr is None:
                return
            for name in self._expr_global_names(expr):
                if (
                    self.name_module.get(name) == mod
                    and name not in exported
                ):
                    raise self.err(
                        node,
                        f"{name} в контракте экспортированного {what} "
                        "не экспортирован модулем",
                    )

        def check_sig(sig, what):
            for _, t in sig.params:
                check_type(t, what)
            if sig.ret is not None:
                check_type(sig.ret, what)
            if sig.node is not None:
                check_contract(sig.node.requires, what)
                check_contract(sig.node.ensures, what)

        if internal in self.funcs:
            check_sig(self.funcs[internal], internal)
        elif internal in self.structs:
            info = self.structs[internal]
            for t in info.fields.values():
                check_type(t, internal)
            for mname, sig in info.methods.items():
                check_sig(sig, f"{internal}.{mname}")
        elif internal in self.enum_payloads:
            for t in self.enum_payloads[internal].values():
                if t is not None:
                    check_type(t, internal)

    def _type_names(self, t):
        if isinstance(t, (StructType, EnumType)):
            yield t.name
        elif isinstance(t, ArrayType):
            yield from self._type_names(t.elem)
        elif isinstance(t, ResultType):
            yield from self._type_names(t.ok)
            yield from self._type_names(t.err)
        elif isinstance(t, OptionType):
            yield from self._type_names(t.inner)

    def _expr_global_names(self, expr):
        """Идентификаторы контракта, которые могут указывать на
        объявления верхнего уровня (параметры и result отфильтрует
        name_module у вызывающего)."""
        if isinstance(expr, ast.Name):
            yield expr.ident
        elif isinstance(expr, ast.Call):
            yield expr.name
            for a in expr.args:
                yield from self._expr_global_names(a)
        elif isinstance(expr, ast.MethodCall):
            yield from self._expr_global_names(expr.obj)
            for a in expr.args:
                yield from self._expr_global_names(a)
        elif isinstance(expr, ast.FieldAccess):
            yield from self._expr_global_names(expr.obj)
        elif isinstance(expr, ast.Index):
            yield from self._expr_global_names(expr.obj)
            yield from self._expr_global_names(expr.index)
        elif isinstance(expr, ast.BinOp):
            yield from self._expr_global_names(expr.left)
            yield from self._expr_global_names(expr.right)
        elif isinstance(expr, ast.UnaryOp):
            yield from self._expr_global_names(expr.operand)

    def vis_name(self, node: ast.Node, name: str) -> str:
        """Разрешение глобального имени из текущего модуля: локальное
        импортированное имя переводится во внутреннее имя экспортёра;
        чужие неимпортированные имена невидимы (§3). Неизвестные имена
        возвращаются как есть — «неизвестное имя» скажет вызывающий."""
        key = (self.current_module, name)
        target = self.imports.get(key)
        if target is not None:
            self.import_used[key] = True
            return target
        owner = self.name_module.get(name)
        if owner is None or owner in (0, self.current_module):
            return name
        raise self.err(
            node,
            f"имя {name} не импортировано (объявлено в модуле "
            f"{self.module_paths[owner - 1]})",
        )

    def _check_unused_imports(self) -> None:
        for key, used in self.import_used.items():
            if not used:
                b = self.import_bind[key]
                raise self.err(
                    b, f"импорт {key[1]} не используется (правило 10)"
                )

    # --- запуск ------------------------------------------------------------

    def run(self) -> CheckResult:
        self.collect_decls()
        self._check_type_cycles()
        self.check_module_interfaces()
        if "main" not in self.funcs:
            raise EatError(
                self.filename, 1, 1, "нет функции main — точки входа"
            )
        main = self.funcs["main"]
        if main.node is not None and main.node.is_extern:
            raise self.err(main.node, "main не может быть extern")
        if main.params or main.ret is not None:
            raise self.err(
                main.node,
                "main не принимает параметров и ничего не возвращает",
            )
        self.check_bodies()
        self._eval_deferred_constexprs()
        self._check_unused_imports()
        depth = self.check_call_graph()
        return CheckResult(
            stack_depth=depth,
            funcs=len(self.funcs),
            edges=self.edges,
            checker=self,
        )

    # --- сбор объявлений -----------------------------------------------------

    def collect_decls(self) -> None:
        self.collect_modules()
        # проход 1: имена типов
        for decl in self.program.decls:
            self.current_module = self.decl_module.get(id(decl), 0)
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
            self.current_module = self.decl_module.get(id(decl), 0)
            if isinstance(decl, ast.ConstexprDecl):
                self._declare_top(decl, decl.name)
                ctype = self.resolve(decl.type)
                try:
                    value = self.constexpr_eval(decl.value)
                except _Deferred:
                    # comptime-константа (§5): значение вычисляется в
                    # фазе 3.5, когда тела функций типизированы. Тип уже
                    # известен — выражения, читающие constexpr, типизируются.
                    self.constexprs[decl.name] = (ctype, None)
                    self._deferred_constexprs.append((decl, ctype))
                else:
                    self._check_int_fits(decl, ctype, value)
                    self.constexprs[decl.name] = (ctype, value)
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
            or name in self.constexprs
            or name in BUILTINS
            or name in _INT_CASTS
            or name in ("len", "str", "char", "Result", "Option")
            # конструкторы встроенных sum-типов (SPEC §5.3)
            or name in ("Ok", "Err", "Some", "None")
        )
        if taken:
            raise self.err(node, f"имя {name} уже занято")
        self.name_module[name] = self.current_module

    def _signature(self, func: ast.FuncDecl) -> FuncSig:
        params = []
        for p in func.params:
            if p.name != "self":
                params.append((p.name, self.resolve(p.type)))
        ret = self.resolve(func.ret) if func.ret is not None else None
        var_self = bool(
            func.params
            and func.params[0].name == "self"
            and func.params[0].mutable
        )
        return FuncSig(func.name, params, ret, func, var_self)

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
            # канонизация: импортированное имя типа -> внутреннее имя
            # экспортёра (дальше конвейер видит только внутренние имена)
            node.name = self.vis_name(node, node.name)
            if node.name in self.structs:
                return StructType(node.name)
            if node.name in self.enums:
                return EnumType(node.name)
            raise self.err(node, f"неизвестный тип {node.name}")
        if isinstance(node, ast.ArrayType):
            size = self._constexpr_size(node.size, "размер массива")
            if not 0 < size <= MAX_ARRAY_ELEMS:
                raise self.err(
                    node, f"размер массива {size} вне (0, {MAX_ARRAY_ELEMS}]"
                )
            return ArrayType(self.resolve(node.elem), size)
        if isinstance(node, ast.StrType):
            cap = self._constexpr_size(node.capacity, "ёмкость строки")
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

    def check_bodies(self) -> None:
        """Фаза 3b: типизация тел всех функций/методов/тестов.
        Вынесена из run(): sig-путь (dump_signatures) догоняет её при
        наличии comptime-констант — их значения печатаются в дампе и
        требуют типизированных тел (COMPTIME_PLAN §9.5)."""
        for decl in self.program.decls:
            self.current_module = self.decl_module.get(id(decl), 0)
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
        self.current_module = 0

    def _eval_deferred_constexprs(self) -> None:
        """Фаза 3.5 (§5, ярус A): вычислить comptime-константы после
        типизации всех тел (тела типизированы, граф вызовов построен).
        Годность — статически до любого вычисления (нечистые не
        исполняются); значения — интерпретатором-эталоном (единый
        вычислитель, зеркалится в selfhost/Eval.eat)."""
        if not self._deferred_constexprs:
            return
        from .comptime import Comptime, _call_names
        ct = Comptime(self.program, self, self.filename)
        for decl, _ctype in self._deferred_constexprs:
            names: set = set()
            _call_names(decl.value, names)
            for callee in sorted(names):
                reason = ct.reason(callee)
                if reason == "impure":
                    raise self.err(
                        decl,
                        f"{callee} не comptime-годна: транзитивно "
                        "вызывает аксиому ОС или extern (§5)",
                    )
                if reason == "nonscalar":
                    raise self.err(
                        decl,
                        f"{callee} не comptime-годна: тело вне "
                        "скалярного подмножества (ярус A)",
                    )
        for decl, ctype in self._deferred_constexprs:
            value = ct.eval_constexpr(decl, decl)
            self._check_constexpr_fits(decl, ctype, value)
            self.constexprs[decl.name] = (ctype, value)

    def _constexpr_size(self, expr: ast.Expr, what: str) -> int:
        """constexpr_eval в контексте размера/границы (не constexpr-декларация):
        вызов или невычисленная comptime-константа здесь — ошибка (ярус A
        разрешает comptime-вызовы только в constexpr-декларациях, §5)."""
        try:
            return self.constexpr_eval(expr)
        except _Deferred:
            raise self.err(
                expr,
                f"{what}: comptime-вызовы разрешены только в constexpr-"
                "декларациях (ярус A); объявите промежуточный constexpr",
            )

    def constexpr_eval(self, expr: ast.Expr) -> int:
        """Константное выражение (правило 2: границы известны до запуска)."""
        if isinstance(expr, ast.IntLit):
            return expr.value
        if isinstance(expr, ast.Name):
            if not self._is_local(expr.ident):
                expr.ident = self.vis_name(expr, expr.ident)
            if expr.ident in self.constexprs:
                value = self.constexprs[expr.ident][1]
                if value is None:
                    # comptime-константа ещё не вычислена (фаза 3.5):
                    # значит используется вне constexpr-декларации
                    raise _Deferred()
                return value
            raise self.err(
                expr,
                f"{expr.ident} — не константа времени компиляции (правило 2)",
            )
        if isinstance(expr, ast.UnaryOp) and expr.op == "-":
            return -self.constexpr_eval(expr.operand)
        if isinstance(expr, ast.BinOp):
            left = self.constexpr_eval(expr.left)
            right = self.constexpr_eval(expr.right)
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
        if isinstance(expr, (ast.Call, ast.MethodCall)):
            # comptime-вызов (§5): в constexpr-декларации — отложить до
            # фазы 3.5; в размере/границе массива — _Deferred поймается
            # и станет ошибкой (ярус A: вызовы только в constexpr)
            raise _Deferred()
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
                self.self_type, sig.var_self, func.line, func.col
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
        if func.is_extern:
            # тела нет: параметры «использует» C-реализация
            self._check_extern_boundary(func, sig)
            for info in self.scopes[-1].values():
                info.used = True
            self.pop_scope()
            self.current = None
            return
        self.check_block(func.body, new_scope=False)
        if sig.ret is not None and not self._block_returns(func.body):
            raise self.err(
                func,
                f"функция {func.name}: не все пути возвращают значение",
            )
        self.pop_scope()
        self.current = None
        self.self_type = None

    def _check_extern_boundary(self, func: ast.FuncDecl, sig) -> None:
        """Граница с C (SPEC §7): параметры — скаляры или массивы
        беззнаковых ([u8|u16|u32|u64; N], по указателю, read-only);
        возврат — только скаляр."""
        for pname, ptype in sig.params:
            ok = isinstance(ptype, (IntType, BoolType, CharType)) or (
                isinstance(ptype, ArrayType)
                and isinstance(ptype.elem, IntType)
                and ptype.elem.kind not in ("i32", "i64")
            )
            if not ok:
                raise self.err(
                    func,
                    f"extern {func.name}: параметр {pname} — на границе "
                    f"с C допустимы скаляры и [u8|u16|u32|u64; N], "
                    f"не {show(ptype)}",
                )
        if sig.ret is not None and not isinstance(
            sig.ret, (IntType, BoolType, CharType)
        ):
            raise self.err(
                func,
                f"extern {func.name}: возврат через границу с C — "
                f"только скаляр, не {show(sig.ret)}",
            )

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
            finished = (
                self._stmt_returns(stmt)
                or isinstance(stmt, ast.BreakStmt)
                or _is_exit_stmt(stmt)
            )
        if new_scope:
            self.pop_scope()

    def check_stmt(self, stmt: ast.Stmt) -> None:
        if isinstance(stmt, ast.LocalDecl):
            declared = self.resolve(stmt.type)
            stmt.local_ty = declared  # для кодогенерации
            actual = self.expr_ctor(stmt.value, declared)
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
            self.loop_depth += 1
            self.break_counts.append(0)
            self.check_for(stmt)
            self.break_counts.pop()
            self.loop_depth -= 1
            return
        if isinstance(stmt, ast.LoopStmt):
            if self.current_key != "main":
                raise self.err(
                    stmt,
                    "loop допустим только в main (правило 2: всё "
                    "остальное имеет границу)",
                )
            self.loop_depth += 1
            self.break_counts.append(0)
            self.check_block(stmt.body)
            self.break_counts.pop()
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
                raise self.err(stmt, "break вне цикла")
            # break привязан к внутреннему циклу — стиль MISRA:
            # не более одного раннего выхода на цикл
            self.break_counts[-1] += 1
            if self.break_counts[-1] > 1:
                raise self.err(
                    stmt, "не более одного break на цикл (правило 1)"
                )
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
            sinfo = self.lookup(base, "self")
            if sinfo is None or not sinfo.mutable:
                raise self.err(
                    stmt,
                    "self неизменяем: мутирующий метод объявляется "
                    "как func имя(let self, ...)",
                )
            value = self.expr(stmt.value, expected=target_type)
            self._require_compatible(stmt, target_type, value)
            return
        if not isinstance(base, ast.Name):
            raise self.err(stmt, "некорректная цель присваивания")
        info = self.lookup(base, base.ident)
        if info is None:
            raise self.err(base, f"неизвестное имя {base.ident}")
        if not info.mutable:
            raise self.err(
                stmt,
                f"{base.ident} объявлена как const — неизменяема "
                "(мутабельность — это let, осознанно)",
            )
        value = self.expr(stmt.value, expected=target_type)
        self._require_compatible(stmt, target_type, value)

    def check_for(self, stmt: ast.ForStmt) -> None:
        if isinstance(stmt.iterable, ast.RangeExpr):
            start = self._constexpr_size(stmt.iterable.start, "граница цикла")
            end = self._constexpr_size(stmt.iterable.end, "граница цикла")
            if end < start:
                raise self.err(
                    stmt.iterable, f"пустой диапазон {start}..{end}"
                )
            if start >= 0:
                elem = U32 if end <= 2**32 - 1 else U64
            else:
                lo32, hi32 = INT_RANGES["i32"]
                elem = I32 if start >= lo32 and end <= hi32 else I64
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
        actual = self.expr_ctor(stmt.value, ret)
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

    def expr_ctor(self, node: ast.Expr, expected: Type | None) -> Type:
        """Контекст конструкторов Ok/Err/Some/None (решение 2026-07-14):
        разрешены только там, где ожидаемый тип известен точно —
        выражение return, const с аннотацией и payload вложенного
        конструктора. Общего вывода типов нет."""
        if isinstance(node, ast.Call) and node.name in ("Ok", "Err", "Some"):
            return self._tagged_ctor(node, expected)
        if (
            isinstance(node, ast.Name)
            and node.ident == "None"
            and not self._is_local("None")
        ):
            if not isinstance(expected, OptionType):
                raise self.err(
                    node,
                    "None допустим только там, где ожидается Option: "
                    "в return и в const с аннотацией",
                )
            node.ctor = "None"
            node.ty = expected
            return expected
        return self.expr(node, expected=expected)

    def _tagged_ctor(self, node: ast.Call, expected: Type | None) -> Type:
        name = node.name
        if name == "Some":
            if not isinstance(expected, OptionType):
                raise self.err(
                    node,
                    "Some допустим только там, где ожидается Option: "
                    "в return и в const с аннотацией",
                )
            payload = expected.inner
        else:
            if not isinstance(expected, ResultType):
                raise self.err(
                    node,
                    f"{name} допустим только там, где ожидается Result: "
                    "в return и в const с аннотацией",
                )
            payload = expected.ok if name == "Ok" else expected.err
        if len(node.args) != 1:
            raise self.err(
                node,
                f"{name}: ровно один аргумент "
                "(несколько значений — заверните в struct)",
            )
        actual = self.expr_ctor(node.args[0], payload)
        if not compatible(payload, actual):
            raise self.err(
                node.args[0],
                f"{name} несёт {show(payload)}, передан {show(actual)}",
            )
        node.ctor = name  # для интерпретатора и кодогенерации
        node.ty = expected
        return expected

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
        if isinstance(node, ast.ArrayFill):
            return self._array_fill(node, expected)
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
        if node.ident == "None":
            raise self.err(
                node,
                "None допустим только там, где ожидается Option: "
                "в return и в const с аннотацией",
            )
        node.ident = self.vis_name(node, node.ident)
        if node.ident in self.constexprs:
            return self.constexprs[node.ident][0]
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
        if node.op == "~":
            # как у битовых бинарных: только беззнаковые (см. _binop)
            hint = expected if isinstance(expected, IntType) else None
            operand = self.expr(node.operand, expected=hint)
            if not isinstance(operand, IntType) or operand.kind in (
                "i32",
                "i64",
            ):
                raise self.err(
                    node,
                    f"~ применим к u64/u32/u16/u8, не к {show(operand)}",
                )
            return operand
        operand = self.expr(node.operand, expected=expected)
        if operand not in (I32, I64):
            raise self.err(
                node,
                f"унарный минус применим к i32/i64, не к {show(operand)}",
            )
        return operand

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
        if op in ("&", "|", "^", "<<", ">>"):
            hint = expected if isinstance(expected, IntType) else None
            left = self.expr(node.left, expected=hint)
            right = self.expr(node.right, expected=left)
            self._require_same(node, left, right, op)
            if not isinstance(left, IntType) or left.kind in ("i32", "i64"):
                # у знаковых смысл битовой операции зависел бы от
                # представления знака — только беззнаковые
                raise self.err(
                    node,
                    f"{op} применим к u64/u32/u16/u8, не к {show(left)}",
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
        node.name = self.vis_name(node, node.name)
        if node.name in _INT_CASTS:
            return self._cast(node)
        if node.name == "char":
            return self._char_cast(node)
        if node.name == "len":
            return self._len(node)
        if node.name == "write_span":
            return self._write_span(node)
        if node.name == "socket_write_span":
            return self._socket_write_span(node)
        if node.name == "exit":
            # завершение процесса: только из main (как loop) и один раз
            if self.current_key != "main":
                raise self.err(node, "exit допустим только в main")
            if self.exit_seen:
                raise self.err(
                    node, "exit допустим не более одного раза на программу"
                )
            self.exit_seen = True
        if node.name in ("Ok", "Err"):
            raise self.err(
                node,
                f"{node.name} допустим только там, где ожидается Result: "
                "в return и в const с аннотацией",
            )
        if node.name == "Some":
            raise self.err(
                node,
                "Some допустим только там, где ожидается Option: "
                "в return и в const с аннотацией",
            )
        if node.name == "None":
            raise self.err(
                node, "None не несёт значения — пишется без скобок"
            )
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

    def _write_span(self, node: ast.Call) -> Type:
        if len(node.args) != 3:
            raise self.err(node, "write_span(): ровно три аргумента")
        arr = self.expr(node.args[0])
        if not (isinstance(arr, ArrayType) and arr.elem == U8):
            raise self.err(
                node,
                "write_span() пишет из массива u8, "
                f"не из {show(arr)}",
            )
        for i in (1, 2):
            t = self.expr(node.args[i], expected=U32)
            if t != U32:
                raise self.err(
                    node,
                    f"write_span(): смещение и длина — u32, не {show(t)}",
                )
        node.arr_size = arr.size  # для кодогенерации: проверка границ
        return VOID

    def _socket_write_span(self, node: ast.Call) -> Type:
        """socket_write_span(fd, a, off, len) -> u32: батч-вывод в
        соединение (HTTP_PLAN §5); размер массива — свободный параметр,
        как у write_span; результат — сколько байт принято ядром."""
        if len(node.args) != 4:
            raise self.err(
                node, "socket_write_span(): ровно четыре аргумента"
            )
        t0 = self.expr(node.args[0], expected=U32)
        if t0 != U32:
            raise self.err(
                node,
                f"socket_write_span(): дескриптор — u32, не {show(t0)}",
            )
        arr = self.expr(node.args[1])
        if not (isinstance(arr, ArrayType) and arr.elem == U8):
            raise self.err(
                node,
                "socket_write_span() пишет из массива u8, "
                f"не из {show(arr)}",
            )
        for i in (2, 3):
            t = self.expr(node.args[i], expected=U32)
            if t != U32:
                raise self.err(
                    node,
                    "socket_write_span(): смещение и длина — u32, "
                    f"не {show(t)}",
                )
        node.arr_size = arr.size  # для кодогенерации: проверка границ
        return U32

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
        if isinstance(node.obj, ast.Name) and not self._is_local(
            node.obj.ident
        ):
            node.obj.ident = self.vis_name(node.obj, node.obj.ident)
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
        if sig.var_self:
            self._check_mutable_receiver(node)
        self._check_args(node, sig)
        node.struct = obj.name  # для кодогенерации
        self.edges.add((self.current_key, f"{obj.name}.{node.name}"))
        return sig.ret if sig.ret is not None else VOID

    def _check_mutable_receiver(self, node: ast.MethodCall) -> None:
        """Метод с let self мутирует получателя — получатель обязан
        быть изменяемым lvalue."""
        base = node.obj
        while isinstance(base, (ast.FieldAccess, ast.Index)):
            base = base.obj
        if isinstance(base, ast.SelfExpr):
            sinfo = self.lookup(base, "self")
            if sinfo is not None and sinfo.mutable:
                return
            raise self.err(
                node,
                f"{node.name}(let self) внутри немутирующего метода",
            )
        if isinstance(base, ast.Name):
            info = self.lookup(base, base.ident)
            if info is not None and info.mutable:
                return
            raise self.err(
                node,
                f"{node.name} объявлен с let self, а получатель "
                f"{base.ident} — const (неизменяем)",
            )
        raise self.err(
            node,
            f"{node.name} объявлен с let self: получатель обязан быть "
            "изменяемой переменной, а не временным значением",
        )

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
        if isinstance(node.obj, ast.Name) and not self._is_local(
            node.obj.ident
        ):
            node.obj.ident = self.vis_name(node.obj, node.obj.ident)
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
        node.name = self.vis_name(node, node.name)
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

    def _array_fill(self, node: ast.ArrayFill, expected: Type | None) -> Type:
        n = self._constexpr_size(node.count, "размер массива")
        if not 0 < n <= MAX_ARRAY_ELEMS:
            raise self.err(
                node, f"размер массива {n} вне (0, {MAX_ARRAY_ELEMS}]"
            )
        elem_hint = expected.elem if isinstance(expected, ArrayType) else None
        elem = self.expr(node.value, expected=elem_hint)
        if isinstance(expected, ArrayType) and expected.size != n:
            raise self.err(
                node,
                f"массив из {n} элементов, а тип требует {expected.size}",
            )
        node.size = n  # для интерпретатора и кодогенерации
        return ArrayType(elem, n)

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

    def _check_constexpr_fits(self, node: ast.Node, t: Type, value) -> None:
        """Проверка результата comptime-константы (§5, ярус A). Скаляр —
        как _check_int_fits; массив (A2) — форма и поэлементный фит.
        Вычислитель уже фитит каждую операцию к типу результата, но
        итоговый массив сверяется ещё раз (защита от рассинхрона)."""
        if isinstance(t, ArrayType):
            if not isinstance(value, list) or len(value) != t.size:
                raise self.err(
                    node, "результат comptime-константы не массив нужной "
                    f"длины {t.size}",
                )
            for elem in value:
                self._check_int_fits(node, t.elem, elem)
            return
        self._check_int_fits(node, t, value)

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
