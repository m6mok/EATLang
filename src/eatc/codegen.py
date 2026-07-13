"""Кодогенерация EATLang: типизированный AST → LLVM IR → бинарник.

Модель значений: скаляры (целые, bool, char, enum) — регистры LLVM;
агрегаты (str, массивы, struct, Result, Option) живут в alloca на
стеке, выражение возвращает указатель. Копия на каждой точке
связывания — как в интерпретаторе. Кучи нет: ни одного malloc.

Все trap'ы (контракты, переполнение, деление на ноль, границы)
компилируются в проверку + вызов eat_trap из runtime.c.
"""

import subprocess
import sys
from pathlib import Path

import llvmlite.binding as llvm
import llvmlite.ir as ir

from . import ast_nodes as ast
from .errors import EatError
from .types import (
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
)

I32L = ir.IntType(32)
I8L = ir.IntType(8)
I1L = ir.IntType(1)
STR_CAP = 256
STR_LL = ir.LiteralStructType([I32L, ir.ArrayType(I8L, STR_CAP)])
I8P = ir.PointerType(I8L)
STRP = ir.PointerType(STR_LL)

# Аксиомы ОС — единственные внешние символы (шим runtime.c);
# логика строк/разбора — EAT-методы RtStr (selfhost/Rt.eat).
_RUNTIME = {
    "eat_trap": ir.FunctionType(ir.VoidType(), [I8P]),
    "eat_read_byte": ir.FunctionType(I32L, []),
    "eat_write_byte": ir.FunctionType(ir.VoidType(), [I8L]),
    "eat_write_err_byte": ir.FunctionType(ir.VoidType(), [I8L]),
    "eat_exit": ir.FunctionType(ir.VoidType(), [I32L]),
}

_SIGNED = {"i32"}
_INT_MIN = -(2**31)


def _is_agg(t: Type) -> bool:
    return isinstance(
        t, (StrType, ArrayType, StructType, ResultType, OptionType)
    )


