"""Статическая верификация EATLang: интервальный + реляционный анализ.

Этап 2 контрактов из SPEC.md §5.2: то, что доказано на этапе
компиляции, удаляется из бинарника. Анализ консервативен: недоказанная
проверка остаётся runtime-trap'ом — ложных «доказательств» не бывает.

Что доказывается:
  - отсутствие переполнения (+ - * и унарный минус);
  - деление на ноль (и краевой случай INT_MIN / -1);
  - выход за границы массива;
  - допустимость сужающих преобразований i32()/u32()/u16()/u8();
  - requires на каждом месте вызова (снятие проверки — только если
    доказаны ВСЕ вызовы функции, либо requires — тавтология);
  - ensures на каждом return;
  - assert.

Три механизма, работающих вместе:
  1. Интервалы: путь (имя, self.поле, переменная.поле) → [lo, hi].
     Циклы: путь с единственным обновлением `p = p ± const` за
     итерацию ускоряется (значение на итерации k равно v0 + k*d —
     точный интервал в теле и после цикла); остальные присваивания
     в цикле расширяются до диапазона типа (грубо, но корректно).
  2. Отношения: разностные ограничения p <= q + d между путями
     (условия ветвей, requires, присваивания `let j = i + 1`,
     счётчики в ногу с переменной цикла) с транзитивным замыканием
     Флойда–Уоршелла. На return `result` символически связывается
     с возвращаемым выражением — так доказывается
     `ensures result >= a` у max.
  3. Структурное равенство выражений (с точностью до коммутативности):
     `result` раскрывается в выражение return — так доказывается
     `ensures result == x * 2`. Корректно, потому что обе стороны
     вычисляются в одном состоянии, а параметры неизменяемы.

Summary функции — интервал результата либо тождество параметру
(функция возвращает свой параметр, возможно через cast): во втором
случае интервал аргумента проходит сквозь вызов.

Функции обходятся в топологическом порядке DAG вызовов (рекурсии
нет — правило 1). Семантика «после trap'а»: выживший результат
операции всегда в диапазоне типа.
"""

from . import ast_nodes as ast
from .types import INT_RANGES, ArrayType, CharType, IntType, StrType

Iv = tuple[int, int]
_CASTS = ("i32", "u32", "u16", "u8", "u64", "i64")
_CHAR_IV: Iv = (0, 255)  # char — ровно один байт


def _range(kind: str) -> Iv:
    return INT_RANGES[kind]


def _tdiv(left: int, right: int) -> int:
    # усечение к нулю в целых: float-путь терял точность на 64 битах
    q = abs(left) // abs(right)
    return -q if (left < 0) != (right < 0) else q


def _uncast(node):
    """u8(char) и char(u8) тотальны и сохраняют байт — для путей,
    разложений и структурного равенства каст прозрачен."""
    while (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and (
            node.name == "char"
            or (
                node.name == "u8"
                and isinstance(getattr(node.args[0], "ty", None), CharType)
            )
        )
    ):
        node = node.args[0]
    return node


def _bytelike(ty) -> bool:
    """Типы с числовой байтовой/целой интерпретацией значения."""
    return isinstance(ty, (IntType, CharType))


def _ty_iv(ty) -> Iv | None:
    if isinstance(ty, IntType):
        return _range(ty.kind)
    if isinstance(ty, CharType):
        return _CHAR_IV
    return None


def _inter(a: Iv, b: Iv) -> Iv | None:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if lo <= hi else None


def _hull(a: Iv, b: Iv) -> Iv:
    return (min(a[0], b[0]), max(a[1], b[1]))


def _path_of(node) -> str | None:
    node = _uncast(node)
    if isinstance(node, ast.Name):
        return node.ident
    if isinstance(node, ast.SelfExpr):
        return "self"
    if isinstance(node, ast.FieldAccess):
        base = _path_of(node.obj)
        return f"{base}.{node.name}" if base is not None else None
    return None


def _conjuncts(expr):
    """Развернуть цепочку and в список конъюнктов."""
    if isinstance(expr, ast.BinOp) and expr.op == "and":
        yield from _conjuncts(expr.left)
        yield from _conjuncts(expr.right)
    else:
        yield expr


def _has_call(node) -> bool:
    node = _uncast(node)  # прозрачные касты — не вызовы
    if isinstance(node, (ast.Call, ast.MethodCall)):
        return True
    for attr in ("left", "right", "operand", "obj", "index"):
        child = getattr(node, attr, None)
        if child is not None and _has_call(child):
            return True
    return False


def _assigned_paths(block: ast.Block) -> set:
    paths = set()
    for stmt in block.stmts:
        if isinstance(stmt, ast.AssignStmt):
            p = _path_of(stmt.target)
            if p is not None:
                paths.add(p)
        for blk in _sub_blocks(stmt):
            paths |= _assigned_paths(blk)
    return paths


def _nested_loop_paths(block: ast.Block) -> set:
    """Пути, присваиваемые ВНУТРИ вложенных циклов блока. Сборщик
    значений выхода (_exit_rec) подменяется на входе во вложенный цикл,
    поэтому такие записи он не видит — их дырку через внешний цикл не
    проводим (осталось бы под-приближение = неверно)."""
    paths = set()
    for stmt in block.stmts:
        if isinstance(stmt, (ast.ForStmt, ast.LoopStmt)):
            paths |= _assigned_paths(stmt.body)
        else:
            for blk in _sub_blocks(stmt):
                paths |= _nested_loop_paths(blk)
    return paths


def _sub_blocks(stmt):
    if isinstance(stmt, ast.IfStmt):
        yield stmt.then
        for _, b in stmt.elifs:
            yield b
        if stmt.els is not None:
            yield stmt.els
    elif isinstance(stmt, (ast.ForStmt, ast.LoopStmt)):
        yield stmt.body
    elif isinstance(stmt, ast.MatchStmt):
        for arm in stmt.arms:
            yield arm.body


def _has_direct_break(block: ast.Block) -> bool:
    """break, привязанный к этому циклу (во вложенные не спускаемся)."""
    for stmt in block.stmts:
        if isinstance(stmt, ast.BreakStmt):
            return True
        if isinstance(stmt, (ast.ForStmt, ast.LoopStmt)):
            continue
        if any(_has_direct_break(b) for b in _sub_blocks(stmt)):
            return True
    return False


def _stmt_returns(stmt) -> bool:
    if isinstance(stmt, ast.ReturnStmt):
        return True
    if isinstance(stmt, ast.IfStmt):
        if stmt.els is None:
            return False
        blocks = [stmt.then, stmt.els] + [b for _, b in stmt.elifs]
        return all(_block_returns(b) for b in blocks)
    if isinstance(stmt, ast.MatchStmt):
        return all(_block_returns(a.body) for a in stmt.arms)
    return False


def _block_returns(block) -> bool:
    return any(_stmt_returns(s) for s in block.stmts)


def _block_exits(block) -> bool:
    """Управление не продолжается за if: ветка кончается return
    или break (break уводит на выход цикла, минуя join этого if)."""
    return _block_returns(block) or any(
        isinstance(s, ast.BreakStmt) for s in block.stmts
    )


class State:
    """Абстрактное состояние: интервалы путей + разностные ограничения
    путей + пути, известные как ненулевые."""

    __slots__ = ("ivs", "rels", "nz", "holes")

    def __init__(self, ivs=None, rels=None, nz=None, holes=None):
        self.ivs: dict[str, Iv] = dict(ivs or {})
        # (p, q) -> d: факт p <= q + d (минимальное известное d)
        self.rels: dict[tuple[str, str], int] = dict(rels or {})
        self.nz: set[str] = set(nz or ())  # пути со значением != 0
        # путь -> (плотная часть, сентинел): значение из пула вида
        # iv ∪ {NONE}; guard `!= NONE` схлопывает к плотной части
        self.holes: dict[str, tuple] = dict(holes or {})

    def copy(self) -> "State":
        return State(self.ivs, self.rels, self.nz, self.holes)

    def kill(self, path: str) -> None:
        for k in list(self.ivs):
            if k == path or k.startswith(path + "."):
                del self.ivs[k]
        for k in list(self.holes):
            if k == path or k.startswith(path + "."):
                del self.holes[k]

        def dead(p: str) -> bool:
            return p == path or p.startswith(path + ".")

        self.rels = {
            k: d
            for k, d in self.rels.items()
            if not dead(k[0]) and not dead(k[1])
        }
        self.nz = {p for p in self.nz if not dead(p)}

    def add(self, p: str, q: str, d: int) -> None:
        """Факт p <= q + d."""
        if p == q:
            return
        cur = self.rels.get((p, q))
        if cur is None or d < cur:
            self.rels[(p, q)] = d

    def relate(self, lhs: str, op: str, rhs: str) -> None:
        self.relate_offset(lhs, op, rhs, 0)

    def relate_offset(self, lhs: str, op: str, rhs: str, delta: int) -> None:
        """Факт lhs op rhs + delta."""
        if op == "<":
            self.add(lhs, rhs, delta - 1)
        elif op == "<=":
            self.add(lhs, rhs, delta)
        elif op == ">":
            self.add(rhs, lhs, -delta - 1)
        elif op == ">=":
            self.add(rhs, lhs, -delta)
        elif op == "==":
            self.add(lhs, rhs, delta)
            self.add(rhs, lhs, -delta)

    def closure(self) -> dict:
        """Транзитивное замыкание (Флойд–Уоршелл): кратчайшие d."""
        cl = dict(self.rels)
        nodes = {p for p, _ in cl} | {q for _, q in cl}
        for k in nodes:
            for i in nodes:
                dik = cl.get((i, k))
                if dik is None or i == k:
                    continue
                for j in nodes:
                    if j == i or j == k:
                        continue
                    dkj = cl.get((k, j))
                    if dkj is None:
                        continue
                    nd = dik + dkj
                    if nd < cl.get((i, j), nd + 1):
                        cl[(i, j)] = nd
        return cl


