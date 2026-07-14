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
from .interpreter import ComptimeBudget, Interpreter, Trap
from .limits import MAX_COMPTIME_STEPS

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


def eligible(key, checker, graph, decls, _seen=None) -> bool:
    """comptime-годность функции по ключу: транзитивно не достигает
    нечистого встроенного (обход тела) и не extern (обход графа —
    DAG правила 1, завершается; _seen отсекает общие подграфы).
    graph — _callee_map, decls — _decl_map."""
    if key in IMPURE_BUILTINS:
        return False
    if _is_extern(checker, key):
        return False
    seen = _seen if _seen is not None else set()
    if key in seen:
        return True
    seen.add(key)
    decl = decls.get(key)
    if decl is not None and _direct_impure(decl):
        return False
    for callee in graph.get(key, ()):
        if not eligible(callee, checker, graph, decls, seen):
            return False
    return True


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

    def is_eligible(self, key: str) -> bool:
        return eligible(key, self.checker, self.graph, self.decls, set())

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
