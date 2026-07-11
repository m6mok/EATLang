"""Статическая верификация EATLang: интервальный анализ целых.

Этап 2 контрактов из SPEC.md §5.2: то, что доказано на этапе
компиляции, удаляется из бинарника. Анализ консервативен: недоказанная
проверка остаётся runtime-trap'ом — ложных «доказательств» не бывает.

Что доказывается:
  - отсутствие переполнения (+ - * и унарный минус);
  - деление на ноль (и краевой случай INT_MIN / -1);
  - выход за границы массива;
  - допустимость сужающих преобразований i32()/u32()/u8();
  - requires на каждом месте вызова (снятие проверки — только если
    доказаны ВСЕ вызовы функции);
  - ensures на каждом return;
  - assert.

Механика: функции обходятся в топологическом порядке DAG вызовов
(рекурсии нет — правило 1), интервал результата функции служит
summary для вызывающих. Ключ интервала — путь: имя, self.поле,
переменная.поле. Присваивание в цикле расширяет интервал до диапазона
типа (widening без итерации до фиксированной точки — грубо, но
корректно). Семантика «после trap'а»: выживший результат операции
всегда в диапазоне типа, поэтому интервалы пересекаются с ним.
"""

from . import ast_nodes as ast
from .types import INT_RANGES, IntType

Iv = tuple[int, int]


def _range(kind: str) -> Iv:
    return INT_RANGES[kind]


def _inter(a: Iv, b: Iv) -> Iv | None:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if lo <= hi else None


def _hull(a: Iv, b: Iv) -> Iv:
    return (min(a[0], b[0]), max(a[1], b[1]))