class Verifier:
    def __init__(self, program: ast.Program, checker):
        self.program = program
        self.checker = checker
        # key -> None | ("iv", Iv) | ("param", имя параметра)
        self.summaries: dict[str, tuple | None] = {}
        self.req_sites: dict[str, list] = {}  # key -> [proven, total]
        # (kind, id(node)) -> [bool, node] c AND-слиянием повторных оценок
        self.checks: dict[tuple, list] = {}
        self.cur_func: ast.FuncDecl | None = None
        self.cur_sig = None
        self.cur_module = 0  # модуль анализируемой функции (SPARK-граница)
        self.param_names: set = set()
        self.returns: list = []
        self.ret_syms: list = []
        self.ret_holes: list = []  # дырка (dense, sent) на каждом return
        self.ensures_ok: list = []
        self.ret_expr = None  # выражение текущего return для ensures
        # активный сбор значений, присваиваемых путям в теле цикла:
        # путь -> [(iv, hole)] по каждому присваиванию (для дырочного
        # объединения на выходе цикла); None — сбор выключен
        self._exit_rec: dict[str, list] | None = None
        self._exit_ty: dict[str, int] = {}  # путь -> максимум типа (сент.)
        self.cur_fn_key = ""  # ключ анализируемой функции (пулы)
        self.cur_struct: str | None = None
        # инварианты пулов и полей (трек 3): (struct, поле) |
        # (":local:"+ключ, имя) -> интервал значений; собираются
        # итеративными пассами анализа (см. run)
        self.pool_iv: dict[tuple, Iv] = {}
        self.field_iv: dict[tuple, Iv] = {}
        self._ps_acc: dict[tuple, Iv] = {}
        self._ps_dead: set = set()
        self._ps_deps: list = []
        self._ps_sent: dict[tuple, set] = {}
        self._fs_acc: dict[tuple, Iv] = {}
        self._fs_dead: set = set()
        self.pool_sent: dict[tuple, int] = {}
        self._hole: tuple | None = None  # (id узла, dense, sent)
        # пробный проход тела цикла: собирает дырочные/масочные
        # инварианты loop-carried путей, НЕ оставляя следов анализа —
        # отметки, счётчики requires и учёт return подавлены (иначе
        # AND-слияние проверок и двойной подсчёт return травят реальный
        # проход)
        self._probe = False

    # --- отметки и статистика ---------------------------------------------

    def _mark(self, kind: str, node, ok: bool) -> None:
        if self._probe:
            return
        key = (kind, id(node))
        if key in self.checks:
            self.checks[key][0] = self.checks[key][0] and ok
        else:
            self.checks[key] = [ok, node]
        attr = {
            "overflow": "no_overflow",
            "div": "div_safe",
            "bounds": "in_bounds",
            "cast": "cast_ok",
            "shift": "shift_ok",
        }.get(kind)
        if attr is not None:
            setattr(node, attr, self.checks[key][0])

    def stats(self) -> dict:
        by_kind: dict[str, list] = {}
        for (kind, _), (ok, _node) in self.checks.items():
            entry = by_kind.setdefault(kind, [0, 0])
            entry[1] += 1
            entry[0] += 1 if ok else 0
        proven = sum(v[0] for v in by_kind.values())
        total = sum(v[1] for v in by_kind.values())
        return {"proven": proven, "total": total, "by_kind": by_kind}

    # --- запуск --------------------------------------------------------------

    def run(self) -> dict:
        # Итеративные инварианты пулов и полей (трек 3): каждый пасс
        # анализа собирает join интервалов ВСЕХ записей (в состоянии
        # потока в точке записи); после пасса они становятся
        # инвариантами следующего. Корректность — индукция от вершины:
        # пасс с инвариантами ⊇ фактических значений даёт записи
        # ⊇ фактических; сужение монотонно. Отметки задаёт последний
        # пасс (перед ним карты совпали либо исчерпан лимит пассов).
        for _ in range(3):
            self._begin_pass()
            self._analyze_all()
            pool, field, sent = self._finish_pass()
            if (
                pool == self.pool_iv
                and field == self.field_iv
                and sent == self.pool_sent
            ):
                break
            self.pool_iv, self.field_iv = pool, field
            self.pool_sent = sent
        return self.stats()

    def _begin_pass(self) -> None:
        self.checks = {}
        self.req_sites = {}
        self.summaries = {}
        self._ps_acc = {}
        self._ps_dead = set()
        self._ps_deps = []
        self._ps_sent = {}
        self._fs_acc = {}
        self._fs_dead = set()

    def _finish_pass(self) -> tuple:
        # разрешение копий целых массивов: join по рёбрам до
        # неподвижной точки; источник без единой записи и без входящих
        # копий нетрассируем (параметр, привязка match) — приёмник мёртв
        acc, dead, deps = self._ps_acc, self._ps_dead, self._ps_deps
        known = set(acc) | {d for d, _ in deps} | set(dead)
        for _ in range(len(deps) + 1):
            changed = False
            for dst, src in deps:
                if dst in dead:
                    continue
                if src in dead or src not in known:
                    dead.add(dst)
                    changed = True
                    continue
                siv = acc.get(src)
                if siv is not None:
                    cur = acc.get(dst)
                    new = siv if cur is None else _hull(cur, siv)
                    if new != cur:
                        acc[dst] = new
                        changed = True
            if not changed:
                break
        # сентинелы наследуются по копиям; больше одного разного или
        # сентинел без плотной части — сложить в обычный интервал
        sents = self._ps_sent
        for _ in range(len(deps) + 1):
            grew = False
            for dst, src in deps:
                add = sents.get(src, set()) - sents.get(dst, set())
                if add and dst not in dead:
                    sents.setdefault(dst, set()).update(add)
                    grew = True
            if not grew:
                break
        pool_sent = {}
        for k, ss in sents.items():
            if k in dead:
                continue
            if len(ss) == 1 and k in acc:
                pool_sent[k] = next(iter(ss))
            else:
                for sv in ss:
                    cur = acc.get(k)
                    acc[k] = (
                        (sv, sv) if cur is None else _hull(cur, (sv, sv))
                    )
        pool = {k: v for k, v in acc.items() if k not in dead}
        field = {
            k: v for k, v in self._fs_acc.items() if k not in self._fs_dead
        }
        return pool, field, pool_sent

    def _analyze_all(self) -> None:
        order = self._topo_order()
        for key in order:
            func, struct = self._func_by_key(key)
            if func is not None and func.body is not None:
                self._analyze_func(func, key, struct)
        for decl in self.program.decls:
            if isinstance(decl, ast.TestBlock):
                self.cur_func = None
                self.cur_sig = None
                self.cur_module = self.checker.decl_module.get(id(decl), 0)
                self.cur_fn_key = f":test:{id(decl)}"
                self.cur_struct = None
                self.param_names = set()
                self.returns = []
                self.ret_syms = []
                self.ret_holes = []
                self.ensures_ok = []
                self._flow_block(decl.body, State())
        for key in order:
            func, _ = self._func_by_key(key)
            if func is None or func.requires is None:
                continue
            proven, total = self.req_sites.get(key, [0, 0])
            no_calls = not _has_call(func.requires)
            tautology = (
                self._eval_bool(func.requires, State(), annotate=False) is True
            )
            ok = no_calls and (tautology or (total > 0 and proven == total))
            func.requires_proven = ok
            self._mark("requires", func, ok)

    def _module_of(self, key: str) -> int:
        """Модуль-владелец функции/метода по ключу графа вызовов
        (для метода — модуль структуры-владельца)."""
        sname = key.split(".", 1)[0]
        return self.checker.name_module.get(sname, 0)

    def _func_by_key(self, key: str):
        if "." in key:
            sname, mname = key.split(".", 1)
            for decl in self.program.decls:
                if isinstance(decl, ast.StructDecl) and decl.name == sname:
                    for m in decl.methods:
                        if m.name == mname:
                            return m, sname
            return None, None
        for decl in self.program.decls:
            if isinstance(decl, ast.FuncDecl) and decl.name == key:
                return decl, None
        return None, None

    # --- инварианты пулов (трек 3, VERIFICATION_PLAN «направление 1») -----
    # Пул — массив (локальный или поле struct, в т.ч. банкованный
    # [[T; N]; M]). Инвариант — join интервалов ВСЕХ записей элементов
    # по всей программе, вычисленных в состоянии потока в точке записи
    # (итеративные пассы run: инварианты пасса k-1 — факты пасса k).
    # Ключ поля — struct, непосредственно владеющий полем, на любой
    # глубине вложенности значения (Parser.nk остаётся Parser.nk и когда
    # Parser лежит полем в Check). Копия целого массива — ребро
    # зависимости; копия из нетрассируемого источника (параметр,
    # результат вызова, привязка match) убивает ключ. Корректность:
    # массивы всегда полностью инициализированы при создании (язык),
    # поэтому join «инициализация + все записи» покрывает все значения.

    def _pool_key(self, node, fn_key: str, sname: str | None):
        base = node
        while isinstance(base, ast.Index):
            base = base.obj
        if isinstance(base, ast.FieldAccess):
            obj = base.obj
            owner = getattr(getattr(obj, "ty", None), "name", None)
            if owner is None and isinstance(obj, ast.SelfExpr):
                owner = sname
            if owner is not None and owner in self.checker.structs:
                return (owner, base.name)
            return None
        if isinstance(base, ast.Name):
            return (":local:" + fn_key, base.ident)
        return None

    def _field_key(self, node, sname: str | None):
        """Ключ скалярного поля struct: владелец — struct,
        непосредственно содержащий поле (на любой глубине значения)."""
        if not isinstance(node, ast.FieldAccess):
            return None
        owner = getattr(getattr(node.obj, "ty", None), "name", None)
        if owner is None and isinstance(node.obj, ast.SelfExpr):
            owner = sname
        if owner is not None and owner in self.checker.structs:
            return (owner, node.name)
        return None

    def _note_pool(self, key, iv, sent_max=None) -> None:
        """Запись элемента пула. Точечная запись максимума типа —
        сентинел (NONE): копится отдельно от плотной части, чтобы
        не растягивать интервал до полного диапазона."""
        if key is None:
            return
        if iv is None:
            self._ps_dead.add(key)
        elif sent_max is not None and iv == (sent_max, sent_max):
            self._ps_sent.setdefault(key, set()).add(sent_max)
        else:
            cur = self._ps_acc.get(key)
            self._ps_acc[key] = iv if cur is None else _hull(cur, iv)

    def _note_field(self, key, iv) -> None:
        if key is None:
            return
        if iv is None:
            self._fs_dead.add(key)
        else:
            cur = self._fs_acc.get(key)
            self._fs_acc[key] = iv if cur is None else _hull(cur, iv)

    def _elem_iv(self, expr, env: State):
        """Интервал скалярных листьев литерала-массива в состоянии
        потока; None — неизвестно (нечисловые листья убивают ключ —
        безвредно: интервал спрашивают только у int/char-чтений)."""
        if isinstance(expr, ast.ArrayFill):
            return self._elem_iv(expr.value, env)
        if isinstance(expr, ast.ArrayLit):
            got = None
            for e in expr.elems:
                part = self._elem_iv(e, env)
                if part is None:
                    return None
                got = part if got is None else _hull(got, part)
            return got
        return self._iv(expr, env, annotate=False)

    def _store_array(self, key, expr, env: State) -> None:
        """Запись целого массива: литерал даёт интервал листьев, копия
        другого пула — ребро зависимости, всё прочее (результат
        вызова, привязка match) — нетрассируемо, ключ мёртв."""
        if key is None:
            return
        if isinstance(expr, (ast.ArrayFill, ast.ArrayLit)):
            ety = getattr(expr, "ty", None)
            while isinstance(ety, ArrayType):
                ety = ety.elem
            sent_max = (
                _range(ety.kind)[1] if isinstance(ety, IntType) else None
            )
            self._note_pool(key, self._elem_iv(expr, env), sent_max)
            return
        if isinstance(expr, (ast.Name, ast.FieldAccess, ast.Index)):
            src = self._pool_key(expr, self.cur_fn_key, self.cur_struct)
            if src is not None:
                self._ps_deps.append((key, src))
                return
        self._ps_dead.add(key)

    def _topo_order(self) -> list:
        keys = list(self.checker.funcs)
        for decl in self.program.decls:
            if isinstance(decl, ast.StructDecl):
                keys += [f"{decl.name}.{m.name}" for m in decl.methods]
        graph = {k: set() for k in keys}
        for caller, callee in self.checker.edges:
            if caller in graph and callee in graph:
                graph[caller].add(callee)
        order: list = []
        seen: set = set()

        def visit(k: str) -> None:
            if k in seen:
                return
            seen.add(k)
            for c in graph[k]:
                visit(c)
            order.append(k)  # callee раньше caller

        for k in keys:
            visit(k)
        return order

    # --- анализ функции ------------------------------------------------------

    def _analyze_func(self, func, key: str, struct: str | None) -> None:
        sig = (
            self.checker.structs[struct].methods[func.name]
            if struct is not None
            else self.checker.funcs[func.name]
        )
        self.cur_func = func
        self.cur_sig = sig
        self.cur_module = self._module_of(key)
        self.cur_fn_key = key
        self.cur_struct = struct
        self.param_names = {p for p, _ in sig.params}
        self.returns = []
        self.ret_syms = []
        self.ret_holes = []
        self.ensures_ok = []
        env = State()
        for pname, ptype in sig.params:
            piv = _ty_iv(ptype)
            if piv is not None:
                env.ivs[pname] = piv
        if func.requires is not None:
            self._eval_bool(func.requires, env)  # аннотации внутри requires
            self._refine(env, func.requires, True)
        env = self._flow_block(func.body, env)
        if func.ensures is not None and not self.returns:
            # функция без return (void): ensures проверяется на выходе
            ok = self._eval_bool(func.ensures, env)
            self.ensures_ok.append(ok is True)
        if func.ensures is not None:
            proven = (
                bool(self.ensures_ok)
                and all(self.ensures_ok)
                and not _has_call(func.ensures)
            )
            func.ensures_proven = proven
            self._mark("ensures", func, proven)
        self.summaries[key] = self._summary(sig)

    def _summary(self, sig) -> tuple | None:
        if not isinstance(sig.ret, IntType) or not self.returns:
            return None
        # тождество параметру: все return возвращают один параметр
        syms = set(self.ret_syms)
        if len(syms) == 1 and None not in syms:
            return ("param", next(iter(syms)))
        ivs = [r for r in self.returns if r is not None]
        if len(ivs) != len(self.returns):
            return None
        # возвраты вида «плотная часть ∪ {NONE}» — итог ("hive", dense,
        # sent), на месте вызова guard `!= NONE` схлопнет к плотной
        # части. Сентинел даёт либо явная дырка возврата (return f,
        # где f её несёт), либо точечный возврат максимума типа.
        hive = self._hive_summary(sig)
        if hive is not None:
            return hive
        summary = ivs[0]
        for r in ivs[1:]:
            summary = _hull(summary, r)
        clamped = _inter(summary, _range(sig.ret.kind))
        return ("iv", clamped) if clamped is not None else None

    def _hive_summary(self, sig) -> tuple | None:
        """Summary «плотное ∪ {sent}»: каждый return — либо дырка с
        сентинелом sent, либо точечный сентинел (максимум типа), либо
        плотный интервал строго ниже sent. Нужен ≥ один сентинел и
        ≥ одна плотная часть, сентинел единственный."""
        smax = _range(sig.ret.kind)[1]
        sent = None
        dense = None
        saw_sent = False
        for riv, hole in zip(self.returns, self.ret_holes):
            if riv is None:
                return None
            if hole is not None:
                dpart, s = hole
                if sent is not None and s != sent:
                    return None
                sent, saw_sent = s, True
                dense = dpart if dense is None else _hull(dense, dpart)
            elif riv == (smax, smax):
                if sent is not None and sent != smax:
                    return None
                sent, saw_sent = smax, True
            else:
                dense = riv if dense is None else _hull(dense, riv)
        if not saw_sent or dense is None or dense[1] >= sent:
            return None
        dclamp = _inter(dense, _range(sig.ret.kind))
        return ("hive", dclamp, sent) if dclamp is not None else None

    def _ret_sym(self, value) -> str | None:
        """Параметр, которому тождественен return (возможно через cast)."""
        if isinstance(value, ast.Name) and value.ident in self.param_names:
            return value.ident
        if (
            isinstance(value, ast.Call)
            and value.name in _CASTS
            and isinstance(value.args[0], ast.Name)
            and value.args[0].ident in self.param_names
        ):
            return value.args[0].ident
        return None

    # --- поток управления ----------------------------------------------------

    def _flow_block(self, block: ast.Block, env: State) -> State:
        env = env.copy()
        for stmt in block.stmts:
            env = self._flow_stmt(stmt, env)
        return env

    def _flow_stmt(self, stmt, env: State) -> State:
        if isinstance(stmt, ast.LetStmt):
            value = self._iv(stmt.value, env)
            if isinstance(getattr(stmt, "var_ty", None), ArrayType):
                self._store_array(
                    (":local:" + self.cur_fn_key, stmt.name),
                    stmt.value, env,
                )
            if self._hole is not None and self._hole[0] == id(stmt.value):
                env.holes[stmt.name] = (self._hole[1], self._hole[2])
                self._hole = None
            clamp = _ty_iv(stmt.var_ty)
            if clamp is not None:
                env.ivs[stmt.name] = (
                    (_inter(value, clamp) or clamp)
                    if value is not None
                    else clamp
                )
                # отношение через присваивание выражения:
                # let j = i + 1 даёт факт j == i + 1
                vdec = self._decompose(stmt.value)
                if vdec is not None:
                    env.relate_offset(stmt.name, "==", vdec[0], vdec[1])
            if isinstance(stmt.value, ast.StructLit):
                for fname, fexpr in stmt.value.fields:
                    fiv = self._iv(fexpr, env)
                    if fiv is not None:
                        env.ivs[f"{stmt.name}.{fname}"] = fiv
            # модульный контракт: ensures вызванной функции гарантирован
            # рантаймом (доказан или проверен trap'ом) — предполагаем
            if isinstance(stmt.value, ast.Call):
                fname2 = stmt.value.name
                if fname2 in self.checker.funcs:
                    func, _ = self._func_by_key(fname2)
                    self._assume_ensures(
                        env,
                        func,
                        self.checker.funcs[fname2],
                        stmt.value,
                        stmt.name,
                        None,
                    )
            elif isinstance(stmt.value, ast.MethodCall) and (
                getattr(stmt.value, "enum_ctor", None) is None
            ):
                key = f"{stmt.value.struct}.{stmt.value.name}"
                func, _ = self._func_by_key(key)
                sig = self.checker.structs[stmt.value.struct].methods[
                    stmt.value.name
                ]
                self._assume_ensures(
                    env,
                    func,
                    sig,
                    stmt.value,
                    stmt.name,
                    _path_of(stmt.value.obj),
                )
            return env
        if isinstance(stmt, ast.AssignStmt):
            value = self._iv(stmt.value, env)
            tty = getattr(stmt.target, "ty", None)
            if isinstance(stmt.target, ast.Index):
                # границы цели присваивания тоже проверяются
                self._iv(stmt.target, env)
                pkey = self._pool_key(
                    stmt.target, self.cur_fn_key, self.cur_struct
                )
                if isinstance(tty, ArrayType):
                    self._store_array(pkey, stmt.value, env)
                else:
                    tiv = _ty_iv(tty)
                    self._note_pool(
                        pkey,
                        (value if value is not None else tiv)
                        if tiv is not None
                        else None,
                        _range(tty.kind)[1]
                        if isinstance(tty, IntType)
                        else None,
                    )
            elif isinstance(stmt.target, ast.FieldAccess):
                if isinstance(tty, ArrayType):
                    self._store_array(
                        self._pool_key(
                            stmt.target, self.cur_fn_key, self.cur_struct
                        ),
                        stmt.value, env,
                    )
                else:
                    tiv = _ty_iv(tty)
                    self._note_field(
                        self._field_key(stmt.target, self.cur_struct),
                        (value if value is not None else tiv)
                        if tiv is not None
                        else None,
                    )
            elif isinstance(stmt.target, ast.Name) and isinstance(
                tty, ArrayType
            ):
                self._store_array(
                    (":local:" + self.cur_fn_key, stmt.target.ident),
                    stmt.value, env,
                )
            path = _path_of(stmt.target)
            if path is not None:
                env.kill(path)
                if self._hole is not None and self._hole[0] == id(
                    stmt.value
                ):
                    env.holes[path] = (self._hole[1], self._hole[2])
                    self._hole = None
                clamp = _ty_iv(stmt.target.ty)
                if clamp is not None:
                    if value is not None:
                        clamped = _inter(value, clamp)
                        if clamped is not None:
                            env.ivs[path] = clamped
                    # x = y + 1 даёт факт x == y + 1 (сам путь в правой
                    # части — старое значение, факт не записываем)
                    vdec = self._decompose(stmt.value)
                    if vdec is not None and vdec[0] != path:
                        env.relate_offset(path, "==", vdec[0], vdec[1])
                if self._exit_rec is not None and path in self._exit_rec:
                    self._exit_rec[path].append(
                        (env.ivs.get(path), env.holes.get(path))
                    )
                    if isinstance(tty, IntType):
                        self._exit_ty[path] = _range(tty.kind)[1]
            return env
        if isinstance(stmt, ast.IfStmt):
            return self._flow_if(stmt, env)
        if isinstance(stmt, ast.ForStmt):
            return self._flow_for(stmt, env)
        if isinstance(stmt, ast.LoopStmt):
            body_env = env.copy()
            for p in _assigned_paths(stmt.body):
                body_env.kill(p)
            self._flow_block(stmt.body, body_env)
            return body_env
        if isinstance(stmt, ast.MatchStmt):
            return self._flow_match(stmt, env)
        if isinstance(stmt, ast.ReturnStmt):
            riv = self._iv(stmt.value, env) if stmt.value is not None else None
            if self._probe:
                return env  # проба не учитывает return (иначе двойной счёт)
            self.returns.append(riv)
            self.ret_syms.append(
                self._ret_sym(stmt.value) if stmt.value is not None else None
            )
            # дырка возврата: `return f`, где f несёт «плотное ∪ {NONE}» —
            # так summary становится hive и на месте вызова guard != NONE
            # у полученного значения схлопывает к плотной части
            rpath = (
                _path_of(stmt.value) if stmt.value is not None else None
            )
            self.ret_holes.append(
                env.holes.get(rpath) if rpath is not None else None
            )
            func = self.cur_func
            if func is not None and func.ensures is not None:
                env_r = env.copy()
                if riv is not None:
                    env_r.ivs["result"] = riv
                rdec = (
                    self._decompose(stmt.value)
                    if stmt.value is not None
                    else None
                )
                if rdec is not None:
                    env_r.relate_offset("result", "==", rdec[0], rdec[1])
                self.ret_expr = stmt.value  # result ≡ выражение return
                ok = self._eval_bool(func.ensures, env_r)
                self.ret_expr = None
                self.ensures_ok.append(ok is True)
            return env
        if isinstance(stmt, ast.AssertStmt):
            ok = self._eval_bool(stmt.cond, env)
            proven = ok is True and not _has_call(stmt.cond)
            stmt.proven = proven
            self._mark("assert", stmt, proven)
            # рантайм гарантирует условие после assert — уточняем
            self._refine(env, stmt.cond, True)
            return env
        if isinstance(stmt, (ast.ExprStmt, ast.DiscardStmt)):
            self._iv(stmt.expr, env)
            # модульный контракт мутирующего метода: ensures о self.поле
            # становится фактом о получателе (после kill в _iv_method)
            if isinstance(stmt.expr, ast.MethodCall) and (
                getattr(stmt.expr, "enum_ctor", None) is None
            ):
                sig = self.checker.structs[stmt.expr.struct].methods[
                    stmt.expr.name
                ]
                func, _ = self._func_by_key(
                    f"{stmt.expr.struct}.{stmt.expr.name}"
                )
                self._assume_ensures(
                    env, func, sig, stmt.expr, None, _path_of(stmt.expr.obj)
                )
            return env
        return env

    def _flow_if(self, stmt: ast.IfStmt, env: State) -> State:
        branches = []
        conds = [stmt.cond] + [c for c, _ in stmt.elifs]
        blocks = [stmt.then] + [b for _, b in stmt.elifs]
        neg_env = env.copy()
        for cond, block in zip(conds, blocks):
            self._eval_bool(cond, neg_env)  # аннотации внутри условия
            b_env = neg_env.copy()
            self._refine(b_env, cond, True)
            out = self._flow_block(block, b_env)
            if not _block_exits(block):
                branches.append(out)
            self._refine(neg_env, cond, False)
        if stmt.els is not None:
            out = self._flow_block(stmt.els, neg_env)
            if not _block_exits(stmt.els):
                branches.append(out)
        else:
            branches.append(neg_env)
        return self._join(branches)

    def _loop_body_env(self, stmt, env, accel, n):
        """Состояние на входе тела цикла: все присваиваемые пути
        обнулены (значение неизвестно), accel-пути получают линейный
        интервал витка, переменная цикла — свой диапазон. Возвращает
        (body_env, after) — after: интервалы accel-путей ПОСЛЕ цикла."""
        body_env = env.copy()
        after: dict[str, Iv] = {}
        for p in _assigned_paths(stmt.body):
            v0 = env.ivs.get(p)
            body_env.kill(p)
            info = accel.get(p)
            if info is None or v0 is None:
                continue
            d, cond, kind, glo, ghi = info
            clamp = _range(kind)
            b_lo = v0[0] + min(0, (n - 1) * d)
            b_hi = v0[1] + max(0, (n - 1) * d)
            a_lo = v0[0] + (min(0, n * d) if cond else n * d)
            a_hi = v0[1] + (max(0, n * d) if cond else n * d)
            if d > 0 and ghi is not None:
                cap = max(v0[1], ghi + d)
                b_hi = min(b_hi, cap)
                a_hi = min(a_hi, cap)
            if d < 0 and glo is not None:
                floor = min(v0[0], glo + d)
                b_lo = max(b_lo, floor)
                a_lo = max(a_lo, floor)
            body_env.ivs[p] = _inter((b_lo, b_hi), clamp) or clamp
            after[p] = _inter((a_lo, a_hi), clamp) or clamp
        if stmt.bounds is not None:
            if n > 0:
                start = stmt.bounds[0]
                body_env.ivs[stmt.target] = (start, stmt.bounds[1] - 1)
                if stmt.target != "_":
                    self._lockstep(stmt, accel, env, body_env, start)
        else:
            eiv = _ty_iv(stmt.elem_ty)
            if eiv is not None:
                pkey = self._pool_key(
                    stmt.iterable, self.cur_fn_key, self.cur_struct
                )
                inv = self.pool_iv.get(pkey) if pkey is not None else None
                body_env.ivs[stmt.target] = (
                    (_inter(inv, eiv) or eiv) if inv is not None else eiv
                )
        return body_env, after

    def _flow_for(self, stmt: ast.ForStmt, env: State) -> State:
        if stmt.bounds is not None:
            n = stmt.bounds[1] - stmt.bounds[0]
        else:
            self._iv(stmt.iterable, env)
            ity = stmt.iterable.ty
            n = ity.size if isinstance(ity, ArrayType) else None
        accel = self._accelerate(stmt.body) if n is not None else {}
        tracked = _assigned_paths(stmt.body)
        # инварианты проводим только для путей, все записи которых видит
        # сборщик (не спрятаны во вложенных циклах)
        observed = tracked - _nested_loop_paths(stmt.body)

        # проба: прогнать тело без следов анализа, собрать значения,
        # присваиваемые observed-путям. Объединение (вход ∪ все записи)
        # — валидный инвариант пути на входе тела и на выходе цикла
        # (⊇ значения на любой границе витка); масочная/пуловая запись
        # `slot = (slot+1) & M`, `c = pool[...]` даёт [0,M] / дырку
        # независимо от старого значения пути
        body_env, after = self._loop_body_env(stmt, env, accel, n)
        saved_probe = self._probe
        self._probe = True
        prev_rec, prev_ty = self._exit_rec, self._exit_ty
        self._exit_rec = {p: [] for p in observed}
        self._exit_ty = {}
        self._flow_block(stmt.body, body_env)
        recs, recs_ty = self._exit_rec, self._exit_ty
        self._exit_rec, self._exit_ty = prev_rec, prev_ty
        self._probe = saved_probe

        def loop_exit(p):
            return self._loop_exit(
                env.ivs.get(p), env.holes.get(p),
                recs.get(p, []), recs_ty.get(p),
            )

        # инварианты loop-carried путей, доступные на входе тела:
        # accel-пути точнее (линейный ход), их не трогаем. В теле путь
        # обнулён (kill → полный диапазон), поэтому любой ограниченный
        # инвариант — уточнение, регрессии быть не может
        inv: dict[str, tuple] = {}
        for p in observed:
            if p in after:
                continue
            iv, hole = loop_exit(p)
            if iv is not None:
                inv[p] = (iv, hole)

        # реальный проход: тот же вход тела + инварианты, с отметками
        body_env, after = self._loop_body_env(stmt, env, accel, n)
        for p, (iv, hole) in inv.items():
            body_env.ivs[p] = iv
            if hole is not None:
                body_env.holes[p] = hole
        self._flow_block(stmt.body, body_env)

        if _has_direct_break(stmt.body):
            # ранний выход: ускорение неприменимо (цикл мог прерваться
            # на любом витке), но дырочное объединение значений выхода
            # (вход ∪ все записи тела) сохраняет форму «плотное ∪ {NONE}»
            out = env.copy()
            out.kill(stmt.target)
            for p in tracked:
                out.kill(p)
                if p not in observed:
                    continue  # записи спрятаны во вложенном цикле — забыть
                iv, hole = loop_exit(p)
                if iv is not None:
                    out.ivs[p] = iv
                    if hole is not None:
                        out.holes[p] = hole
            return out
        out = body_env.copy()
        out.kill(stmt.target)
        for p, iv in after.items():
            out.kill(p)
            out.ivs[p] = iv
        # непроускоренные пути с дыркой: объединение вход ∪ записи тела
        # сохраняет сентинел (accel-пути точнее — их не трогаем)
        for p in observed:
            if p in after:
                continue
            iv, hole = loop_exit(p)
            if hole is not None:
                out.ivs[p] = iv
                out.holes[p] = hole
        return out

    def _loop_exit(self, v0_iv, v0_hole, recs, smax):
        """Значение пути на выходе цикла — дырочное объединение входного
        значения и всех значений, присвоенных телу за один символический
        виток (каждое над-приближает свою итерацию). Сентинел даёт явная
        дырка записи либо точечное значение максимума типа (smax) — так
        `var f = NONE; в цикле f = fi` даёт «плотное ∪ {NONE}».
        Возвращает (интервал | None, дырка (dense, sent) | None);
        None-интервал — неизвестно (полный диапазон, без дырки)."""
        cands = [(v0_iv, v0_hole)] + list(recs)
        dense = None
        sents: set = set()
        for iv, hole in cands:
            if iv is None:
                return None, None  # вход/запись без интервала — забываем
            if hole is not None:
                dpart, sent = hole
                dense = dpart if dense is None else _hull(dense, dpart)
                sents.add(sent)
            elif smax is not None and iv == (smax, smax):
                sents.add(smax)  # точечный максимум типа — сентинел
            else:
                dense = iv if dense is None else _hull(dense, iv)
        if dense is None:
            return None, None
        if len(sents) == 1:
            sent = next(iter(sents))
            if dense[1] < sent:  # плотная часть строго ниже сентинела
                return _hull(dense, (sent, sent)), (dense, sent)
            return _hull(dense, (sent, sent)), None
        full = dense
        for s in sents:  # 0 или >1 сентинелов — сложить в интервал
            full = _hull(full, (s, s))
        return full, None

    def _lockstep(
        self, stmt, accel: dict, env: State, body_env: State, start: int
    ) -> None:
        """Инвариант связи счётчиков: путь с единственным обновлением
        `p = p + 1` идёт в ногу с переменной цикла. На входе итерации k
        target == start + k, а p == v0 + (число сработавших обновлений):
        безусловное обновление даёт p <= target + (v0_hi - start) и
        p >= target + (v0_lo - start) (при точном v0 — равенство),
        условное — только верхнюю границу. Обновление внутри тела
        убивает факт через kill(p)."""
        for p, info in accel.items():
            d, cond, _kind, _glo, _ghi = info
            v0 = env.ivs.get(p)
            if d != 1 or v0 is None:
                continue
            body_env.relate_offset(p, "<=", stmt.target, v0[1] - start)
            if not cond:
                body_env.relate_offset(p, ">=", stmt.target, v0[0] - start)

    def _accelerate(self, block: ast.Block) -> dict:
        """Пути с единственным обновлением `p = p ± const` за итерацию:
        p -> (дельта, условное ли, вид целого, охрана снизу/сверху)."""
        updates: dict = {}
        self._collect_updates(block, False, updates, [])
        return {
            p: recs[0]
            for p, recs in updates.items()
            if recs != "invalid" and len(recs) == 1
        }

    def _collect_updates(
        self,
        block: ast.Block,
        conditional: bool,
        updates: dict,
        guards: list,
    ) -> None:
        for stmt in block.stmts:
            if isinstance(stmt, ast.AssignStmt):
                p = _path_of(stmt.target)
                if p is None:
                    continue
                if updates.get(p) == "invalid":
                    continue
                d = self._delta_of(stmt.value, p)
                tty = stmt.target.ty
                if d is None or not isinstance(tty, IntType):
                    updates[p] = "invalid"
                else:
                    glo, ghi = self._guard_bounds(guards, p)
                    updates.setdefault(p, []).append(
                        (d, conditional, tty.kind, glo, ghi)
                    )
                continue
            if isinstance(stmt, (ast.ForStmt, ast.LoopStmt)):
                # вложенный цикл: кратность обновлений неизвестна
                for p in _assigned_paths(stmt.body):
                    updates[p] = "invalid"
                continue
            if isinstance(stmt, ast.IfStmt):
                conds = [stmt.cond] + [c for c, _ in stmt.elifs]
                blocks = [stmt.then] + [b for _, b in stmt.elifs]
                for cond, blk in zip(conds, blocks):
                    self._collect_updates(blk, True, updates, guards + [cond])
                if stmt.els is not None:
                    self._collect_updates(stmt.els, True, updates, guards)
                continue
            for blk in _sub_blocks(stmt):
                self._collect_updates(blk, True, updates, guards)

    def _guard_bounds(self, guards: list, path: str):
        """Границы path из охраняющих условий: `path < C` даёт верх,
        `path > C` — низ (C — литерал или const)."""
        lo = None
        hi = None
        for guard in guards:
            for conj in _conjuncts(guard):
                if not isinstance(conj, ast.BinOp):
                    continue
                for target, op, other in (
                    (conj.left, conj.op, conj.right),
                    (
                        conj.right,
                        {"<": ">", "<=": ">=", ">": "<", ">=": "<="}.get(
                            conj.op, ""
                        ),
                        conj.left,
                    ),
                ):
                    if _path_of(target) != path:
                        continue
                    c = self._const_of(other)
                    if c is None:
                        continue
                    if op == "<":
                        hi = c - 1 if hi is None else min(hi, c - 1)
                    elif op == "<=":
                        hi = c if hi is None else min(hi, c)
                    elif op == ">":
                        lo = c + 1 if lo is None else max(lo, c + 1)
                    elif op == ">=":
                        lo = c if lo is None else max(lo, c)
        return lo, hi

    def _const_of(self, node) -> int | None:
        if isinstance(node, ast.IntLit):
            return node.value
        if isinstance(node, ast.Name) and node.ident in self.checker.consts:
            return self.checker.consts[node.ident][1]
        return None

    def _delta_of(self, value, path: str) -> int | None:
        if not isinstance(value, ast.BinOp) or value.op not in ("+", "-"):
            return None
        if _path_of(value.left) == path:
            step = value.right
        elif value.op == "+" and _path_of(value.right) == path:
            step = value.left
        else:
            return None
        c = self._const_of(step)
        if c is None:
            return None
        return c if value.op == "+" else -c

    def _flow_match(self, stmt: ast.MatchStmt, env: State) -> State:
        self._iv(stmt.subject, env)
        branches = []
        for arm in stmt.arms:
            a_env = env.copy()
            if arm.binding is not None:
                biv = _ty_iv(arm.payload_ty)
                if biv is not None:
                    a_env.ivs[arm.binding] = biv
            out = self._flow_block(arm.body, a_env)
            if not _block_returns(arm.body):
                branches.append(out)
        return self._join(branches) if branches else env

    def _join(self, envs: list) -> State:
        if not envs:
            return State()
        keys = set(envs[0].ivs)
        rkeys = set(envs[0].rels)
        for e in envs[1:]:
            keys &= set(e.ivs)
            rkeys &= set(e.rels)
        # общий факт — слабейшая из границ (максимальное d)
        rels = {k: max(e.rels[k] for e in envs) for k in rkeys}
        nz = set(envs[0].nz)
        for e in envs[1:]:
            nz &= e.nz
        joined = State(rels=rels, nz=nz)
        for k in keys:
            iv = envs[0].ivs[k]
            for e in envs[1:]:
                iv = _hull(iv, e.ivs[k])
            joined.ivs[k] = iv
        hkeys = set(envs[0].holes)
        for e in envs[1:]:
            hkeys &= set(e.holes)
        for k in hkeys:
            h0 = envs[0].holes[k]
            if all(e.holes[k] == h0 for e in envs[1:]):
                joined.holes[k] = h0
        return joined

    # --- уточнение по условиям -----------------------------------------------

    def _refine(self, env: State, cond, assume: bool) -> None:
        if isinstance(cond, ast.BinOp) and cond.op == "and" and assume:
            self._refine(env, cond.left, True)
            self._refine(env, cond.right, True)
            return
        if isinstance(cond, ast.BinOp) and cond.op == "or" and not assume:
            self._refine(env, cond.left, False)
            self._refine(env, cond.right, False)
            return
        if isinstance(cond, ast.UnaryOp) and cond.op == "not":
            self._refine(env, cond.operand, not assume)
            return
        if not isinstance(cond, ast.BinOp):
            return
        neg = {
            "<": ">=",
            "<=": ">",
            ">": "<=",
            ">=": "<",
            "==": "!=",
            "!=": "==",
        }
        op = cond.op if assume else neg.get(cond.op)
        if op == "!=":
            # неравенство константе: подрезка границ + метка «не ноль»
            self._refine_neq(env, cond.left, cond.right)
            self._refine_neq(env, cond.right, cond.left)
            return
        if op is None or op not in ("<", "<=", ">", ">=", "=="):
            return
        self._refine_cmp(env, cond.left, op, cond.right)
        mirror = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "=="}
        self._refine_cmp(env, cond.right, mirror[op], cond.left)
        # отношения между путями (с учётом смещения p ± c:
        # из `i + 1 < n` следует факт i < n - 1)
        dl = self._decompose(cond.left)
        dr = self._decompose(cond.right)
        if (
            dl is not None
            and dr is not None
            and dl[0] != dr[0]
            and _bytelike(getattr(cond.left, "ty", None))
            and _bytelike(getattr(cond.right, "ty", None))
        ):
            env.relate_offset(dl[0], op, dr[0], dr[1] - dl[1])

    def _refine_cmp(self, env: State, target, op: str, other) -> None:
        path = _path_of(target)
        default = _ty_iv(getattr(target, "ty", None))
        if path is None or default is None:
            return
        oiv = self._iv(other, env, annotate=False)
        if oiv is None:
            return
        cur = env.ivs.get(path, default)
        if op == "<":
            new = _inter(cur, (cur[0], oiv[1] - 1))
        elif op == "<=":
            new = _inter(cur, (cur[0], oiv[1]))
        elif op == ">":
            new = _inter(cur, (oiv[0] + 1, cur[1]))
        elif op == ">=":
            new = _inter(cur, (oiv[0], cur[1]))
        else:  # ==
            new = _inter(cur, oiv)
        if new is not None:
            env.ivs[path] = new

    def _refine_neq(self, env: State, target, other) -> None:
        path = _path_of(target)
        default = _ty_iv(getattr(target, "ty", None))
        if path is None or default is None:
            return
        oiv = self._iv(other, env, annotate=False)
        if oiv is not None and oiv[0] == oiv[1]:
            hole = env.holes.get(path)
            if hole is not None and hole[1] == oiv[0]:
                # значение было dense ∪ {sent}; sent исключён guard'ом
                cur = env.ivs.get(path)
                env.ivs[path] = (
                    (_inter(hole[0], cur) or hole[0])
                    if cur is not None
                    else hole[0]
                )
                del env.holes[path]
        if oiv is None or oiv[0] != oiv[1]:
            return
        c = oiv[0]
        if c == 0:
            env.nz.add(path)
        cur = env.ivs.get(path, default)
        if cur[0] == c:
            cur = (c + 1, cur[1])
        if cur[1] == c:
            cur = (cur[0], c - 1)
        if cur[0] <= cur[1]:
            env.ivs[path] = cur

    # --- трёхзначная логика --------------------------------------------------

    def _eval_bool(self, node, env: State, annotate: bool = True):
        if isinstance(node, ast.BoolLit):
            return node.value
        if isinstance(node, ast.UnaryOp) and node.op == "not":
            inner = self._eval_bool(node.operand, env, annotate)
            return None if inner is None else not inner
        if isinstance(node, ast.BinOp) and node.op in ("and", "or"):
            left = self._eval_bool(node.left, env, annotate)
            right = self._eval_bool(node.right, env, annotate)
            if node.op == "and":
                if left is False or right is False:
                    return False
                if left is True and right is True:
                    return True
                return None
            if left is True or right is True:
                return True
            if left is False and right is False:
                return False
            return None
        if isinstance(node, ast.BinOp) and node.op in (
            "<",
            "<=",
            ">",
            ">=",
            "==",
            "!=",
        ):
            left = self._iv(node.left, env, annotate)
            right = self._iv(node.right, env, annotate)
            if left is not None and right is not None:
                res = self._cmp_iv(node.op, left, right)
                if res is not None:
                    return res
            lp, rp = _path_of(node.left), _path_of(node.right)
            if (
                lp is not None
                and rp is not None
                and _bytelike(getattr(node.left, "ty", None))
                and _bytelike(getattr(node.right, "ty", None))
            ):
                res = self._decide_rel(env, lp, node.op, rp)
                if res is not None:
                    return res
            # разложение p ± c: из i < n следует i + 1 <= n
            dl = self._decompose(node.left)
            dr = self._decompose(node.right)
            if (
                dl is not None
                and dr is not None
                and _bytelike(getattr(node.left, "ty", None))
                and _bytelike(getattr(node.right, "ty", None))
            ):
                res = self._decide_offset(env, dl, node.op, dr)
                if res is not None:
                    return res
            # структурное равенство: обе стороны — одно выражение,
            # вычисленное в одном состоянии (result ≡ выражению return)
            if self._expr_equal(node.left, node.right):
                return node.op in ("==", "<=", ">=")
            return None
        # прочее (str/enum сравнения, вызовы) — неизвестно
        self._iv(node, env, annotate)
        return None

    @staticmethod
    def _cmp_iv(op: str, a: Iv, b: Iv):
        if op == "<":
            if a[1] < b[0]:
                return True
            if a[0] >= b[1]:
                return False
        elif op == "<=":
            if a[1] <= b[0]:
                return True
            if a[0] > b[1]:
                return False
        elif op == ">":
            if a[0] > b[1]:
                return True
            if a[1] <= b[0]:
                return False
        elif op == ">=":
            if a[0] >= b[1]:
                return True
            if a[1] < b[0]:
                return False
        elif op == "==":
            if a == b and a[0] == a[1]:
                return True
            if a[1] < b[0] or b[1] < a[0]:
                return False
        elif op == "!=":
            if a[1] < b[0] or b[1] < a[0]:
                return True
            if a == b and a[0] == a[1]:
                return False
        return None

    def _expr_equal(self, a, b) -> bool:
        """Синтаксическое равенство выражений (с точностью до
        коммутативности + и *). Name('result') раскрывается в выражение
        return. Корректно: обе стороны вычисляются в одном состоянии,
        параметры неизменяемы, вызовы не сравниваются (прозрачные
        касты char ↔ u8 разворачиваются)."""
        a, b = _uncast(a), _uncast(b)
        if (
            isinstance(a, ast.Name)
            and a.ident == "result"
            and self.ret_expr is not None
        ):
            return self._expr_equal(self.ret_expr, b)
        if (
            isinstance(b, ast.Name)
            and b.ident == "result"
            and self.ret_expr is not None
        ):
            return self._expr_equal(a, self.ret_expr)
        if type(a) is not type(b):
            return False
        if isinstance(a, ast.IntLit):
            return a.value == b.value
        if isinstance(a, ast.BoolLit):
            return a.value == b.value
        if isinstance(a, ast.CharLit):
            return a.value == b.value
        if isinstance(a, ast.Name):
            return a.ident == b.ident
        if isinstance(a, ast.SelfExpr):
            return True
        if isinstance(a, ast.FieldAccess):
            return a.name == b.name and self._expr_equal(a.obj, b.obj)
        if isinstance(a, ast.UnaryOp):
            return a.op == b.op and self._expr_equal(a.operand, b.operand)
        if isinstance(a, ast.BinOp):
            if a.op != b.op:
                return False
            if self._expr_equal(a.left, b.left) and self._expr_equal(
                a.right, b.right
            ):
                return True
            if a.op in ("+", "*"):
                return self._expr_equal(a.left, b.right) and self._expr_equal(
                    a.right, b.left
                )
            return False
        return False

    def _decompose(self, node):
        """Выражение как (путь, смещение): p, p + c, p - c, c + p."""
        p = _path_of(node)
        if p is not None:
            return (p, 0)
        if isinstance(node, ast.BinOp) and node.op in ("+", "-"):
            base = _path_of(node.left)
            step = node.right
            if base is None and node.op == "+":
                base = _path_of(node.right)
                step = node.left
            if base is None:
                return None
            c = self._const_of(step)
            if c is None:
                return None
            return (base, c if node.op == "+" else -c)
        return None

    def _decide_offset(self, env: State, dl, op: str, dr):
        """Решить p + a op q + b через разностные ограничения.
        Эквивалентно p + delta op q, где delta = a - b."""
        (p, a), (q, b) = dl, dr
        delta = a - b
        if p == q:  # p + delta op p — решается точно
            return {
                "<": delta < 0,
                "<=": delta <= 0,
                ">": delta > 0,
                ">=": delta >= 0,
                "==": delta == 0,
                "!=": delta != 0,
            }[op]
        cl = env.closure()
        dpq = cl.get((p, q))  # p <= q + dpq
        dqp = cl.get((q, p))  # q <= p + dqp
        # только доказательства (True); опровержения оставляем интервалам
        if op == "<=" and dpq is not None and dpq <= -delta:
            return True
        if op == "<" and dpq is not None and dpq <= -delta - 1:
            return True
        if op == ">=" and dqp is not None and dqp <= delta:
            return True
        if op == ">" and dqp is not None and dqp <= delta - 1:
            return True
        if (
            op == "=="
            and dpq is not None
            and dqp is not None
            and dpq <= -delta
            and dqp <= delta
        ):
            return True
        return None

    def _decide_rel(self, env: State, lp: str, op: str, rp: str):
        cl = env.closure()

        def le(x, y):
            return x == y or cl.get((x, y), 1) <= 0

        def lt(x, y):
            return cl.get((x, y), 1) <= -1

        if op == "<":
            if lt(lp, rp):
                return True
            if le(rp, lp):
                return False
        elif op == "<=":
            if le(lp, rp):
                return True
            if lt(rp, lp):
                return False
        elif op == ">":
            if lt(rp, lp):
                return True
            if le(lp, rp):
                return False
        elif op == ">=":
            if le(rp, lp):
                return True
            if lt(lp, rp):
                return False
        elif op == "==":
            if lp == rp or (le(lp, rp) and le(rp, lp)):
                return True
            if lt(lp, rp) or lt(rp, lp):
                return False
        elif op == "!=":
            if lt(lp, rp) or lt(rp, lp):
                return True
            if lp == rp:
                return False
        return None

    # --- интервалы выражений ------------------------------------------------

    def _iv(self, node, env: State, annotate: bool = True) -> Iv | None:
        ty = getattr(node, "ty", None)
        if isinstance(node, ast.IntLit):
            return (node.value, node.value)
        if isinstance(node, ast.CharLit):
            b = ord(node.value)  # лексер гарантирует один байт
            return (b, b)
        if isinstance(node, (ast.Name, ast.FieldAccess, ast.SelfExpr)):
            if isinstance(node, ast.Name) and node.ident == "result":
                return env.ivs.get("result") or self._ty_range(ty)
            if (
                isinstance(node, ast.Name)
                and node.ident in self.checker.consts
            ):
                _, value = self.checker.consts[node.ident]
                return (value, value)
            if isinstance(node, ast.FieldAccess) and isinstance(
                node.obj, ast.Name
            ):
                if node.obj.ident in self.checker.enums:
                    return None  # литерал enum — не число
            path = _path_of(node)
            if path is not None and path in env.ivs:
                return env.ivs[path]
            if isinstance(node, ast.FieldAccess):
                self._iv(node.obj, env, annotate)
                clamp = self._ty_range(ty)
                if clamp is not None:
                    inv = self.field_iv.get(
                        self._field_key(node, self.cur_struct)
                    )
                    if inv is not None:
                        return _inter(inv, clamp) or clamp
            return self._ty_range(ty)
        if isinstance(node, ast.UnaryOp):
            if node.op == "not":
                self._eval_bool(node, env, annotate)
                return None
            inner = self._iv(node.operand, env, annotate)
            if node.op == "~":
                # ~x = маска - x: линейно убывает, интервал точный
                mask = INT_RANGES[node.ty.kind][1]
                if inner is None:
                    return self._ty_range(node.ty)
                lo, hi = inner
                return (mask - hi, mask - lo)
            return self._arith(
                node, "-", (0, 0), inner, node.ty.kind, annotate
            )
        if isinstance(node, ast.BinOp):
            if node.op in ("and", "or"):
                self._eval_bool(node, env, annotate)
                return None
            left = self._iv(node.left, env, annotate)
            right = self._iv(node.right, env, annotate)
            if node.op in ("+", "-", "*", "/", "%"):
                kind = node.left.ty.kind
                # x * x неотрицателен
                lp, rp = _path_of(node.left), _path_of(node.right)
                if (
                    node.op == "*"
                    and lp is not None
                    and lp == rp
                    and left is not None
                ):
                    m = max(abs(left[0]), abs(left[1]))
                    return self._square(node, (0, m * m), kind, annotate)
                # a - b при известном b <= a не уходит ниже нуля
                floor_zero = False
                if node.op == "-" and lp is not None and rp is not None:
                    floor_zero = (
                        lp == rp or env.closure().get((rp, lp), 1) <= 0
                    )
                return self._arith(
                    node,
                    node.op,
                    left,
                    right,
                    kind,
                    annotate,
                    env=env,
                    floor_zero=floor_zero,
                )
            if node.op in ("&", "|", "^", "<<", ">>"):
                return self._bitwise(
                    node, node.op, left, right, node.left.ty.kind, annotate
                )
            return None  # сравнение в числовом контексте не встречается
        if isinstance(node, ast.Call):
            return self._iv_call(node, env, annotate)
        if isinstance(node, ast.MethodCall):
            return self._iv_method(node, env, annotate)
        if isinstance(node, ast.Index):
            self._iv(node.obj, env, annotate)
            idx = self._iv(node.index, env, annotate)
            if annotate:
                oty = node.obj.ty
                ok = (
                    isinstance(oty, ArrayType)
                    and idx is not None
                    and idx[0] >= 0
                    and idx[1] < oty.size
                )
                self._mark("bounds", node, ok)
            clamp = self._ty_range(ty)
            if clamp is not None:
                # чтение из пула с инвариантом уже интервала типа
                pkey = self._pool_key(node, self.cur_fn_key, self.cur_struct)
                inv = self.pool_iv.get(pkey) if pkey is not None else None
                if inv is not None:
                    sent = self.pool_sent.get(pkey)
                    dense = _inter(inv, clamp) or clamp
                    if sent is None:
                        return dense
                    # значение вида dense ∪ {sent}: наружу — hull,
                    # дырка запоминается для guard'а `!= NONE`
                    self._hole = (id(node), dense, sent)
                    return _inter(_hull(inv, (sent, sent)), clamp) or clamp
            return clamp
        if isinstance(node, ast.StrLit):
            for seg in node.segments:
                if not isinstance(seg, str):
                    self._iv(seg, env, annotate)
            return None
        if isinstance(node, ast.StructLit):
            ftypes = self.checker.structs[node.name].fields
            for fname, fexpr in node.fields:
                fiv = self._iv(fexpr, env, annotate)
                fty = ftypes.get(fname)
                if isinstance(fty, ArrayType):
                    self._store_array((node.name, fname), fexpr, env)
                else:
                    tiv = _ty_iv(fty)
                    if tiv is not None:
                        self._note_field(
                            (node.name, fname),
                            fiv if fiv is not None else tiv,
                        )
            return None
        if isinstance(node, ast.ArrayLit):
            for e in node.elems:
                self._iv(e, env, annotate)
            return None
        if isinstance(node, ast.ArrayFill):
            self._iv(node.value, env, annotate)
            return None
        return self._ty_range(ty)

    def _ty_range(self, ty) -> Iv | None:
        return _ty_iv(ty)

    def _square(self, node, iv: Iv, kind: str, annotate: bool) -> Iv:
        clamp = _range(kind)
        if annotate:
            self._mark("overflow", node, iv[1] <= clamp[1])
        return _inter(iv, clamp) or clamp

    def _arith(
        self,
        node,
        op: str,
        left,
        right,
        kind: str,
        annotate: bool,
        env: State | None = None,
        floor_zero: bool = False,
    ) -> Iv | None:
        clamp = _range(kind)
        if left is None or right is None:
            if annotate and op in ("+", "-", "*"):
                self._mark("overflow", node, False)
            if annotate and op in ("/", "%"):
                self._mark("div", node, False)
            return clamp
        if op == "+":
            raw: Iv = (left[0] + right[0], left[1] + right[1])
        elif op == "-":
            raw = (left[0] - right[1], left[1] - right[0])
            if floor_zero:
                raw = (max(raw[0], 0), max(raw[1], 0))
        elif op == "*":
            products = [
                left[0] * right[0],
                left[0] * right[1],
                left[1] * right[0],
                left[1] * right[1],
            ]
            raw = (min(products), max(products))
        elif op == "/":
            return self._div(node, left, right, clamp, annotate, env)
        else:  # %
            return self._mod(node, left, right, clamp, annotate, env)
        if annotate:
            ok = clamp[0] <= raw[0] and raw[1] <= clamp[1]
            self._mark("overflow", node, ok)
        return _inter(raw, clamp) or clamp

    def _div_ok(
        self, node, left: Iv, right: Iv, kind: str, env: State | None
    ) -> bool:
        zero_free = right[0] > 0 or right[1] < 0
        if not zero_free and env is not None:
            # путь делителя известен как ненулевой (например, из
            # requires b != 0)
            rpath = _path_of(node.right)
            zero_free = rpath is not None and rpath in env.nz
        if not zero_free:
            return False
        if kind in ("i32", "i64"):
            lo, _ = _range(kind)
            if left[0] <= lo and right[0] <= -1 <= right[1]:
                return False
        return True

    def _div(self, node, left: Iv, right: Iv, clamp, annotate, env) -> Iv:
        safe = self._div_ok(node, left, right, node.left.ty.kind, env)
        if annotate:
            self._mark("div", node, safe)
        if not safe or (right[0] <= 0 <= right[1]):
            # интервал делителя содержит 0 (безопасность доказана
            # через nz) — точные частные не вычислить
            return clamp
        quotients = [
            _tdiv(left[0], right[0]),
            _tdiv(left[0], right[1]),
            _tdiv(left[1], right[0]),
            _tdiv(left[1], right[1]),
        ]
        raw = (min(quotients + [0]), max(quotients + [0]))
        return _inter(raw, clamp) or clamp

    def _mod(self, node, left: Iv, right: Iv, clamp, annotate, env) -> Iv:
        safe = self._div_ok(node, left, right, node.left.ty.kind, env)
        if annotate:
            self._mark("div", node, safe)
        if not safe or (right[0] <= 0 <= right[1]):
            return clamp
        bound = max(abs(right[0]), abs(right[1])) - 1
        lo = 0 if left[0] >= 0 else -bound
        return _inter((lo, bound), clamp) or clamp

    def _bitwise(self, node, op: str, left, right, kind: str, annotate) -> Iv:
        """Битовые операции беззнаковых. & | ^ тотальны; интервалы —
        из неравенств a&b <= min(a,b), max(a,b) <= a|b <= a+b,
        a^b <= a+b (верны для неотрицательных). Сдвиги: << — умножение
        на 2^n с проверкой переполнения, >> — деление (тотален);
        сдвиг на ширину типа и больше — trap (свой вид проверки)."""
        clamp = _range(kind)
        if op in ("<<", ">>"):
            width = {"u8": 8, "u16": 16, "u64": 64}.get(kind, 32)
            shift_ok = right is not None and right[1] < width
            if annotate:
                self._mark("shift", node, shift_ok)
            if op == "<<" and annotate:
                self._mark(
                    "overflow",
                    node,
                    shift_ok
                    and left is not None
                    and left[1] * 2 ** right[1] <= clamp[1],
                )
            if not shift_ok or left is None:
                return clamp
            if op == "<<":
                raw = (left[0] * 2 ** right[0], left[1] * 2 ** right[1])
            else:
                raw = (left[0] // 2 ** right[1], left[1] // 2 ** right[0])
            return _inter(raw, clamp) or clamp
        if left is None or right is None:
            return clamp
        if left[0] == left[1] and right[0] == right[1]:
            # обе стороны — константы: точное значение
            exact = {"&": left[0] & right[0], "|": left[0] | right[0]}.get(
                op, left[0] ^ right[0]
            )
            return (exact, exact)
        if op == "&":
            raw = (0, min(left[1], right[1]))
        elif op == "|":
            raw = (max(left[0], right[0]), min(left[1] + right[1], clamp[1]))
        else:  # ^
            raw = (0, min(left[1] + right[1], clamp[1]))
        return _inter(raw, clamp) or clamp

    # --- вызовы --------------------------------------------------------------

    def _call_env(self, sig, node, env: State, obj_path: str | None) -> State:
        call_env = State()
        for (pname, _), arg in zip(sig.params, node.args):
            arg_iv = self._iv(arg, env, annotate=False)
            if arg_iv is not None:
                call_env.ivs[pname] = arg_iv
        if obj_path is not None:
            prefix = obj_path + "."
            for k, v in env.ivs.items():
                if k == obj_path:
                    call_env.ivs["self"] = v
                elif k.startswith(prefix):
                    call_env.ivs["self." + k[len(prefix) :]] = v
        return call_env

    def _check_requires(self, key, func, sig, node, env, obj_path=None):
        if func is None or func.requires is None:
            return
        call_env = self._call_env(sig, node, env, obj_path)
        ok = self._eval_bool(func.requires, call_env, annotate=False)
        if self._probe:
            return  # проба не считает requires-сайты
        entry = self.req_sites.setdefault(key, [0, 0])
        entry[1] += 1
        entry[0] += 1 if ok is True else 0

    def _assume_ensures(
        self, env: State, func, sig, call, bind: str, obj_path
    ) -> None:
        """Модульный контракт: после вызова ensures функции истинен —
        либо доказан статически, либо проверен trap'ом внутри неё.
        Конъюнкты-сравнения переводятся в термины вызывающего: сторона —
        путь со смещением (result, параметр, p ± c, в том числе
        арифметика вида `pos + width`) либо интервал. Путь-путь даёт
        разностный факт, путь-интервал — подрезку границ (bind — имя
        связываемой переменной)."""
        if func is None or func.ensures is None:
            return
        subst = {p: a for (p, _), a in zip(sig.params, call.args)}
        mirror = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "=="}
        for conj in _conjuncts(func.ensures):
            if not isinstance(conj, ast.BinOp) or conj.op not in mirror:
                continue
            left = self._map_side(conj.left, subst, bind, obj_path, env)
            right = self._map_side(conj.right, subst, bind, obj_path, env)
            if left is None or right is None:
                continue
            op = conj.op
            if left[0] == "off" and right[0] == "off":
                _, lp, lc = left
                _, rp, rc = right
                if lp != rp:
                    env.relate_offset(lp, op, rp, rc - lc)
                riv = env.ivs.get(rp)
                if riv is not None:
                    self._refine_path_iv(
                        env, lp, op, (riv[0] + rc - lc, riv[1] + rc - lc)
                    )
                liv = env.ivs.get(lp)
                if liv is not None:
                    self._refine_path_iv(
                        env,
                        rp,
                        mirror[op],
                        (liv[0] + lc - rc, liv[1] + lc - rc),
                    )
            elif left[0] == "off" and right[0] == "iv":
                _, lp, lc = left
                iv = right[1]
                self._refine_path_iv(env, lp, op, (iv[0] - lc, iv[1] - lc))
            elif left[0] == "iv" and right[0] == "off":
                iv = left[1]
                _, rp, rc = right
                self._refine_path_iv(
                    env, rp, mirror[op], (iv[0] - rc, iv[1] - rc)
                )

    def _map_side(self, e, subst: dict, bind: str, obj_path, env: State):
        """Сторона конъюнкта ensures в терминах вызывающего:
        ("off", путь, c) — путь + c | ("iv", интервал) | None."""
        if isinstance(e, ast.IntLit):
            return ("iv", (e.value, e.value))
        if isinstance(e, ast.Name):
            if e.ident == "result":
                # bind is None — вызов без связывания результата
                return ("off", bind, 0) if bind is not None else None
            if e.ident in self.checker.consts:
                v = self.checker.consts[e.ident][1]
                return ("iv", (v, v))
            if e.ident in subst:
                arg = subst[e.ident]
                d = self._decompose(arg)
                if d is not None:
                    return ("off", d[0], d[1])
                iv = self._iv(arg, env, annotate=False)
                return ("iv", iv) if iv is not None else None
            return None
        if isinstance(e, ast.BinOp) and e.op in ("+", "-"):
            left = self._map_side(e.left, subst, bind, obj_path, env)
            right = self._map_side(e.right, subst, bind, obj_path, env)
            if left is None or right is None:
                return None
            return self._combine_sides(e.op, left, right, env)
        p = _path_of(e)  # self.поле в ensures метода
        if p is not None and obj_path is not None:
            if p == "self":
                return ("off", obj_path, 0)
            if p.startswith("self."):
                return ("off", obj_path + p[len("self") :], 0)
        return None

    def _combine_sides(self, op: str, left, right, env: State):
        """Сумма/разность сторон: путь ± константа остаётся путём со
        смещением (реляционно), иначе — интервальная арифметика."""
        if (
            left[0] == "off"
            and right[0] == "iv"
            and right[1][0] == right[1][1]
        ):
            c = right[1][0]
            return ("off", left[1], left[2] + (c if op == "+" else -c))
        if (
            op == "+"
            and left[0] == "iv"
            and left[1][0] == left[1][1]
            and right[0] == "off"
        ):
            return ("off", right[1], right[2] + left[1][0])
        liv = self._side_iv(left, env)
        riv = self._side_iv(right, env)
        if liv is None or riv is None:
            return None
        if op == "+":
            return ("iv", (liv[0] + riv[0], liv[1] + riv[1]))
        return ("iv", (liv[0] - riv[1], liv[1] - riv[0]))

    def _side_iv(self, side, env: State) -> Iv | None:
        if side[0] == "iv":
            return side[1]
        iv = env.ivs.get(side[1])
        return (iv[0] + side[2], iv[1] + side[2]) if iv is not None else None

    def _refine_path_iv(self, env: State, path: str, op: str, oiv: Iv) -> None:
        cur = env.ivs.get(path)
        if cur is None:
            if op == "==":  # точный факт восстанавливает интервал
                env.ivs[path] = oiv
            return
        if op == "<":
            new = _inter(cur, (cur[0], oiv[1] - 1))
        elif op == "<=":
            new = _inter(cur, (cur[0], oiv[1]))
        elif op == ">":
            new = _inter(cur, (oiv[0] + 1, cur[1]))
        elif op == ">=":
            new = _inter(cur, (oiv[0], cur[1]))
        else:  # ==
            new = _inter(cur, oiv)
        if new is not None:
            env.ivs[path] = new

    def _contract_iv(self, func, sig, node, env: State, obj_path=None):
        """SPARK-граница модулей (MODULES_PLAN §6): через границу виден
        только объявленный контракт — интервал результата это диапазон
        типа, обрезанный конъюнктами ensures; body-summary не проходит."""
        base = self._ty_range(node.ty)
        if base is None or func is None or func.ensures is None:
            return base
        tmp = env.copy()
        tmp.ivs["$result"] = base
        self._assume_ensures(tmp, func, sig, node, "$result", obj_path)
        return tmp.ivs.get("$result", base)

    def _apply_summary(self, key: str, sig, node, env: State):
        summary = self.summaries.get(key)
        base = self._ty_range(node.ty)
        if summary is None:
            return base
        tag = summary[0]
        if tag == "iv":
            return summary[1]
        if tag == "hive":
            # dense ∪ {sent}: наружу — hull, дырка для guard'а != NONE
            _, dense, sent = summary
            self._hole = (id(node), dense, sent)
            full = _hull(dense, (sent, sent))
            return (_inter(full, base) or base) if base is not None else full
        # тождество параметру: интервал аргумента проходит сквозь вызов
        pname = summary[1]
        for (name, _), arg in zip(sig.params, node.args):
            if name != pname:
                continue
            arg_iv = self._iv(arg, env, annotate=False)
            if arg_iv is not None and base is not None:
                return _inter(arg_iv, base) or base
        return base

    def _iv_call(self, node: ast.Call, env: State, annotate: bool):
        for arg in node.args:
            self._iv(arg, env, annotate)
        name = node.name
        if name == "char" or (
            name == "u8"
            and isinstance(getattr(node.args[0], "ty", None), CharType)
        ):
            # char ↔ u8 тотален (тот же байт) — обязательства нет,
            # интервал аргумента проходит сквозь каст
            src = self._iv(node.args[0], env, annotate=False)
            if src is None:
                return _CHAR_IV
            return _inter(src, _CHAR_IV) or _CHAR_IV
        if name in _CASTS:
            src = self._iv(node.args[0], env, annotate=False)
            clamp = _range(name)
            if annotate:
                ok = (
                    src is not None
                    and clamp[0] <= src[0]
                    and src[1] <= clamp[1]
                )
                self._mark("cast", node, ok)
            return (_inter(src, clamp) if src is not None else clamp) or clamp
        if name == "len":
            aty = node.args[0].ty
            if isinstance(aty, ArrayType):
                return (aty.size, aty.size)
            if isinstance(aty, StrType) and aty.capacity is not None:
                return (0, aty.capacity)
            return (0, 4096)
        if name in ("arg_len", "arg_byte"):
            # границы argv (i < arg_count(), j < arg_len(i)): размеры
            # известны только в рантайме — обязательство bounds всегда
            # остаётся в рантайме (как индекс массива без сужения)
            if annotate:
                self._mark("bounds", node, False)
            return self._ty_range(node.ty)
        if name == "write_span":
            # граница вызова: off + len <= N — то же обязательство
            # bounds, что у индексации (codegen: node.in_bounds)
            off = self._iv(node.args[1], env, annotate=False)
            ln = self._iv(node.args[2], env, annotate=False)
            if annotate:
                size = getattr(node, "arr_size", None)
                ok = (
                    size is not None
                    and off is not None
                    and ln is not None
                    and off[0] >= 0
                    and ln[0] >= 0
                    and off[1] + ln[1] <= size
                )
                self._mark("bounds", node, ok)
            return None
        if name in self.checker.funcs:
            func, _ = self._func_by_key(name)
            sig = self.checker.funcs[name]
            self._check_requires(name, func, sig, node, env)
            if self._module_of(name) != self.cur_module:
                return self._contract_iv(func, sig, node, env)
            return self._apply_summary(name, sig, node, env)
        return self._ty_range(node.ty)

    def _iv_method(self, node: ast.MethodCall, env: State, annotate: bool):
        self._iv(node.obj, env, annotate)
        for arg in node.args:
            self._iv(arg, env, annotate)
        if getattr(node, "enum_ctor", None) is not None:
            return None  # конструктор enum — не вызов
        key = f"{node.struct}.{node.name}"
        func, _ = self._func_by_key(key)
        sig = self.checker.structs[node.struct].methods[node.name]
        self._check_requires(
            key, func, sig, node, env, obj_path=_path_of(node.obj)
        )
        if sig.var_self:
            # метод мутирует получателя — факты о нём устаревают
            p = _path_of(node.obj)
            if p is not None:
                env.kill(p)
        if self._module_of(key) != self.cur_module:
            return self._contract_iv(
                func, sig, node, env, obj_path=_path_of(node.obj)
            )
        return self._apply_summary(key, sig, node, env)


def verify(program: ast.Program, checker) -> dict:
    return Verifier(program, checker).run()