class Codegen:
    def __init__(self, program: ast.Program, checker, filename: str):
        self.program = program
        self.checker = checker
        self.filename = filename
        self.module = ir.Module(name=filename)
        self.module.triple = llvm.get_process_triple()
        self.rt = {
            name: ir.Function(self.module, ftype, name=name)
            for name, ftype in _RUNTIME.items()
        }
        # аксиомы не разворачивают стек; trap/exit не возвращаются,
        # trap-пути холодные — LLVM выносит их из горячего кода
        for fn in self.rt.values():
            fn.attributes.add("nounwind")
        self.rt["eat_trap"].attributes.add("noreturn")
        self.rt["eat_trap"].attributes.add("cold")
        self.rt["eat_exit"].attributes.add("noreturn")
        self.cstr_cache: dict[bytes, ir.GlobalVariable] = {}
        self.strlit_cache: dict[bytes, ir.GlobalVariable] = {}
        # declare_intrinsic ищет глобал по манглированному имени на
        # каждый арифметический оператор — кэшируем результат
        self.intr_cache: dict[tuple, ir.Function] = {}
        self.gname_n = 0  # общий счётчик имён @"str.N" обоих видов
        # enum с нагрузкой: {i32 tag, слот на каждый вариант с нагрузкой}
        self.payload_enums: set = {
            name
            for name, ps in checker.enum_payloads.items()
            if any(t is not None for t in ps.values())
        }
        self.enum_ll_cache: dict[str, ir.Type] = {}
        self.enum_slot: dict[str, dict] = {}
        self.frame_types: dict[str, list] = {}  # кадры для отчёта §8
        self.cur_key = ""
        self.struct_ll: dict[str, ir.Type] = {}
        self.field_index: dict[str, dict] = {}
        self.funcs: dict[str, ir.Function] = {}
        self.env: list[dict] = []
        self.b: ir.IRBuilder | None = None
        self.fn: ir.Function | None = None
        self.ret_ty: Type | None = None
        self.ret_slot = None
        self.exit_block = None
        self.loop_exits: list = []

    # --- типы -----------------------------------------------------------

    def ll(self, t: Type) -> ir.Type:
        if isinstance(t, IntType):
            return I8L if t.kind == "u8" else I32L
        if isinstance(t, BoolType):
            return I1L
        if isinstance(t, CharType):
            return I8L
        if isinstance(t, EnumType):
            if t.name in self.payload_enums:
                return self.enum_ll_of(t.name)
            return I32L
        if isinstance(t, StrType):
            return STR_LL
        if isinstance(t, ArrayType):
            return ir.ArrayType(self.ll(t.elem), t.size)
        if isinstance(t, StructType):
            return self.struct_ll[t.name]
        if isinstance(t, ResultType):
            return ir.LiteralStructType([I32L, self.ll(t.ok), self.ll(t.err)])
        if isinstance(t, OptionType):
            return ir.LiteralStructType([I32L, self.ll(t.inner)])
        raise AssertionError(f"нет lowering для {t}")

    def is_agg(self, t: Type) -> bool:
        if isinstance(t, EnumType):
            return t.name in self.payload_enums
        return _is_agg(t)

    def enum_ll_of(self, name: str) -> ir.Type:
        """Лейаут enum с нагрузкой. Циклов нет — тайпчекер отклоняет
        типы, содержащие себя по значению."""
        if name not in self.enum_ll_cache:
            payloads = self.checker.enum_payloads[name]
            slots: list = [I32L]
            slot_idx: dict = {}
            for v in self.checker.enums[name]:
                t = payloads[v]
                if t is not None:
                    slot_idx[v] = len(slots)
                    slots.append(self.ll(t))
            self.enum_slot[name] = slot_idx
            self.enum_ll_cache[name] = ir.LiteralStructType(slots)
        return self.enum_ll_cache[name]

    # --- инфраструктура ---------------------------------------------------

    def cstr(self, text: str):
        data = text.encode("utf-8") + b"\0"
        if data not in self.cstr_cache:
            arr = ir.Constant(ir.ArrayType(I8L, len(data)), bytearray(data))
            g = ir.GlobalVariable(
                self.module, arr.type, name=f"str.{self.gname_n}"
            )
            self.gname_n += 1
            g.initializer = arr
            g.global_constant = True
            g.linkage = "private"
            self.cstr_cache[data] = g
        g = self.cstr_cache[data]
        return self.b.gep(g, [I32L(0), I32L(0)], inbounds=True), len(data) - 1

    def cstr_str(self, text: str):
        """Литеральный сегмент строки — глобал в layout'е str<256>
        ({i32 len, [256 x i8]}): передаётся RtStr-методам как параметр."""
        data = text.encode("utf-8")
        if data not in self.strlit_cache:
            buf = ir.Constant(
                ir.ArrayType(I8L, STR_CAP),
                bytearray(data.ljust(STR_CAP, b"\0")),
            )
            init = ir.Constant.literal_struct([I32L(len(data)), buf])
            g = ir.GlobalVariable(
                self.module, STR_LL, name=f"str.{self.gname_n}"
            )
            self.gname_n += 1
            g.initializer = init
            g.global_constant = True
            g.linkage = "private"
            self.strlit_cache[data] = g
        return self.strlit_cache[data]

    def rtm(self, name: str):
        """Метод рантайм-модуля RtStr (selfhost/Rt.eat)."""
        fn = self.funcs.get(f"RtStr.{name}")
        if fn is None:
            raise EatError(
                self.filename,
                1,
                1,
                "программа не включает рантайм-модуль: первым модулем "
                "должен идти selfhost/Rt.eat (struct RtStr)",
            )
        return fn

    def trap_if(self, bad, node: ast.Node, message: str) -> None:
        """bad — i1: если истина, аварийная остановка."""
        fname = getattr(node, "src_file", None) or self.filename
        full = f"{fname}:{node.line}:{node.col}: error: trap: {message}"
        bad_bb = self.fn.append_basic_block("trap")
        ok_bb = self.fn.append_basic_block("ok")
        self.b.cbranch(bad, bad_bb, ok_bb)
        self.b.position_at_end(bad_bb)
        ptr, _ = self.cstr(full)
        self.b.call(self.rt["eat_trap"], [ptr])
        self.b.unreachable()
        self.b.position_at_end(ok_bb)

    def push(self) -> None:
        self.env.append({})

    def pop(self) -> None:
        self.env.pop()

    def bind(self, name: str, ty: Type, ptr) -> None:
        if name != "_":
            self.env[-1][name] = (ty, ptr)

    def find(self, name: str):
        for scope in reversed(self.env):
            if name in scope:
                return scope[name]
        return None

    def copy_into(self, ty: Type, dst_ptr, src) -> None:
        """src: значение (скаляр) или указатель (агрегат).

        Агрегаты копируются memcpy: load/store целого массива создаёт
        SSA-значение на все элементы, и на пулах в десятки тысяч
        элементов LLVM SelectionDAG падает (NumValues — 16 бит).
        """
        if not self.is_agg(ty):
            self.b.store(src, dst_ptr)
            return
        i8p = I8L.as_pointer()
        i64 = ir.IntType(64)
        memcpy = self.intr_cache.get("llvm.memcpy")
        if memcpy is None:
            memcpy = self.module.declare_intrinsic(
                "llvm.memcpy", [i8p, i8p, i64]
            )
            self.intr_cache["llvm.memcpy"] = memcpy
        # sizeof через gep(null, 1): без обращения к target data
        null = ir.Constant(dst_ptr.type, None)
        one = ir.Constant(ir.IntType(32), 1)
        size = self.b.ptrtoint(self.b.gep(null, [one]), i64)
        self.b.call(
            memcpy,
            [
                self.b.bitcast(dst_ptr, i8p),
                self.b.bitcast(src, i8p),
                size,
                ir.Constant(ir.IntType(1), 0),
            ],
        )

    def alloca(self, llty: ir.Type, name: str = ""):
        """Единственная точка аллокации: учитывает кадр функции для
        отчёта о памяти (SPEC.md §8). Все alloca поднимаются в
        entry-блок (как в clang): alloca в теле цикла выделял бы
        стек на каждой итерации — кадр рос бы с числом итераций."""
        self.frame_types.setdefault(self.cur_key, []).append(llty)
        return self.ab.alloca(llty, name=name)

    def materialize(self, ty: Type, src):
        """Копия значения в свежем alloca; возвращает указатель."""
        slot = self.alloca(self.ll(ty))
        self.copy_into(ty, slot, src)
        return slot

    def ensure_br(self, target) -> None:
        if not self.b.block.is_terminated:
            self.b.branch(target)

    # --- генерация модуля ---------------------------------------------------

    def generate(self) -> ir.Module:
        for name, info in self.checker.structs.items():
            self.struct_ll[name] = ir.LiteralStructType(
                [self.ll(t) for t in info.fields.values()]
            )
            self.field_index[name] = {
                fname: i for i, fname in enumerate(info.fields)
            }
        decls = []
        for decl in self.program.decls:
            if isinstance(decl, ast.FuncDecl):
                sig = self.checker.funcs[decl.name]
                decls.append((decl, decl.name, sig, None))
            elif isinstance(decl, ast.StructDecl):
                for m in decl.methods:
                    sig = self.checker.structs[decl.name].methods[m.name]
                    decls.append((m, f"{decl.name}.{m.name}", sig, decl.name))
        for func, key, sig, struct in decls:
            self.funcs[key] = self.declare_func(key, sig, struct)
        for func, key, sig, struct in decls:
            self.gen_func(func, key, sig, struct)
        self.gen_entry()
        return self.module

    def mangle(self, key: str) -> str:
        return "eat_" + key.replace(".", "__")

    def declare_func(self, key: str, sig, struct: str | None):
        args: list[ir.Type] = []
        agg_ret = sig.ret is not None and self.is_agg(sig.ret)
        if agg_ret:
            args.append(ir.PointerType(self.ll(sig.ret)))
        if struct is not None:
            args.append(ir.PointerType(self.struct_ll[struct]))
        for _, pty in sig.params:
            llt = self.ll(pty)
            args.append(ir.PointerType(llt) if self.is_agg(pty) else llt)
        if sig.ret is None or agg_ret:
            ret_ll: ir.Type = ir.VoidType()
        else:
            ret_ll = self.ll(sig.ret)
        ftype = ir.FunctionType(ret_ll, args)
        fn = ir.Function(self.module, ftype, name=self.mangle(key))
        # рекурsии в языке нет по построению (правило 1), стек не
        # разворачивается (исключений нет, trap завершает процесс)
        fn.attributes.add("norecurse")
        fn.attributes.add("nounwind")
        # указательные аргументы — всегда alloca вызывающего: не null,
        # кучи нет (nofree); слот агрегатного возврата — свежая alloca
        # на каждый вызов, ни с чем не алиасится. noalias на параметры
        # ставить нельзя: получатель var self может совпасть с
        # аргументом (s.append_str(s)).
        ai = 0
        if agg_ret:
            for attr in ("noalias", "nofree", "nonnull"):
                fn.args[0].add_attribute(attr)
            ai = 1
        if struct is not None:
            for attr in ("nofree", "nonnull"):
                fn.args[ai].add_attribute(attr)
            ai += 1
        for _, pty in sig.params:
            if self.is_agg(pty):
                for attr in ("nofree", "nonnull"):
                    fn.args[ai].add_attribute(attr)
            ai += 1
        return fn

    def gen_func(self, func: ast.FuncDecl, key, sig, struct) -> None:
        fn = self.funcs[key]
        self.fn = fn
        self.cur_key = key
        # entry держит только alloca и br на body: код идёт в body
        entry = fn.append_basic_block("entry")
        body_bb = fn.append_basic_block("body")
        entry_br = ir.IRBuilder(entry).branch(body_bb)
        self.ab = ir.IRBuilder(entry)
        self.ab.position_before(entry_br)
        self.b = ir.IRBuilder(body_bb)
        self.env = [{}]
        self.loop_exits = []
        self.ret_ty = sig.ret
        agg_ret = sig.ret is not None and self.is_agg(sig.ret)

        arg_i = 0
        if agg_ret:
            self.ret_slot = fn.args[arg_i]
            arg_i += 1
        elif sig.ret is not None:
            self.ret_slot = self.alloca(self.ll(sig.ret), name="ret")
        else:
            self.ret_slot = None
        if struct is not None:
            self_ty = StructType(struct)
            if sig.var_self:
                # var self мутирует получателя — работаем по указателю
                # вызывающего, без локальной копии
                self.bind("self", self_ty, fn.args[arg_i])
            else:
                self.bind(
                    "self", self_ty, self.materialize(self_ty, fn.args[arg_i])
                )
            arg_i += 1
        for pname, pty in sig.params:
            arg = fn.args[arg_i]
            arg_i += 1
            if self.is_agg(pty):
                self.bind(pname, pty, self.materialize(pty, arg))
            else:
                slot = self.alloca(self.ll(pty), name=pname)
                self.b.store(arg, slot)
                self.bind(pname, pty, slot)

        self.exit_block = fn.append_basic_block("exit")
        if func.requires is not None and not getattr(
            func, "requires_proven", False
        ):
            cond = self.expr(func.requires)
            self.trap_if(
                self.b.not_(cond),
                func,
                f"нарушен requires функции {func.name}",
            )
        self.gen_block(func.body)
        self.ensure_br(self.exit_block)

        self.b.position_at_end(self.exit_block)
        if func.ensures is not None and not getattr(
            func, "ensures_proven", False
        ):
            self.push()
            if sig.ret is not None:
                self.bind("result", sig.ret, self.ret_slot)
            cond = self.expr(func.ensures)
            self.trap_if(
                self.b.not_(cond),
                func,
                f"нарушен ensures функции {func.name}",
            )
            self.pop()
        if sig.ret is None or agg_ret:
            self.b.ret_void()
        else:
            self.b.ret(self.b.load(self.ret_slot))

    def gen_entry(self) -> None:
        fn = ir.Function(self.module, ir.FunctionType(I32L, []), name="main")
        fn.attributes.add("norecurse")
        fn.attributes.add("nounwind")
        b = ir.IRBuilder(fn.append_basic_block("entry"))
        b.call(self.funcs["main"], [])
        b.ret(I32L(0))

    # --- инструкции ---------------------------------------------------------

    def gen_block(self, block: ast.Block) -> None:
        self.push()
        for stmt in block.stmts:
            if self.b.block.is_terminated:
                break
            self.gen_stmt(stmt)
        self.pop()

    def gen_stmt(self, stmt: ast.Stmt) -> None:
        if isinstance(stmt, ast.LetStmt):
            value = self.expr(stmt.value)
            self.bind(
                stmt.name, stmt.var_ty, self.materialize(stmt.var_ty, value)
            )
            return
        if isinstance(stmt, ast.AssignStmt):
            value = self.expr(stmt.value)
            target = self.lvalue(stmt.target)
            self.copy_into(stmt.target.ty, target, value)
            return
        if isinstance(stmt, ast.IfStmt):
            self.gen_if(stmt)
            return
        if isinstance(stmt, ast.ForStmt):
            self.gen_for(stmt)
            return
        if isinstance(stmt, ast.LoopStmt):
            body = self.fn.append_basic_block("loop")
            after = self.fn.append_basic_block("loop.end")
            self.b.branch(body)
            self.b.position_at_end(body)
            self.loop_exits.append(after)
            self.gen_block(stmt.body)
            self.loop_exits.pop()
            self.ensure_br(body)
            self.b.position_at_end(after)
            return
        if isinstance(stmt, ast.MatchStmt):
            self.gen_match(stmt)
            return
        if isinstance(stmt, ast.ReturnStmt):
            if stmt.value is not None:
                value = self.expr(stmt.value)
                self.copy_into(self.ret_ty, self.ret_slot, value)
            self.b.branch(self.exit_block)
            return
        if isinstance(stmt, ast.BreakStmt):
            self.b.branch(self.loop_exits[-1])
            return
        if isinstance(stmt, ast.AssertStmt):
            if getattr(stmt, "proven", False):
                return  # доказан статически — проверка не нужна
            cond = self.expr(stmt.cond)
            self.trap_if(self.b.not_(cond), stmt, "assert не выполнен")
            return
        if isinstance(stmt, (ast.ExprStmt, ast.DiscardStmt)):
            self.expr(stmt.expr, allow_void=True)
            return
        raise AssertionError("неизвестная инструкция")

    def gen_if(self, stmt: ast.IfStmt) -> None:
        merge = self.fn.append_basic_block("if.end")
        branches = [(stmt.cond, stmt.then)] + list(stmt.elifs)
        for cond_expr, block in branches:
            then_bb = self.fn.append_basic_block("if.then")
            else_bb = self.fn.append_basic_block("if.else")
            self.b.cbranch(self.expr(cond_expr), then_bb, else_bb)
            self.b.position_at_end(then_bb)
            self.gen_block(block)
            self.ensure_br(merge)
            self.b.position_at_end(else_bb)
        if stmt.els is not None:
            self.gen_block(stmt.els)
        self.ensure_br(merge)
        self.b.position_at_end(merge)

    def gen_for(self, stmt: ast.ForStmt) -> None:
        idx = self.alloca(I32L, name="for.i")
        if stmt.bounds is not None:
            start, end = stmt.bounds
            self.b.store(I32L(start), idx)
            limit = I32L(end)
            source = None
            elem_ll = None
        else:
            self.b.store(I32L(0), idx)
            source = self.expr(stmt.iterable)
            ity = stmt.iterable.ty
            if isinstance(ity, ArrayType):
                limit = I32L(ity.size)
            else:  # str: предел — текущая длина
                limit = self.b.load(
                    self.b.gep(source, [I32L(0), I32L(0)], inbounds=True)
                )
            elem_ll = self.ll(stmt.elem_ty)
        cond_bb = self.fn.append_basic_block("for.cond")
        body_bb = self.fn.append_basic_block("for.body")
        after = self.fn.append_basic_block("for.end")
        self.b.branch(cond_bb)
        self.b.position_at_end(cond_bb)
        cur = self.b.load(idx)
        self.b.cbranch(self.b.icmp_signed("<", cur, limit), body_bb, after)
        self.b.position_at_end(body_bb)
        self.push()
        if stmt.target != "_":
            slot = self.alloca(
                elem_ll if elem_ll is not None else I32L, name=stmt.target
            )
            if stmt.bounds is not None:
                self.b.store(cur, slot)
            else:
                elem_ptr = (
                    self.b.gep(source, [I32L(0), I32L(1), cur], inbounds=True)
                    if isinstance(stmt.iterable.ty, StrType)
                    else self.b.gep(source, [I32L(0), cur], inbounds=True)
                )
                self.copy_into(
                    stmt.elem_ty,
                    slot,
                    elem_ptr
                    if self.is_agg(stmt.elem_ty)
                    else self.b.load(elem_ptr),
                )
            self.bind(stmt.target, stmt.elem_ty, slot)
        self.loop_exits.append(after)  # break — ранний выход из for
        self.gen_block(stmt.body)
        self.loop_exits.pop()
        self.pop()
        if not self.b.block.is_terminated:
            nxt = self.b.add(self.b.load(idx), I32L(1))
            self.b.store(nxt, idx)
            self.b.branch(cond_bb)
        self.b.position_at_end(after)

    def gen_match(self, stmt: ast.MatchStmt) -> None:
        subject_ty = stmt.subject.ty
        subject = self.expr(stmt.subject)
        if isinstance(subject_ty, EnumType):
            variants = self.checker.enums[subject_ty.name]
            index = {v: i for i, v in enumerate(variants)}
            if subject_ty.name in self.payload_enums:
                self.enum_ll_of(subject_ty.name)  # заполняет enum_slot
                tag = self.b.load(
                    self.b.gep(subject, [I32L(0), I32L(0)], inbounds=True)
                )
                payload_field = self.enum_slot[subject_ty.name]
            else:
                tag = subject
                payload_field = {}
        elif isinstance(subject_ty, ResultType):
            tag = self.b.load(
                self.b.gep(subject, [I32L(0), I32L(0)], inbounds=True)
            )
            index = {"Ok": 0, "Err": 1}
            payload_field = {"Ok": 1, "Err": 2}
        else:  # Option
            tag = self.b.load(
                self.b.gep(subject, [I32L(0), I32L(0)], inbounds=True)
            )
            index = {"Some": 0, "None": 1}
            payload_field = {"Some": 1}
        merge = self.fn.append_basic_block("match.end")
        default = self.fn.append_basic_block("match.dead")
        switch = self.b.switch(tag, default)
        b_saved = self.b
        b_saved.position_at_end(default)
        self.b.unreachable()
        for arm in stmt.arms:
            arm_bb = self.fn.append_basic_block(f"match.{arm.pattern}")
            switch.add_case(I32L(index[arm.pattern]), arm_bb)
            self.b.position_at_end(arm_bb)
            self.push()
            if (
                arm.binding is not None
                and arm.binding != "_"
                and arm.pattern in payload_field
            ):
                fidx = payload_field[arm.pattern]
                pptr = self.b.gep(
                    subject, [I32L(0), I32L(fidx)], inbounds=True
                )
                pty = arm.payload_ty
                src = pptr if self.is_agg(pty) else self.b.load(pptr)
                self.bind(arm.binding, pty, self.materialize(pty, src))
            self.gen_block(arm.body)
            self.pop()
            self.ensure_br(merge)
        self.b.position_at_end(merge)

    # --- lvalue ----------------------------------------------------------

    def lvalue(self, node: ast.Expr):
        if isinstance(node, ast.Name):
            _, ptr = self.find(node.ident)
            return ptr
        if isinstance(node, ast.SelfExpr):
            _, ptr = self.find("self")
            return ptr
        if isinstance(node, ast.FieldAccess):
            base = self.lvalue(node.obj)
            sname = node.obj.ty.name
            fidx = self.field_index[sname][node.name]
            return self.b.gep(base, [I32L(0), I32L(fidx)], inbounds=True)
        if isinstance(node, ast.Index):
            base = self.lvalue(node.obj)
            return self.indexed_ptr(node, base)
        raise AssertionError("некорректный lvalue")

    def indexed_ptr(self, node: ast.Index, base):
        idx = self.expr(node.index)
        idx32 = self.widen_index(node.index.ty, idx)
        oty = node.obj.ty
        if isinstance(oty, ArrayType):
            size = I32L(oty.size)
            path = [I32L(0), idx32]
        else:  # str
            size = self.b.load(
                self.b.gep(base, [I32L(0), I32L(0)], inbounds=True)
            )
            path = [I32L(0), I32L(1), idx32]
        if not getattr(node, "in_bounds", False):
            bad_low = self.b.icmp_signed("<", idx32, I32L(0))
            bad_high = self.b.icmp_signed(">=", idx32, size)
            self.trap_if(
                self.b.or_(bad_low, bad_high), node, "индекс вне границ"
            )
        return self.b.gep(base, path, inbounds=True)

    def widen_index(self, ty: Type, value):
        if isinstance(ty, IntType) and ty.kind == "u8":
            return self.b.zext(value, I32L)
        return value

    # --- выражения ----------------------------------------------------------

    def expr(self, node: ast.Expr, allow_void: bool = False):
        if isinstance(node, ast.IntLit):
            return self.ll(node.ty)(node.value)
        if isinstance(node, ast.BoolLit):
            return I1L(1 if node.value else 0)
        if isinstance(node, ast.CharLit):
            return I8L(ord(node.value))
        if isinstance(node, ast.StrLit):
            return self.gen_strlit(node)
        if isinstance(node, ast.SelfExpr):
            _, ptr = self.find("self")
            return ptr
        if isinstance(node, ast.Name):
            return self.gen_name(node)
        if isinstance(node, ast.UnaryOp):
            return self.gen_unary(node)
        if isinstance(node, ast.BinOp):
            return self.gen_binop(node)
        if isinstance(node, ast.Call):
            return self.gen_call(node)
        if isinstance(node, ast.MethodCall):
            return self.gen_method_call(node)
        if isinstance(node, ast.FieldAccess):
            return self.gen_field(node)
        if isinstance(node, ast.Index):
            base = self.expr(node.obj)
            ptr = self.indexed_ptr(node, base)
            return ptr if self.is_agg(node.ty) else self.b.load(ptr)
        if isinstance(node, ast.StructLit):
            return self.gen_struct_lit(node)
        if isinstance(node, ast.ArrayLit):
            return self.gen_array_lit(node)
        if isinstance(node, ast.ArrayFill):
            return self.gen_array_fill(node)
        raise AssertionError("неизвестное выражение")

    def gen_name(self, node: ast.Name):
        found = self.find(node.ident)
        if found is not None:
            ty, ptr = found
            return ptr if self.is_agg(ty) else self.b.load(ptr)
        cty, cval = self.checker.consts[node.ident]
        return self.ll(cty)(cval)

    def gen_strlit(self, node: ast.StrLit):
        out = self.alloca(STR_LL, name="str")
        self.b.call(self.rtm("init"), [out])
        for seg in node.segments:
            if isinstance(seg, str):
                g = self.cstr_str(seg)
                self.b.call(self.rtm("append_str"), [out, g])
                continue
            value = self.expr(seg)
            ty = seg.ty
            if isinstance(ty, StrType):
                self.b.call(self.rtm("append_str"), [out, value])
            elif isinstance(ty, CharType):
                self.b.call(self.rtm("append_char"), [out, value])
            elif isinstance(ty, BoolType):
                self.b.call(self.rtm("append_bool"), [out, value])
            elif ty.kind == "i32":
                self.b.call(self.rtm("append_i32"), [out, value])
            else:  # u32, u8
                wide = self.b.zext(value, I32L) if ty.kind == "u8" else value
                self.b.call(self.rtm("append_u32"), [out, wide])
        return out

    def gen_unary(self, node: ast.UnaryOp):
        value = self.expr(node.operand)
        if node.op == "not":
            return self.b.not_(value)
        return self.arith(node, "-", I32L(0), value, "i32")

    def gen_binop(self, node: ast.BinOp):
        op = node.op
        if op in ("and", "or"):
            return self.gen_shortcircuit(node)
        left = self.expr(node.left)
        right = self.expr(node.right)
        lty = node.left.ty
        if op in ("+", "-", "*", "/", "%"):
            return self.arith(node, op, left, right, lty.kind)
        if op == "&":
            return self.b.and_(left, right)
        if op == "|":
            return self.b.or_(left, right)
        if op == "^":
            return self.b.xor(left, right)
        if op in ("<<", ">>"):
            return self.shift(node, op, left, right, lty.kind)
        # сравнения
        if isinstance(lty, StrType):
            res = self.b.call(self.rtm("eq"), [left, right])
            return res if op == "==" else self.b.not_(res)
        signed = isinstance(lty, IntType) and lty.kind in _SIGNED
        if signed:
            return self.b.icmp_signed(op, left, right)
        return self.b.icmp_unsigned(op, left, right)

    def gen_shortcircuit(self, node: ast.BinOp):
        left = self.expr(node.left)
        start = self.b.block
        rhs_bb = self.fn.append_basic_block(node.op)
        merge = self.fn.append_basic_block(f"{node.op}.end")
        if node.op == "and":
            self.b.cbranch(left, rhs_bb, merge)
        else:
            self.b.cbranch(left, merge, rhs_bb)
        self.b.position_at_end(rhs_bb)
        right = self.expr(node.right)
        rhs_end = self.b.block
        self.b.branch(merge)
        self.b.position_at_end(merge)
        phi = self.b.phi(I1L)
        phi.add_incoming(left, start)
        phi.add_incoming(right, rhs_end)
        return phi

    def arith(self, node, op: str, left, right, kind: str):
        signed = kind in _SIGNED
        if op in ("+", "-", "*"):
            if getattr(node, "no_overflow", False):
                # переполнение доказуемо невозможно — обычная инструкция;
                # nsw/nuw отдаёт доказательство верификатора оптимизатору
                # (только build-путь: в `eatc ir` фактов верификатора нет)
                plain = {"+": self.b.add, "-": self.b.sub, "*": self.b.mul}
                wrap = ("nsw",) if signed else ("nuw",)
                return plain[op](left, right, flags=wrap)
            name = {
                ("+", True): "llvm.sadd.with.overflow",
                ("-", True): "llvm.ssub.with.overflow",
                ("*", True): "llvm.smul.with.overflow",
                ("+", False): "llvm.uadd.with.overflow",
                ("-", False): "llvm.usub.with.overflow",
                ("*", False): "llvm.umul.with.overflow",
            }[(op, signed)]
            key = (name, str(left.type))
            intr = self.intr_cache.get(key)
            if intr is None:
                pair_ty = ir.LiteralStructType([left.type, I1L])
                fnty = ir.FunctionType(pair_ty, [left.type, left.type])
                intr = self.module.declare_intrinsic(
                    name, [left.type], fnty=fnty
                )
                self.intr_cache[key] = intr
            pair = self.b.call(intr, [left, right])
            self.trap_if(
                self.b.extract_value(pair, 1),
                node,
                f"переполнение {kind}",
            )
            return self.b.extract_value(pair, 0)
        # деление и остаток
        safe = getattr(node, "div_safe", False)
        if not safe:
            zero = left.type(0)
            self.trap_if(
                self.b.icmp_signed("==", right, zero),
                node,
                "деление на ноль",
            )
        if signed:
            if not safe:
                edge = self.b.and_(
                    self.b.icmp_signed("==", left, left.type(_INT_MIN)),
                    self.b.icmp_signed("==", right, left.type(-1)),
                )
                self.trap_if(edge, node, f"переполнение {kind}")
            return (
                self.b.sdiv(left, right)
                if op == "/"
                else self.b.srem(left, right)
            )
        return (
            self.b.udiv(left, right) if op == "/" else self.b.urem(left, right)
        )

    def shift(self, node, op: str, left, right, kind: str):
        """Сдвиги беззнаковых. Сдвиг ≥ ширины типа в LLVM — яд,
        поэтому trap до инструкции; << дополнительно трапит вынос
        битов: обратный lshr обязан восстановить операнд."""
        width = 8 if kind == "u8" else 32
        if not getattr(node, "shift_ok", False):
            self.trap_if(
                self.b.icmp_unsigned(">=", right, right.type(width)),
                node,
                f"сдвиг ≥ ширины {kind}",
            )
        if op == ">>":
            return self.b.lshr(left, right)
        if getattr(node, "no_overflow", False):
            # вынос битов доказуемо невозможен — nuw для оптимизатора
            return self.b.shl(left, right, flags=("nuw",))
        res = self.b.shl(left, right)
        back = self.b.lshr(res, right)
        self.trap_if(
            self.b.icmp_unsigned("!=", back, left),
            node,
            f"переполнение {kind}",
        )
        return res

    # --- вызовы --------------------------------------------------------------

    def gen_call(self, node: ast.Call):
        name = node.name
        if name == "print":
            self.b.call(self.rtm("print"), [self.expr(node.args[0])])
            return None
        if name == "write":
            self.b.call(self.rtm("write"), [self.expr(node.args[0])])
            return None
        if name == "read_byte":
            return self.gen_read_byte(node)
        if name == "write_byte":
            self.b.call(self.rt["eat_write_byte"], [self.expr(node.args[0])])
            return None
        if name == "write_err_byte":
            self.b.call(
                self.rt["eat_write_err_byte"], [self.expr(node.args[0])]
            )
            return None
        if name == "exit":
            self.b.call(self.rt["eat_exit"], [self.expr(node.args[0])])
            return None
        if name == "read_line":
            return self.gen_read_line(node)
        if name == "parse_i32":
            return self.gen_parse_i32(node)
        if name == "len":
            return self.gen_len(node)
        if name in ("i32", "u32", "u8", "char"):
            return self.gen_cast(node)
        sig = self.checker.funcs[name]
        return self.emit_call(node, self.funcs[name], sig, [])

    def gen_method_call(self, node: ast.MethodCall):
        if getattr(node, "enum_ctor", None) is not None:
            return self.gen_enum_ctor(node)
        sig = self.checker.structs[node.struct].methods[node.name]
        fn = self.funcs[f"{node.struct}.{node.name}"]
        return self.emit_call(node, fn, sig, [self.expr(node.obj)])

    def gen_enum_ctor(self, node: ast.MethodCall):
        ename = node.enum_ctor
        out = self.alloca(
            self.enum_ll_of(ename), name=f"{ename}.{node.name}"
        )
        tag = I32L(self.checker.enums[ename].index(node.name))
        self.b.store(tag, self.b.gep(out, [I32L(0), I32L(0)], inbounds=True))
        pty = self.checker.enum_payloads[ename][node.name]
        slot = self.enum_slot[ename][node.name]
        dst = self.b.gep(out, [I32L(0), I32L(slot)], inbounds=True)
        self.copy_into(pty, dst, self.expr(node.args[0]))
        return out

    def emit_call(self, node, fn, sig, prefix_args: list):
        args = list(prefix_args)
        agg_ret = sig.ret is not None and self.is_agg(sig.ret)
        out = None
        if agg_ret:
            out = self.alloca(self.ll(sig.ret), name="call.ret")
            args.insert(0, out)
        for arg in node.args:
            args.append(self.expr(arg))
        result = self.b.call(fn, args)
        if sig.ret is None:
            return None
        return out if agg_ret else result

    def gen_read_byte(self, node: ast.Call):
        raw = self.b.call(self.rt["eat_read_byte"], [])
        res = self.alloca(self.ll(node.ty), name="rb.res")
        ok = self.b.icmp_signed(">=", raw, I32L(0))
        tag = self.b.select(ok, I32L(0), I32L(1))
        self.b.store(tag, self.b.gep(res, [I32L(0), I32L(0)], inbounds=True))
        byte = self.b.select(ok, self.b.trunc(raw, I8L), I8L(0))
        self.b.store(byte, self.b.gep(res, [I32L(0), I32L(1)], inbounds=True))
        # Err(Eof) — индекс варианта 0
        self.b.store(
            I32L(0), self.b.gep(res, [I32L(0), I32L(2)], inbounds=True)
        )
        return res

    def gen_read_line(self, node: ast.Call):
        tmp = self.alloca(STR_LL, name="line")
        status = self.b.call(self.rtm("read_line"), [tmp])
        res_ll = self.ll(node.ty)
        res = self.alloca(res_ll, name="read.res")
        tag = self.b.select(
            self.b.icmp_signed("==", status, I32L(0)), I32L(0), I32L(1)
        )
        self.b.store(tag, self.b.gep(res, [I32L(0), I32L(0)], inbounds=True))
        self.b.store(
            self.b.load(tmp),
            self.b.gep(res, [I32L(0), I32L(1)], inbounds=True),
        )
        # Err(Eof) — индекс варианта 0
        self.b.store(
            I32L(0), self.b.gep(res, [I32L(0), I32L(2)], inbounds=True)
        )
        return res

    def gen_parse_i32(self, node: ast.Call):
        s = self.expr(node.args[0])
        status = self.b.call(self.rtm("parse_status"), [s])
        value = self.b.call(self.rtm("parse_value"), [s])
        res = self.alloca(self.ll(node.ty), name="parse.res")
        ok = self.b.icmp_signed("==", status, I32L(0))
        tag = self.b.select(ok, I32L(0), I32L(1))
        self.b.store(tag, self.b.gep(res, [I32L(0), I32L(0)], inbounds=True))
        self.b.store(
            value,
            self.b.gep(res, [I32L(0), I32L(1)], inbounds=True),
        )
        # статусы 1..3 → варианты ParseError 0..2
        err = self.b.select(ok, I32L(0), self.b.sub(status, I32L(1)))
        self.b.store(err, self.b.gep(res, [I32L(0), I32L(2)], inbounds=True))
        return res

    def gen_len(self, node: ast.Call):
        aty = node.args[0].ty
        if isinstance(aty, ArrayType):
            return I32L(aty.size)
        s = self.expr(node.args[0])
        return self.b.load(self.b.gep(s, [I32L(0), I32L(0)], inbounds=True))

    def gen_cast(self, node: ast.Call):
        target = node.name
        source_ty = node.args[0].ty
        value = self.expr(node.args[0])
        if target == "char" or isinstance(source_ty, CharType):
            # char ↔ u8: оба lowering'уются в i8, тот же байт
            return value
        src = source_ty.kind
        proven = getattr(node, "cast_ok", False)
        if src == "u8":
            wide = self.b.zext(value, I32L)
            if target == "u8":
                return value
            return wide  # в i32/u32 всегда помещается
        # src — i32 или u32 (регистр i32)
        if target == "i32" and src == "u32":
            if not proven:
                bad = self.b.icmp_unsigned(">", value, I32L(2**31 - 1))
                self.trap_if(bad, node, "переполнение при i32()")
        elif target == "u32" and src == "i32":
            if not proven:
                bad = self.b.icmp_signed("<", value, I32L(0))
                self.trap_if(bad, node, "переполнение при u32()")
        elif target == "u8":
            if not proven:
                if src == "i32":
                    low = self.b.icmp_signed("<", value, I32L(0))
                    high = self.b.icmp_signed(">", value, I32L(255))
                    bad = self.b.or_(low, high)
                else:
                    bad = self.b.icmp_unsigned(">", value, I32L(255))
                self.trap_if(bad, node, "переполнение при u8()")
            return self.b.trunc(value, I8L)
        return value

    # --- агрегаты ------------------------------------------------------------

    def gen_field(self, node: ast.FieldAccess):
        if (
            isinstance(node.obj, ast.Name)
            and node.obj.ident in self.checker.enums
        ):
            ename = node.obj.ident
            tag = I32L(self.checker.enums[ename].index(node.name))
            if ename in self.payload_enums:
                # вариант без нагрузки внутри enum с нагрузкой —
                # агрегат с одним лишь тегом
                out = self.alloca(
                    self.enum_ll_of(ename), name=f"{ename}.{node.name}"
                )
                self.b.store(
                    tag, self.b.gep(out, [I32L(0), I32L(0)], inbounds=True)
                )
                return out
            return tag
        base = self.expr(node.obj)
        sname = node.obj.ty.name
        fidx = self.field_index[sname][node.name]
        ptr = self.b.gep(base, [I32L(0), I32L(fidx)], inbounds=True)
        return ptr if self.is_agg(node.ty) else self.b.load(ptr)

    def gen_struct_lit(self, node: ast.StructLit):
        out = self.alloca(self.struct_ll[node.name], name=node.name)
        fields = self.checker.structs[node.name].fields
        for fname, fexpr in node.fields:
            fidx = self.field_index[node.name][fname]
            ptr = self.b.gep(out, [I32L(0), I32L(fidx)], inbounds=True)
            self.copy_into(fields[fname], ptr, self.expr(fexpr))
        return out

    def gen_array_lit(self, node: ast.ArrayLit):
        aty = node.ty
        out = self.alloca(self.ll(aty), name="arr")
        for i, elem in enumerate(node.elems):
            ptr = self.b.gep(out, [I32L(0), I32L(i)], inbounds=True)
            self.copy_into(aty.elem, ptr, self.expr(elem))
        return out

    def gen_array_fill(self, node: ast.ArrayFill):
        """[значение; N]: значение вычисляется один раз, заполнение —
        циклом (N бывает большим, разворачивать нельзя)."""
        aty = node.ty
        out = self.alloca(self.ll(aty), name="arr.fill")
        value = self.expr(node.value)
        idx = self.alloca(I32L, name="fill.i")
        self.b.store(I32L(0), idx)
        cond_bb = self.fn.append_basic_block("fill.cond")
        body_bb = self.fn.append_basic_block("fill.body")
        end_bb = self.fn.append_basic_block("fill.end")
        self.b.branch(cond_bb)
        self.b.position_at_end(cond_bb)
        cur = self.b.load(idx)
        self.b.cbranch(
            self.b.icmp_signed("<", cur, I32L(aty.size)), body_bb, end_bb
        )
        self.b.position_at_end(body_bb)
        ptr = self.b.gep(out, [I32L(0), cur], inbounds=True)
        self.copy_into(aty.elem, ptr, value)
        self.b.store(self.b.add(cur, I32L(1)), idx)
        self.b.branch(cond_bb)
        self.b.position_at_end(end_bb)
        return out