def _path_of(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.ident
    if isinstance(node, ast.SelfExpr):
        return "self"
    if isinstance(node, ast.FieldAccess):
        base = _path_of(node.obj)
        return f"{base}.{node.name}" if base is not None else None
    return None


def _has_call(node) -> bool:
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


class Verifier:
    def __init__(self, program: ast.Program, checker):
        self.program = program
        self.checker = checker
        self.summaries: dict[str, Iv | None] = {}
        self.req_sites: dict[str, list] = {}  # key -> [proven, total]
        # (kind, id(node)) -> [bool, node] c AND-слиянием повторных оценок
        self.checks: dict[tuple, list] = {}
        self.cur_func: ast.FuncDecl | None = None
        self.cur_sig = None
        self.returns: list = []
        self.ensures_ok: list = []

    # --- отметки и статистика -------------------------------------------

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

    # --- запуск -------------------------------------------------------------

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
                self.returns = []
                self.ensures_ok = []
                self._flow_block(decl.body, {})
        # requires снимается только если доказаны все вызовы
        for key in order:
            func, _ = self._func_by_key(key)
            if func is None or func.requires is None:
                continue
            proven, total = self.req_sites.get(key, [0, 0])
            no_calls = not _has_call(func.requires)
            # тавтология (например, `requires true`) верна без вызовов
            tautology = (
                self._eval_bool(func.requires, {}, annotate=False) is True
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
        self.returns = []
        self.ensures_ok = []
        env: dict[str, Iv] = {}
        for pname, ptype in sig.params:
            if isinstance(ptype, IntType):
                env[pname] = _range(ptype.kind)
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
        ret_ivs = [r for r in self.returns if r is not None]
        if (
            isinstance(sig.ret, IntType)
            and ret_ivs
            and len(ret_ivs) == len(self.returns)
        ):
            summary = ret_ivs[0]
            for r in ret_ivs[1:]:
                summary = _hull(summary, r)
            self.summaries[key] = _inter(summary, _range(sig.ret.kind))
        else:
            self.summaries[key] = None

    # --- поток управления ----------------------------------------------------

    def _flow_block(self, block: ast.Block, env: dict) -> dict:
        env = dict(env)
        for stmt in block.stmts:
            env = self._flow_stmt(stmt, env)
        return env

    def _kill(self, env: dict, path: str) -> None:
        for k in list(env):
            if k == path or k.startswith(path + "."):
                del env[k]

    def _flow_stmt(self, stmt, env: dict) -> dict:
        if isinstance(stmt, ast.LetStmt):
            value = self._iv(stmt.value, env)
            if isinstance(stmt.var_ty, IntType):
                clamp = _range(stmt.var_ty.kind)
                env[stmt.name] = (
                    (_inter(value, clamp) or clamp)
                    if value is not None
                    else clamp
                )
            if isinstance(stmt.value, ast.StructLit):
                for fname, fexpr in stmt.value.fields:
                    fiv = self._iv(fexpr, env)
                    if fiv is not None:
                        env[f"{stmt.name}.{fname}"] = fiv
            return env
        if isinstance(stmt, ast.AssignStmt):
            value = self._iv(stmt.value, env)
            path = _path_of(stmt.target)
            if path is not None:
                self._kill(env, path)
                tty = stmt.target.ty
                if isinstance(tty, IntType) and value is not None:
                    clamped = _inter(value, _range(tty.kind))
                    if clamped is not None:
                        env[path] = clamped
            return env
        if isinstance(stmt, ast.IfStmt):
            return self._flow_if(stmt, env)
        if isinstance(stmt, ast.ForStmt):
            return self._flow_for(stmt, env)
        if isinstance(stmt, ast.LoopStmt):
            body_env = dict(env)
            for p in _assigned_paths(stmt.body):
                self._kill(body_env, p)
            self._flow_block(stmt.body, body_env)
            return body_env
        if isinstance(stmt, ast.MatchStmt):
            return self._flow_match(stmt, env)
        if isinstance(stmt, ast.ReturnStmt):
            riv = self._iv(stmt.value, env) if stmt.value is not None else None
            self.returns.append(riv)
            func = self.cur_func
            if func is not None and func.ensures is not None:
                env_r = dict(env)
                if riv is not None:
                    env_r["result"] = riv
                elif stmt.value is not None:
                    env_r.pop("result", None)
                ok = self._eval_bool(func.ensures, env_r)
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

    def _flow_if(self, stmt: ast.IfStmt, env: dict) -> dict:
        branches = []
        conds = [stmt.cond] + [c for c, _ in stmt.elifs]
        blocks = [stmt.then] + [b for _, b in stmt.elifs]
        neg_env = dict(env)
        for cond, block in zip(conds, blocks):
            self._eval_bool(cond, neg_env)  # аннотации внутри условия
            b_env = dict(neg_env)
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

    def _flow_for(self, stmt: ast.ForStmt, env: dict) -> dict:
        body_env = dict(env)
        for p in _assigned_paths(stmt.body):
            self._kill(body_env, p)
        if stmt.bounds is not None:
            start, end = stmt.bounds
            body_env[stmt.target] = (start, end - 1)
        else:
            self._iv(stmt.iterable, body_env)
            if isinstance(stmt.elem_ty, IntType):
                body_env[stmt.target] = _range(stmt.elem_ty.kind)
        self._flow_block(stmt.body, body_env)
        out = dict(body_env)
        out.pop(stmt.target, None)
        return out

    def _flow_match(self, stmt: ast.MatchStmt, env: dict) -> dict:
        self._iv(stmt.subject, env)
        branches = []
        for arm in stmt.arms:
            a_env = dict(env)
            if arm.binding is not None and isinstance(arm.payload_ty, IntType):
                a_env[arm.binding] = _range(arm.payload_ty.kind)
            out = self._flow_block(arm.body, a_env)
            if not _block_returns(arm.body):
                branches.append(out)
        return self._join(branches) if branches else env

    def _join(self, envs: list) -> dict:
        if not envs:
            return {}
        keys = set(envs[0])
        for e in envs[1:]:
            keys &= set(e)
        joined = {}
        for k in keys:
            iv = envs[0][k]
            for e in envs[1:]:
                iv = _hull(iv, e[k])
            joined[k] = iv
        return joined

    # --- уточнение по условиям ----------------------------------------------

    def _refine(self, env: dict, cond, assume: bool) -> None:
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
        if op is None or op not in ("<", "<=", ">", ">=", "=="):
            return
        self._refine_cmp(env, cond.left, op, cond.right)
        mirror = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "=="}
        self._refine_cmp(env, cond.right, mirror[op], cond.left)

    def _refine_cmp(self, env: dict, target, op: str, other) -> None:
        path = _path_of(target)
        if path is None or not isinstance(
            getattr(target, "ty", None), IntType
        ):
            return
        oiv = self._iv(other, env, annotate=False)
        if oiv is None:
            return
        cur = env.get(path, _range(target.ty.kind))
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
            env[path] = new

    # --- трёхзначная логика --------------------------------------------------

    def _eval_bool(self, node, env: dict, annotate: bool = True):
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
            if left is None or right is None:
                return None
            return self._cmp_iv(node.op, left, right)
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

    # --- интервалы выражений -----------------------------------------------

    def _iv(self, node, env: dict, annotate: bool = True) -> Iv | None:
        ty = getattr(node, "ty", None)
        if isinstance(node, ast.IntLit):
            return (node.value, node.value)
        if isinstance(node, (ast.Name, ast.FieldAccess, ast.SelfExpr)):
            if isinstance(node, ast.Name) and node.ident == "result":
                return env.get("result") or self._ty_range(ty)
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
            if path is not None and path in env:
                return env[path]
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
                    left_sq: Iv = (0, m * m)
                    return self._square(node, left_sq, kind, annotate)
                return self._arith(node, node.op, left, right, kind, annotate)
            return None  # сравнение в числовом контексте не встречается
        if isinstance(node, ast.Call):
            return self._iv_call(node, env, annotate)
        if isinstance(node, ast.MethodCall):
            return self._iv_method(node, env, annotate)
        if isinstance(node, ast.Index):
            self._iv(node.obj, env, annotate)
            idx = self._iv(node.index, env, annotate)
            if annotate:
                from .types import ArrayType

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
        return _range(ty.kind) if isinstance(ty, IntType) else None

    def _square(self, node, iv: Iv, kind: str, annotate: bool) -> Iv:
        clamp = _range(kind)
        if annotate:
            self._mark("overflow", node, iv[1] <= clamp[1])
        return _inter(iv, clamp) or clamp

    def _arith(
        self, node, op: str, left, right, kind: str, annotate: bool
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
        elif op == "*":
            products = [
                left[0] * right[0],
                left[0] * right[1],
                left[1] * right[0],
                left[1] * right[1],
            ]
            raw = (min(products), max(products))
        elif op == "/":
            return self._div(node, left, right, clamp, annotate)
        else:  # %
            return self._mod(node, left, right, clamp, annotate)
        if annotate:
            ok = clamp[0] <= raw[0] and raw[1] <= clamp[1]
            self._mark("overflow", node, ok)
        return _inter(raw, clamp) or clamp

    def _div_ok(self, left: Iv, right: Iv, kind: str) -> bool:
        if right[0] <= 0 <= right[1]:
            return False
        if kind == "i32":
            lo, _ = _range("i32")
            if left[0] <= lo and right[0] <= -1 <= right[1]:
                return False
        return True

    def _div(self, node, left: Iv, right: Iv, clamp, annotate) -> Iv:
        safe = self._div_ok(left, right, node.left.ty.kind)
        if annotate:
            self._mark("div", node, safe)
        if not safe:
            return clamp
        quotients = [
            int(left[0] / right[0]),
            int(left[0] / right[1]),
            int(left[1] / right[0]),
            int(left[1] / right[1]),
        ]
        raw = (min(quotients + [0]), max(quotients + [0]))
        return _inter(raw, clamp) or clamp

    def _mod(self, node, left: Iv, right: Iv, clamp, annotate) -> Iv:
        safe = self._div_ok(left, right, node.left.ty.kind)
        if annotate:
            self._mark("div", node, safe)
        if not safe:
            return clamp
        bound = max(abs(right[0]), abs(right[1])) - 1
        lo = 0 if left[0] >= 0 else -bound
        return _inter((lo, bound), clamp) or clamp

    # --- вызовы --------------------------------------------------------------

    def _call_env(self, sig, node, env: dict, obj_path: str | None) -> dict:
        call_env: dict[str, Iv] = {}
        for (pname, _), arg in zip(sig.params, node.args):
            arg_iv = self._iv(arg, env, annotate=False)
            if arg_iv is not None:
                call_env[pname] = arg_iv
        if obj_path is not None:
            for k, v in env.items():
                if k == obj_path:
                    call_env["self"] = v
                elif k.startswith(obj_path + "."):
                    call_env["self" + k[len(obj_path) :]] = v
        return call_env

    def _check_requires(self, key, func, sig, node, env, obj_path=None):
        if func is None or func.requires is None:
            return
        call_env = self._call_env(sig, node, env, obj_path)
        ok = self._eval_bool(func.requires, call_env, annotate=False)
        entry = self.req_sites.setdefault(key, [0, 0])
        entry[1] += 1
        entry[0] += 1 if ok is True else 0

    def _iv_call(self, node: ast.Call, env: dict, annotate: bool):
        for arg in node.args:
            self._iv(arg, env, annotate)
        name = node.name
        if name in ("i32", "u32", "u8"):
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
            from .types import ArrayType

            aty = node.args[0].ty
            if isinstance(aty, ArrayType):
                return (aty.size, aty.size)
            return (0, 4096)
        if name in self.checker.funcs:
            func, _ = self._func_by_key(name)
            sig = self.checker.funcs[name]
            self._check_requires(name, func, sig, node, env)
            return self.summaries.get(name) or self._ty_range(node.ty)
        return self._ty_range(node.ty)

    def _iv_method(self, node: ast.MethodCall, env: dict, annotate: bool):
        self._iv(node.obj, env, annotate)
        for arg in node.args:
            self._iv(arg, env, annotate)
        key = f"{node.struct}.{node.name}"
        func, _ = self._func_by_key(key)
        sig = self.checker.structs[node.struct].methods[node.name]
        self._check_requires(
            key, func, sig, node, env, obj_path=_path_of(node.obj)
        )
        return self.summaries.get(key) or self._ty_range(node.ty)


def verify(program: ast.Program, checker) -> dict:
    return Verifier(program, checker).run()
