"""Comptime-вычисление тотальных функций на компиляции (§5, ярус A).

Тотальность языка (Power of 10: граф вызовов — DAG, границы циклов
статичны) делает вычисление любого вызова с константными аргументами
разрешимым — не эвристика с лимитом, как `constexpr` в Turing-полном
C++, а прямое следствие дизайна. Функция **comptime-годна** ⇔
транзитивно не трогает аксиомы ОС и `extern` (нечистые); trap внутри
вычисления — годен: это ошибка компиляции, а не отказ (§1).

Вычислитель — интерпретатор-эталон ([interpreter.py]) в режиме бюджета
шагов (`step_budget`): переиспользование даёт точную семантику
(trap-тексты, переполнения, касты) бесплатно. trap → ошибка
компиляции с координатами вызова; исчерпание бюджета → ошибка класса
«предел превышен» (SPEC §6).

Паритет ([MODIFYING.md]): этот модуль — эталон; зеркало —
selfhost/Eval.eat. Определение «шага» (один eval/exec_stmt) фиксировано
в SPEC §6 и обязано совпадать байт-в-байт.
"""

from . import ast_nodes as ast
from .errors import EatError
from .interpreter import ComptimeBudget, ComptimeDepth, Interpreter, Trap
from .limits import MAX_COMPTIME_CALL_DEPTH, MAX_COMPTIME_STEPS
from .types import INT_RANGES, ArrayType, BoolType, IntType

# Нечистые встроенные: аксиомы ОС и обёртки вывода. Функция,
# достигающая любой из них по графу вызовов, не comptime-годна.
IMPURE_BUILTINS = frozenset({
    "read_byte", "write_byte", "write_span", "write_err_byte", "exit",
    "arg_count", "arg_len", "arg_byte", "print", "write",
})


def _callee_map(checker) -> dict:
    """caller-key -> множество callee-ключей ПОЛЬЗОВАТЕЛЬСКИХ функций/
    методов из графа вызовов тайпчекера (`checker.edges` — тот же
    источник, что для DAG-проверки правила 1). Рёбра к встроенным
    тайпчекер не пишет (edges только для self.funcs), поэтому нечистоту
    встроенных ловит отдельный обход тела (`_direct_impure`)."""
    graph: dict = {}
    for caller, callee in checker.edges:
        graph.setdefault(caller, set()).add(callee)
    return graph


def _decl_map(program: ast.Program) -> dict:
    """key -> FuncDecl для функций и методов (как _func_by_key
    верификатора): "f" для функции, "S.m" для метода."""
    out: dict = {}
    for decl in program.decls:
        if isinstance(decl, ast.FuncDecl):
            out.setdefault(decl.name, decl)
        elif isinstance(decl, ast.StructDecl):
            for m in decl.methods:
                out.setdefault(f"{decl.name}.{m.name}", decl)
    # методам нужен сам метод, не struct — второй проход по методам
    for decl in program.decls:
        if isinstance(decl, ast.StructDecl):
            for m in decl.methods:
                out[f"{decl.name}.{m.name}"] = m
    return out


def _call_names(node, out: set) -> None:
    """Имена всех Call-вызовов в поддереве (для поиска нечистых
    встроенных: MethodCall — только пользовательские методы, их ловит
    edges; прямой вызов встроенного — это Call с именем-аксиомой)."""
    if node is None:
        return
    if isinstance(node, ast.Call):
        out.add(node.name)
    for attr in ("body", "then", "els", "value", "cond", "subject",
                 "operand", "left", "right", "obj", "index", "start",
                 "end", "iterable", "expr", "target"):
        child = getattr(node, attr, None)
        if isinstance(child, list):
            for c in child:
                _call_names(c, out)
        elif child is not None and not isinstance(child, (str, int, bool)):
            _call_names(child, out)
    for lst in ("stmts", "args", "elems", "elifs", "arms", "segments",
                "params"):
        seq = getattr(node, lst, None)
        if isinstance(seq, list):
            for c in seq:
                if isinstance(c, tuple):
                    for x in c:
                        _call_names(x, out)
                else:
                    _call_names(c, out)


def _direct_impure(decl) -> bool:
    """Тело функции напрямую вызывает нечистый встроенный?"""
    names: set = set()
    _call_names(getattr(decl, "body", None), names)
    return bool(names & IMPURE_BUILTINS)


