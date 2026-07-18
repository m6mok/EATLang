"""Структурные проверки Power of 10, возможные сразу после парсинга.

Правило 4  — функция не длиннее 60 statements.
Правило 5  — контракты опциональны: отсутствие клаузы ≡ `true`
             (содержательный контракт пишется явно; SPEC §5.2).
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


def merge_extends(program: ast.Program, filename: str) -> None:
    """extend ИМЯ { методы } (SPEC §4): методы сливаются в struct,
    объявленный раньше по потоку в том же модуле, как если бы были
    объявлены в его блоке; узел extend исчезает из decls — фазы ниже
    парсера различий не видят."""
    structs: dict = {}
    struct_module: dict = {}
    module = 0
    decls = []
    for decl in program.decls:
        if isinstance(decl, ast.ModuleMark):
            module += 1
        elif isinstance(decl, ast.StructDecl):
            structs[decl.name] = decl
            struct_module[decl.name] = module
        elif isinstance(decl, ast.ExtendDecl):
            src = getattr(decl, "src_file", None) or filename
            target = structs.get(decl.name)
            if target is None:
                raise EatError(
                    src,
                    decl.line,
                    decl.col,
                    f"extend {decl.name}: struct не объявлен раньше "
                    "по потоку",
                )
            if struct_module[decl.name] != module:
                raise EatError(
                    src,
                    decl.line,
                    decl.col,
                    f"extend {decl.name}: struct объявлен в другом модуле",
                )
            for m in decl.methods:
                if any(m.name == x.name for x in target.methods):
                    raise EatError(
                        getattr(m, "src_file", None) or filename,
                        m.line,
                        m.col,
                        f"метод {m.name} уже объявлен в struct {decl.name}",
                    )
                target.methods.append(m)
            continue
        decls.append(decl)
    program.decls = decls


def check_program(program: ast.Program, filename: str) -> dict:
    merge_extends(program, filename)
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
        # extern: тела нет — правило 4 не применимо, контракты обязательны
        n = count_stmts(func.body) if func.body is not None else 0
        total_stmts += n
        if n > MAX_STMTS_PER_FUNC:
            raise EatError(
                getattr(func, "src_file", None) or filename,
                func.line,
                func.col,
                f"функция {func.name}: {n} statements — длиннее "
                f"{MAX_STMTS_PER_FUNC} (правило 4)",
            )
        # Правило 5 (форма): контракт опционален — отсутствие клаузы ≡
        # `requires true` / `ensures true`. Содержательный контракт
        # пишется явно, тривиальный опускается (DX_PLAN §6.5, SPEC §5.2).
        # Отсутствующий узел уже трактуется как `true` во всех бэкендах
        # (codegen/interpreter guard `is not None`), поэтому здесь —
        # ничего не требуем.

    structs = sum(isinstance(d, ast.StructDecl) for d in program.decls)
    tests = sum(isinstance(d, ast.TestBlock) for d in program.decls)
    return {
        "funcs": len(funcs),
        "structs": structs,
        "tests": tests,
        "stmts": total_stmts,
    }