def _memory_report(cg: Codegen, checker, machine) -> dict:
    """Отчёт §8: кадры функций из фактических alloca (ABI-размеры LLVM)
    и худшая цепочка вызовов по DAG. Верхняя граница: mem2reg на деле
    поднимет часть локалов в регистры."""
    td = machine.target_data
    frames = {
        key: sum(t.get_abi_size(td) for t in types)
        for key, types in cg.frame_types.items()
    }
    graph: dict[str, set] = {}
    for caller, callee in checker.edges:
        if caller.startswith("test:") or callee not in frames:
            continue
        graph.setdefault(caller, set()).add(callee)

    memo: dict[str, int] = {}

    def worst(key: str) -> int:
        if key not in memo:
            memo[key] = frames.get(key, 0) + max(
                (worst(c) for c in graph.get(key, ())), default=0
            )
        return memo[key]

    globals_bytes = sum(len(data) for data in cg.cstr_cache) + (
        4 + STR_CAP
    ) * len(cg.strlit_cache)
    return {
        "frames": frames,
        "stack_bytes": worst("main"),
        "globals_bytes": globals_bytes,
    }


def emit_ir(program: ast.Program, checker) -> str:
    """Текстовый LLVM IR — канон дифф-сверки фазы 4 self-host
    (`eatc ir`, selfhost/Ir.eat). Без верификатора: все проверки
    остаются в рантайме. Имя модуля и файл в trap-сообщениях —
    «stdin», triple пуст: вывод не зависит от платформы и пути
    файла (self-hosted эмиттер читает исходник со stdin)."""
    cg = Codegen(program, checker, "stdin")
    module = cg.generate()
    module.triple = ""
    return str(module)