def _is_extern(checker, key: str) -> bool:
    sig = checker.funcs.get(key)
    node = getattr(sig, "node", None) if sig is not None else None
    return bool(node is not None and getattr(node, "is_extern", False))


# Подмножество яруса A (§9.3 COMPTIME_PLAN): инструкции, выражения и
# виды типов, которые вычислитель selfhost (зеркало) обязан
# поддерживать. A1 — скаляры; A2 добавляет одномерные массивы скаляров
# (`[скаляр; N]`): индексация, array-литералы, array-fill. Всё вне
# множества (char/str/self/struct/enum/match/loop/2D-массивы …) — не
# годно в ярусе A.
_SCALAR_STMTS = (
    ast.Block, ast.LetStmt, ast.AssignStmt, ast.IfStmt, ast.ForStmt,
    ast.ReturnStmt, ast.BreakStmt, ast.AssertStmt, ast.ExprStmt,
    ast.DiscardStmt,
)
_SCALAR_EXPRS = (
    ast.IntLit, ast.BoolLit, ast.Name, ast.BinOp, ast.UnaryOp,
    ast.Call, ast.RangeExpr, ast.Index, ast.ArrayLit, ast.ArrayFill,
)
_SCALAR_TYPE_NAMES = frozenset(INT_RANGES) | {"bool"}


def _a2_type_ok(t) -> bool:
    """Тип годен для яруса A: скаляр (A1) или одномерный массив
    скаляров `[скаляр; N]` (A2). Вложенные массивы — вне A2."""
    if isinstance(t, (IntType, BoolType)):
        return True
    if isinstance(t, ArrayType):
        return isinstance(t.elem, (IntType, BoolType))
    return False


def _scalar_walk(node, bad: list) -> None:
    """Обход поддерева: любой узел вне подмножества яруса A — в bad.
    Узлы типов: TypeName со скалярным именем ок; ArrayType с
    одномерным скалярным элементом ок (A2)."""
    if node is None or bad:
        return
    if isinstance(node, ast.TypeName):
        if node.name not in _SCALAR_TYPE_NAMES:
            bad.append(node)
        return
    if isinstance(node, ast.ArrayType):
        # A2: [скаляр; N] — элемент скалярный, размер — const-выражение;
        # вложенные массивы (2D) вне яруса A
        if not (isinstance(node.elem, ast.TypeName)
                and node.elem.name in _SCALAR_TYPE_NAMES):
            bad.append(node)
        return
    if isinstance(node, (_SCALAR_STMTS + _SCALAR_EXPRS)):
        if isinstance(node, ast.Call) and (
            getattr(node, "ctor", None) or node.name in ("char", "len")
        ):
            bad.append(node)  # Ok/Err/Some/char()/len() — вне яруса A
            return
    else:
        bad.append(node)
        return
    for attr in ("body", "then", "els", "value", "cond", "operand",
                 "left", "right", "start", "end", "iterable", "expr",
                 "target", "type", "obj", "index", "count"):
        child = getattr(node, attr, None)
        if child is not None and not isinstance(child, (str, int, bool)):
            _scalar_walk(child, bad)
    for lst in ("stmts", "args", "elifs", "elems"):
        seq = getattr(node, lst, None)
        if isinstance(seq, list):
            for c in seq:
                if isinstance(c, tuple):
                    for x in c:
                        _scalar_walk(x, bad)
                else:
                    _scalar_walk(c, bad)


def _scalar_ok(decl, sig) -> bool:
    """Функция в подмножестве яруса A: сигнатура int/bool/[скаляр; N],
    тело/requires/ensures без конструкций вне подмножества."""
    for _, t in sig.params:
        if not _a2_type_ok(t):
            return False
    if sig.ret is not None and not _a2_type_ok(sig.ret):
        return False
    bad: list = []
    _scalar_walk(getattr(decl, "body", None), bad)
    _scalar_walk(getattr(decl, "requires", None), bad)
    _scalar_walk(getattr(decl, "ensures", None), bad)
    return not bad


