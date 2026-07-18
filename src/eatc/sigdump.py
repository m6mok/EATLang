"""Дамп деклараций и сигнатур — эталон для self-hosted фазы 3a
(selfhost/Check.eat): таблицы collect_decls + constexpr_eval + resolve.

Формат (порядок исходника):

    module {путь} {l}:{c}
    import {локальное} {l}:{c} :: {путь} {публичное}
    export {публичное} {l}:{c} :: {внутреннее}
    constexpr {имя} {l}:{c} :: {тип} = {значение}
    func {имя} {l}:{c} (имя: тип, ...) [-> тип]
    struct {имя} {l}:{c}
      field {имя} :: {тип}
      method {имя} {l}:{c} (имя: тип, ...) [var_self] [-> тип]
    enum {имя} {l}:{c}
      variant {имя} [:: тип нагрузки]
    test {имя} {l}:{c}
    stats funcs={n} structs={n} stmts={n}

Перед дампом выполняются проверки уровня деклараций: правила 4–5
(check_program), повторы/коллизии имён, циклы типов, наличие и
сигнатура main.
"""

from . import ast_nodes as ast
from .checks import check_program
from .errors import EatError
from .typechecker import FuncSig, TypeChecker
from .types import show


def _sig_str(sig: FuncSig) -> str:
    params = ", ".join(f"{n}: {show(t)}" for n, t in sig.params)
    text = f"({params})"
    if sig.var_self:
        text += " var_self"
    if sig.ret is not None:
        text += f" -> {show(sig.ret)}"
    return text


def dump_signatures(
    program: ast.Program, filename: str
) -> list[str]:
    stats = check_program(program, filename)
    tc = TypeChecker(program, filename)
    tc.collect_decls()
    tc._check_type_cycles()
    tc.check_module_interfaces()
    if "main" not in tc.funcs:
        raise EatError(filename, 1, 1, "нет функции main — точки входа")
    main = tc.funcs["main"]
    if main.params or main.ret is not None:
        raise tc.err(
            main.node, "main не принимает параметров и ничего не возвращает"
        )
    if tc._deferred_constexprs:
        # comptime-константы (§5): их значения печатаются в дампе —
        # догоняем типизацию тел и фазу 3.5 (COMPTIME_PLAN §9.5);
        # программы без comptime идут прежним лёгким путём
        tc.check_bodies()
        tc._eval_deferred_constexprs()

    lines: list[str] = []
    for decl in program.decls:
        pos = f"{decl.line}:{decl.col}"
        if isinstance(decl, ast.ConstexprDecl):
            ctype, value = tc.constexprs[decl.name]
            lines.append(f"const {decl.name} {pos} :: {show(ctype)} = {value}")
        elif isinstance(decl, ast.FuncDecl):
            kw = "extern" if decl.is_extern else "func"
            lines.append(
                f"{kw} {decl.name} {pos} {_sig_str(tc.funcs[decl.name])}"
            )
        elif isinstance(decl, ast.StructDecl):
            lines.append(f"struct {decl.name} {pos}")
            info = tc.structs[decl.name]
            for fdecl in decl.fields:
                lines.append(
                    f"  field {fdecl.name} :: {show(info.fields[fdecl.name])}"
                )
            for method in decl.methods:
                mpos = f"{method.line}:{method.col}"
                lines.append(
                    f"  method {method.name} {mpos} "
                    f"{_sig_str(info.methods[method.name])}"
                )
        elif isinstance(decl, ast.EnumDecl):
            lines.append(f"enum {decl.name} {pos}")
            payloads = tc.enum_payloads[decl.name]
            for vname, _ in decl.variants:
                payload = payloads[vname]
                if payload is None:
                    lines.append(f"  variant {vname}")
                else:
                    lines.append(f"  variant {vname} :: {show(payload)}")
        elif isinstance(decl, ast.TestBlock):
            lines.append(f"test {decl.name} {pos}")
        elif isinstance(decl, ast.ModuleMark):
            lines.append(f"module {decl.path} {pos}")
        elif isinstance(decl, ast.ImportBlock):
            for b in decl.binds:
                local = b.alias or b.name
                lines.append(
                    f"import {local} {b.line}:{b.col} :: "
                    f"{decl.path} {b.name}"
                )
        elif isinstance(decl, ast.ExportBlock):
            for b in decl.binds:
                pub = b.alias or b.name
                lines.append(f"export {pub} {b.line}:{b.col} :: {b.name}")
    lines.append(
        f"stats funcs={stats['funcs']} structs={stats['structs']} "
        f"stmts={stats['stmts']}"
    )
    return lines