def compile_binary(
    program: ast.Program, checker, filename: str, out_path: str
) -> tuple[str, dict]:
    """AST → LLVM IR → объектный файл → clang → бинарник + отчёт §8."""
    cg = Codegen(program, checker, filename)
    module = cg.generate()
    try:
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()
    except RuntimeError:
        pass  # новые llvmlite инициализируются сами
    ref = llvm.parse_assembly(str(module))
    ref.verify()
    machine = llvm.Target.from_default_triple().create_target_machine(opt=2)
    report = _memory_report(cg, checker, machine)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ll_path = out.with_suffix(".ll")
    ll_path.write_text(str(module), encoding="utf-8")
    # Оптимизация — только на пути IR → объектный код: .ll выше уже
    # записан неоптимизированным (канон дифф-сверки и отладки), а
    # текстовую эмиссию `eatc ir` фикспойнт бутстрапа требует
    # байт-в-байт — её не трогаем.
    pto = llvm.create_pipeline_tuning_options(speed_level=2)
    pb = llvm.create_pass_builder(machine, pto)
    mpm = pb.getModulePassManager()
    mpm.run(ref, pb)
    obj_path = out.with_suffix(".o")
    obj_path.write_bytes(machine.emit_object(ref))
    runtime = Path(__file__).parent / "runtime.c"
    # стек 128 МБ: у программ без кучи пулы живут в кадре main,
    # и кадры компилятора (§8) выходят за умолчание ОС (8 МБ);
    # кадр main самого self-hosted компилятора — ~85 МБ (фаза 5)
    if sys.platform == "darwin":
        stack_flags = ["-Wl,-stack_size,0x8000000"]
    else:
        stack_flags = ["-Wl,-z,stacksize=134217728"]
    proc = subprocess.run(
        ["clang", str(obj_path), str(runtime), "-o", str(out)]
        + stack_flags,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise EatError(filename, 1, 1, f"clang: {proc.stderr.strip()}")
    obj_path.unlink()
    return str(out), report