def _subgraph_flags(key, checker, graph, decls, seen, flags) -> None:
    """Обойти ВЕСЬ подграф вызовов и агрегировать причины негодности в
    flags = [impure, nonscalar]. Без раннего выхода: причина — свойство
    подграфа с приоритетом impure > nonscalar, а не порядка обхода
    (DFS по set был бы недетерминирован). Граф — DAG (правило 1)."""
    if key in IMPURE_BUILTINS:
        flags[0] = True
        return
    if _is_extern(checker, key):
        flags[0] = True
        return
    if key in seen:
        return
    seen.add(key)
    decl = decls.get(key)
    if decl is not None:
        if _direct_impure(decl):
            flags[0] = True
        sig = checker.funcs.get(key)
        if sig is None or not _scalar_ok(decl, sig):
            flags[1] = True  # метод (S.m) — тоже вне A1
    for callee in graph.get(key, ()):
        _subgraph_flags(callee, checker, graph, decls, seen, flags)


def ineligible_reason(key, checker, graph, decls, _seen=None):
    """None — годна; 'impure' — транзитивно аксиома ОС/extern;
    'nonscalar' — тело/сигнатура вне скалярного подмножества A1.
    Приоритет причин: impure > nonscalar (детерминирован независимо
    от порядка обхода)."""
    flags = [False, False]
    _subgraph_flags(
        key, checker, graph, decls,
        _seen if _seen is not None else set(), flags,
    )
    if flags[0]:
        return "impure"
    if flags[1]:
        return "nonscalar"
    return None


def eligible(key, checker, graph, decls, _seen=None) -> bool:
    return ineligible_reason(key, checker, graph, decls, _seen) is None


