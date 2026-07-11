"""Статическая верификация EATLang: интервальный + реляционный анализ.

Этап 2 контрактов из SPEC.md §5.2: то, что доказано на этапе
компиляции, удаляется из бинарника. Анализ консервативен: недоказанная
проверка остаётся runtime-trap'ом — ложных «доказательств» не бывает.

Что доказывается:
  - отсутствие переполнения (+ - * и унарный минус);
  - деление на ноль (и краевой случай INT_MIN / -1);
  - выход за границы массива;
  - допустимость сужающих преобразований i32()/u32()/u8();
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
_CASTS = ("i32", "u32", "u8")
_CHAR_IV: Iv = (0, 255)  # char — ровно один байт


def _range(kind: str) -> Iv:
    return INT_RANGES[kind]


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


class State:
    """Абстрактное состояние: интервалы путей + разностные ограничения
    путей + пути, известные как ненулевые."""

    __slots__ = ("ivs", "rels", "nz")

    def __init__(self, ivs=None, rels=None, nz=None):
        self.ivs: dict[str, Iv] = dict(ivs or {})
        # (p, q) -> d: факт p <= q + d (минимальное известное d)
        self.rels: dict[tuple[str, str], int] = dict(rels or {})
        self.nz: set[str] = set(nz or ())  # пути со значением != 0

    def copy(self) -> "State":
        return State(self.ivs, self.rels, self.nz)

    def kill(self, path: str) -> None:
        for k in list(self.ivs):
            if k == path or k.startswith(path + "."):
                del self.ivs[k]

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
        self.param_names: set = set()
        self.returns: list = []
        self.ret_syms: list = []
        self.ensures_ok: list = []
        self.ret_expr = None  # выражение текущего return для ensures

    # --- отметки и статистика ---------------------------------------------

    def _mark(self, kind: str, node, ok: bool) -> None:
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
        order = self._topo_order()
        for key in order:
            func, struct = self._func_by_key(key)
            if func is not None:
                self._analyze_func(func, key, struct)
        for decl in self.program.decls:
            if isinstance(decl, ast.TestBlock):
                self.cur_func = None
                self.cur_sig = None
                self.param_names = set()
                self.returns = []
                self.ret_syms = []
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
        return self.stats()

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
        self.param_names = {p for p, _ in sig.params}
        self.returns = []
        self.ret_syms = []
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
        summary = ivs[0]
        for r in ivs[1:]:
            summary = _hull(summary, r)
        clamped = _inter(summary, _range(sig.ret.kind))
        return ("iv", clamped) if clamped is not None else None

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
            elif isinstance(stmt.value, ast.MethodCall):
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
            if isinstance(stmt.target, ast.Index):
                # границы цели присваивания тоже проверяются
                self._iv(stmt.target, env)
            path = _path_of(stmt.target)
            if path is not None:
                env.kill(path)
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
            self.returns.append(riv)
            self.ret_syms.append(
                self._ret_sym(stmt.value) if stmt.value is not None else None
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
            if not _block_returns(block):
                branches.append(out)
            self._refine(neg_env, cond, False)
        if stmt.els is not None:
            out = self._flow_block(stmt.els, neg_env)
            if not _block_returns(stmt.els):
                branches.append(out)
        else:
            branches.append(neg_env)
        return self._join(branches)

    def _flow_for(self, stmt: ast.ForStmt, env: State) -> State:
        if stmt.bounds is not None:
            start, end = stmt.bounds
            n = end - start
        else:
            self._iv(stmt.iterable, env)
            ity = stmt.iterable.ty
            n = ity.size if isinstance(ity, ArrayType) else None
        accel = self._accelerate(stmt.body) if n is not None else {}
        body_env = env.copy()
        after: dict[str, Iv] = {}
        for p in _assigned_paths(stmt.body):
            v0 = env.ivs.get(p)
            body_env.kill(p)
            info = accel.get(p)
            if info is None or v0 is None:
                continue
            # ускорение: p меняется на d за итерацию, значение на входе
            # итерации k — v0 + k*d, k ∈ [0, n-1]
            d, cond, kind, glo, ghi = info
            clamp = _range(kind)
            b_lo = v0[0] + min(0, (n - 1) * d)
            b_hi = v0[1] + max(0, (n - 1) * d)
            a_lo = v0[0] + (min(0, n * d) if cond else n * d)
            a_hi = v0[1] + (max(0, n * d) if cond else n * d)
            # охрана: обновление срабатывает только при p ≤ ghi
            # (p ≥ glo), значит значения не превышают max(v0, ghi + d)
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
                body_env.ivs[stmt.target] = (start, end - 1)
                if stmt.target != "_":
                    self._lockstep(stmt, accel, env, body_env, start)
        else:
            eiv = _ty_iv(stmt.elem_ty)
            if eiv is not None:
                body_env.ivs[stmt.target] = eiv
        self._flow_block(stmt.body, body_env)
        out = body_env.copy()
        out.kill(stmt.target)
        for p, iv in after.items():
            out.kill(p)
            out.ivs[p] = iv
        return out

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
            return self._ty_range(ty)
        if isinstance(node, ast.UnaryOp):
            if node.op == "not":
                self._eval_bool(node, env, annotate)
                return None
            inner = self._iv(node.operand, env, annotate)
            return self._arith(node, "-", (0, 0), inner, "i32", annotate)
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
            return self._ty_range(ty)
        if isinstance(node, ast.StrLit):
            for seg in node.segments:
                if not isinstance(seg, str):
                    self._iv(seg, env, annotate)
            return None
        if isinstance(node, ast.StructLit):
            for _, fexpr in node.fields:
                self._iv(fexpr, env, annotate)
            return None
        if isinstance(node, ast.ArrayLit):
            for e in node.elems:
                self._iv(e, env, annotate)
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
        if kind == "i32":
            lo, _ = _range("i32")
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
            int(left[0] / right[0]),
            int(left[0] / right[1]),
            int(left[1] / right[0]),
            int(left[1] / right[1]),
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
                return ("off", bind, 0)
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

    def _apply_summary(self, key: str, sig, node, env: State):
        summary = self.summaries.get(key)
        base = self._ty_range(node.ty)
        if summary is None:
            return base
        tag = summary[0]
        if tag == "iv":
            return summary[1]
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
        if name in self.checker.funcs:
            func, _ = self._func_by_key(name)
            sig = self.checker.funcs[name]
            self._check_requires(name, func, sig, node, env)
            return self._apply_summary(name, sig, node, env)
        return self._ty_range(node.ty)

    def _iv_method(self, node: ast.MethodCall, env: State, annotate: bool):
        self._iv(node.obj, env, annotate)
        for arg in node.args:
            self._iv(arg, env, annotate)
        key = f"{node.struct}.{node.name}"
        func, _ = self._func_by_key(key)
        sig = self.checker.structs[node.struct].methods[node.name]
        self._check_requires(
            key, func, sig, node, env, obj_path=_path_of(node.obj)
        )
        return self._apply_summary(key, sig, node, env)


def verify(program: ast.Program, checker) -> dict:
    return Verifier(program, checker).run()
