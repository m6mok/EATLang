"""Драйвер модулей (docs/MODULES_PLAN.md §4).

У языка нет файловой системы — компилятор потребляет один поток.
Драйвер читает import-шапки, строит DAG модулей от главного файла,
проверяет циклы, топологически сортирует (при равенстве —
лексикографически по каноническому пути: порядок детерминирован,
поток байт-в-байт) и конкатенирует модули, ставя перед каждым
директиву `#module "путь"`. Первым — selfhost/Rt.eat без директивы:
неявный нулевой модуль, его имена видимы всем.

Разрешение пути импорта: (1) относительно импортирующего файла,
(2) корни из `--lib`-флагов CLI в порядке задания. Канонический путь —
относительный к рабочему каталогу, разделитель `/`. Компилятор
сверяет строку из `from "..."` с каноническими путями модулей раньше
по потоку, поэтому пути в import пишутся от корня проекта
(`--lib .` в Makefile делает канонику равной написанному).
"""

import os
from pathlib import Path

from . import ast_nodes as ast
from .errors import EatError
from .parser import parse_file

# repo-корень: src/eatc/driver.py -> два уровня вверх от пакета
_RT_PATH = Path(__file__).resolve().parents[2] / "selfhost" / "Rt.eat"


def has_imports(program: ast.Program) -> bool:
    return any(isinstance(d, ast.ImportBlock) for d in program.decls)


def _canon(path: Path) -> str:
    return Path(os.path.relpath(path.resolve())).as_posix()


def _resolve_spec(
    spec: str, importer: Path, lib_roots: list, node: ast.Node, fname: str
) -> Path:
    cand = importer.parent / spec
    if cand.is_file():
        return cand
    for root in lib_roots:
        cand = Path(root) / spec
        if cand.is_file():
            return cand
    raise EatError(
        fname,
        node.line,
        node.col,
        f'import из "{spec}": файл не найден (искали относительно '
        f"{importer.parent or '.'} и в --lib-корнях "
        f"{[str(r) for r in lib_roots]})",
    )


def resolve_modules(main_path: str, lib_roots: list) -> list:
    """[(канонический путь, исходный текст)] в порядке потока:
    зависимости раньше зависимых, главный модуль последним."""
    main = Path(main_path)
    if not main.is_file():
        raise EatError(main_path, 1, 1, "файл не найден")
    main_canon = _canon(main)
    sources: dict[str, str] = {}
    deps: dict[str, list] = {}
    state: dict[str, int] = {}  # 1 — в обходе (цикл!), 2 — готов

    def visit(canon: str, path: Path, chain: list) -> None:
        if state.get(canon) == 2:
            return
        if state.get(canon) == 1:
            cycle = " -> ".join(chain[chain.index(canon):] + [canon])
            raise EatError(
                canon, 1, 1,
                f"цикл импортов: {cycle} (модули обязаны допускать "
                "линейный порядок — docs/MODULES_PLAN.md §3)",
            )
        state[canon] = 1
        program = parse_file(str(path))
        sources[canon] = path.read_text(encoding="utf-8")
        deps[canon] = []
        for decl in program.decls:
            if not isinstance(decl, ast.ImportBlock):
                continue
            target = _resolve_spec(
                decl.path, path, lib_roots, decl, canon
            )
            tcanon = _canon(target)
            if tcanon not in deps[canon]:
                deps[canon].append(tcanon)
            visit(tcanon, target, chain + [canon])
        state[canon] = 2

    visit(main_canon, main, [])

    # Kahn: из готовых к выпуску всегда берётся лексикографически
    # меньший канонический путь — порядок детерминирован байт-в-байт
    emitted: list[str] = []
    done: set = set()
    pending = set(deps)
    while pending:
        ready = sorted(
            m for m in pending if all(d in done for d in deps[m])
        )
        assert ready, "цикл импортов пропущен обходом"  # visit ловит раньше
        m = ready[0]
        pending.discard(m)
        done.add(m)
        emitted.append(m)
    return [(canon, sources[canon]) for canon in emitted]


def build_stream(main_path: str, lib_roots: list) -> str:
    """Поток компиляции: Rt.eat (неявный нулевой модуль) + модули DAG,
    каждый за своей директивой `#module`."""
    if not _RT_PATH.is_file():
        raise EatError(str(_RT_PATH), 1, 1, "не найден рантайм-модуль")
    parts = [_RT_PATH.read_text(encoding="utf-8")]
    for canon, text in resolve_modules(main_path, lib_roots):
        if not text.endswith("\n"):
            text += "\n"
        parts.append(f'#module "{canon}"\n{text}')
    return "".join(parts)