class Comptime:
    """Обёртка вычислителя над одним интерпретатором программы.
    Держит интерпретатор и предвычисленный граф вызовов; вход
    `call` изолирует бюджет и переводит trap/бюджет в ошибку
    компиляции."""

    def __init__(self, program: ast.Program, checker, filename: str):
        self.checker = checker
        self.filename = filename
        self.graph = _callee_map(checker)
        self.decls = _decl_map(program)
        self.interp = Interpreter(program, filename)
        self._elig_cache: dict = {}
        self._fold_hits = 0

    def is_eligible(self, key: str) -> bool:
        return eligible(key, self.checker, self.graph, self.decls, set())

    def reason(self, key: str):
        return ineligible_reason(
            key, self.checker, self.graph, self.decls, set()
        )

    def eval_const(self, decl, site):
        """Вычислить отложенную comptime-константу через интерпретатор
        (ленивое разрешение _const_pending: бюджет + запрет аксиом внутри
        _comptime_call). trap/бюджет → ошибка компиляции с координатами
        объявления."""
        interp = self.interp
        try:
            if decl.name in interp._const_pending:
                interp._resolve_pending_const(decl.name)
            slot = interp.consts.get(decl.name)
            return slot.value if slot is not None else None
        except ComptimeBudget:
            raise EatError(
                getattr(site, "src_file", None) or self.filename,
                site.line, site.col,
                "comptime: превышен предел шагов "
                f"(предел {MAX_COMPTIME_STEPS})",
            )
        except ComptimeDepth:
            raise EatError(
                getattr(site, "src_file", None) or self.filename,
                site.line, site.col,
                "comptime: превышена глубина вызовов "
                f"(предел {MAX_COMPTIME_CALL_DEPTH})",
            )
        except Trap as trap:
            raise EatError(
                getattr(site, "src_file", None) or self.filename,
                site.line, site.col,
                f"comptime: {trap.message}",
            )

    def call(self, func: ast.FuncDecl, args: list, site: ast.Node):
        """Вычислить вызов чистой функции с константными аргументами.
        args — уже вычисленные значения (int/bool). Возвращает значение
        результата; trap/бюджет → EatError с координатами вызова."""
        interp = self.interp
        interp.frames = []
        interp.step_budget = MAX_COMPTIME_STEPS
        interp.steps = 0
        try:
            return interp.call_func(func, args, None, site)
        except ComptimeBudget:
            raise EatError(
                getattr(site, "src_file", None) or self.filename,
                site.line,
                site.col,
                "comptime: превышен предел шагов "
                f"(предел {MAX_COMPTIME_STEPS})",
            )
        except Trap as trap:
            # trap вычисления — ошибка компиляции с исходным текстом
            # (координаты — точки вызова, а не места trap'а: это её
            # ошибка компиляции)
            raise EatError(
                getattr(site, "src_file", None) or self.filename,
                site.line,
                site.col,
                f"comptime: {trap.message}",
            )
        finally:
            interp.step_budget = None

    # --- ярус B: свёртка вызовов в телах (build-путь, §11) ---------------

    def _elig(self, key: str) -> bool:
        """Кэшированная годность (fold дёргает по всем call-узлам)."""
        hit = self._elig_cache.get(key)
        if hit is None:
            hit = self.is_eligible(key)
            self._elig_cache[key] = hit
        return hit

    def _try_fold(self, func: ast.FuncDecl, values: list, site):
        """Вычислить вызов яруса B (аргументы — известные константы) в
        comptime-режиме (строгая по-операционная семантика, бюджет шагов,
        запрет аксиом). В отличие от яруса A trap/бюджет — НЕ ошибка: три
        исхода (§1) — вычислилось / trap / бюджет; последние два «не
        сворачивать» (вернуть None), рантайм-вызов остаётся и trap'нет
        там же с тем же текстом."""
        interp = self.interp
        interp.frames = []
        try:
            result = interp._comptime_call(func, values, site)
        except (Trap, ComptimeBudget, ComptimeDepth):
            return None
        if isinstance(result, bool):
            return 1 if result else 0
        if isinstance(result, int):
            return result
        return None  # не скаляр (массив/др.) — ярус B сворачивает скаляры

    def _const_of(self, node):
        """Значение выражения-аргумента, если оно compile-time константа
        яруса B: целый/bool литерал, скалярная const-имя или уже
        свёрнутый вызов (post-order). Иначе None. Ограничение v1:
        арифметика/касты как аргумент не считаются константой (их
        вычисление могло бы trap'нуть) — объявите промежуточный const."""
        if isinstance(node, ast.IntLit):
            return node.value
        if isinstance(node, ast.BoolLit):
            return 1 if node.value else 0
        if isinstance(node, ast.Name):
            slot = self.checker.consts.get(getattr(node, "ident", None))
            if slot is not None and isinstance(slot[1], (int, bool)):
                return int(slot[1])
            return None
        if isinstance(node, ast.Call) and getattr(node, "folded", False):
            return node.fold_value
        return None

    def _fold_node(self, node) -> None:
        """Post-order обход: сворачивает годные вызовы с константными
        аргументами в литерал (аннотация `folded`/`fold_value` на узле —
        читается кодогеном/верификатором, как флаги снятия проверок).
        Возврат не значение — константность аргументов берёт `_const_of`
        уже после свёртки детей."""
        if node is None or isinstance(node, (str, int, bool)):
            return
        if isinstance(node, ast.Call):
            for arg in node.args:
                self._fold_node(arg)
            ret = getattr(node, "ty", None)
            if (
                node.name in self.checker.funcs
                and not getattr(node, "ctor", None)
                and isinstance(ret, (IntType, BoolType))
                and self._elig(node.name)
            ):
                values = [self._const_of(a) for a in node.args]
                if all(v is not None for v in values):
                    func = self.decls.get(node.name)
                    if func is not None:
                        folded = self._try_fold(func, values, node)
                        if folded is not None:
                            node.folded = True
                            node.fold_value = folded
                            self._fold_hits += 1
            return
        for attr in ("body", "then", "els", "value", "cond", "subject",
                     "operand", "left", "right", "obj", "index", "start",
                     "end", "iterable", "expr", "target"):
            child = getattr(node, attr, None)
            if isinstance(child, list):
                for c in child:
                    self._fold_node(c)
            elif child is not None and not isinstance(child, (str, int, bool)):
                self._fold_node(child)
        for lst in ("stmts", "args", "elems", "elifs", "arms", "segments"):
            seq = getattr(node, lst, None)
            if isinstance(seq, list):
                for c in seq:
                    if isinstance(c, tuple):
                        for x in c:
                            self._fold_node(x)
                    else:
                        self._fold_node(c)

    def fold_bodies(self) -> int:
        """Свернуть годные вызовы во всех телах функций/методов. Возвращает
        число свёрнутых узлов (для отчёта build). Тела тестов не трогаем —
        кодоген их не эмитит; аксиомные вызовы отсеивает годность."""
        self._fold_hits = 0
        for decl in self.decls.values():
            self._fold_node(getattr(decl, "body", None))
        return self._fold_hits


def fold_calls(program: ast.Program, checker, filename: str) -> int:
    """Ярус B (§11): свёртка вызовов с константными аргументами в телах
    в литералы. Build-путь только (после типизации/3.5, перед verify —
    чтобы верификатор увидел точку [v,v]); в `eatc ir` не вызывается,
    поэтому канон IR и паритет selfhost неизменны. Возвращает число
    свёрнутых вызовов."""
    return Comptime(program, checker, filename).fold_bodies()
