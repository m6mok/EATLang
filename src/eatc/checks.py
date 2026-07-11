"""Структурные проверки Power of 10, возможные сразу после парсинга.

Правило 4  — функция не длиннее 60 statements.
Правило 5  — обязательные контракты: у функции с параметрами requires,
             с возвращаемым значением ensures.
Пределы    — число функций в программе.

Проверки, требующие типов и графа вызовов (правила 1, 2, 6, 7, 10),
живут в тайпчекере и семантическом анализе.
"""

from . import ast_nodes as ast
from .errors import CapacityError, EatError
from .limits import MAX_FUNCS_PER_PROGRAM, MAX_STMTS_PER_FUNC


def count_stmts(block: ast.Block) -> int:
    total = 0
    for stmt in block.stmts:
        total += 1
        if isinstance(stmt, ast.IfStmt):
            total += count_stmts(stmt.then)
            for _, blk in stmt.elifs:
                total += count_stmts(blk)
            if stmt.els is not None:
                total += count_stmts(stmt.els)
        elif isinstance(stmt, (ast.ForStmt, ast.LoopStmt)):
            total += count_stmts(stmt.body)
        elif isinstance(stmt, ast.MatchStmt):
            for arm in stmt.arms:
                total += count_stmts(arm.body)
    return total


def _all_funcs(program: ast.Program):
    for decl in program.decls:
        if isinstance(decl, ast.FuncDecl):
            yield decl
        elif isinstance(decl, ast.StructDecl):
            yield from decl.methods


def check_program(program: ast.Program, filename: str) -> dict:
    funcs = list(_all_funcs(program))
    if len(funcs) > MAX_FUNCS_PER_PROGRAM:
        raise CapacityError(
            filename,
            program.line,
            program.col,
            "функций в программе",
            MAX_FUNCS_PER_PROGRAM,
        )

    total_stmts = 0
    for func in funcs:
        n = count_stmts(func.body)
        total_stmts += n
        if n > MAX_STMTS_PER_FUNC:
            raise EatError(
                filename,
                func.line,
                func.col,
                f"функция {func.name}: {n} statements — длиннее "
                f"{MAX_STMTS_PER_FUNC} (правило 4)",
            )
        has_params = (
            any(p.name != "self" for p in func.params) or func.is_method
        )
        if has_params and func.requires is None:
            raise EatError(
                filename,
                func.line,
                func.col,
                f"функция {func.name} с параметрами обязана иметь requires; "
                "осознанный отказ — `requires true` (правило 5)",
            )
        if func.ret is not None and func.ensures is None:
            raise EatError(
                filename,
                func.line,
                func.col,
                f"функция {func.name} с возвращаемым значением обязана иметь "
                "ensures; осознанный отказ — `ensures true` (правило 5)",
            )

    structs = sum(isinstance(d, ast.StructDecl) for d in program.decls)
    tests = sum(isinstance(d, ast.TestBlock) for d in program.decls)
    return {
        "funcs": len(funcs),
        "structs": structs,
        "tests": tests,
        "stmts": total_stmts,
    }
