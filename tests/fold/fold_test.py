"""Регресс яруса B (§11 COMPTIME_PLAN): свёртка вызовов в телах.

Три исхода свёртки (§1): вычислилось → литерал; trap → НЕ сворачивать
(рантайм-вызов остаётся, trap'нет там же); нечистая/негодная → не
сворачивать. Плюс паритет значения: свёрнутый литерал == результат
интерпретатора-эталона (тот же вычислитель). Тест не линкует бинарники —
работает на AST/аннотациях, потому дёшев и детерминирован.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from eatc import ast_nodes as ast  # noqa: E402
from eatc.comptime import fold_calls  # noqa: E402
import eatc.__main__ as M  # noqa: E402

RT = str(ROOT / "selfhost" / "Rt.eat")


def _compile(src: str, tmp: Path):
    tmp.write_text(src, encoding="utf-8")
    program, _, typed, main = M._compile_many([RT, str(tmp)])
    return program, typed, main


def _calls(program, fn_name: str):
    """Все узлы Call в теле функции fn_name (для проверки folded)."""
    out: list = []

    def walk(node):
        if node is None or isinstance(node, (str, int, bool)):
            return
        if isinstance(node, ast.Call):
            out.append(node)
        for a in ("body", "value", "obj", "index", "left", "right",
                  "operand", "expr", "target", "cond", "then", "els",
                  "start", "end", "iterable"):
            c = getattr(node, a, None)
            if isinstance(c, list):
                for x in c:
                    walk(x)
            elif c is not None and not isinstance(c, (str, int, bool)):
                walk(c)
        for lst in ("stmts", "args", "elems", "elifs"):
            s = getattr(node, lst, None)
            if isinstance(s, list):
                for x in s:
                    if isinstance(x, tuple):
                        for y in x:
                            walk(y)
                    else:
                        walk(x)

    for d in program.decls:
        if isinstance(d, ast.FuncDecl) and d.name == fn_name:
            walk(d.body)
    return out


FOLDABLE = """
func sq(x: u32) -> u32
    requires x < 1000
    ensures true
{
    return x * x + 1
}

func main() {
    let a: u32 = sq(9)
    write_byte(u8(a % 256))
}
"""

TRAP = """
func boom(x: u32) -> u32
    requires true
    ensures true
{
    return x / 0
}

func main() {
    let a: u32 = boom(5)
    write_byte(u8(a % 256))
}
"""

IMPURE = """
func loud(x: u32) -> u32
    requires true
    ensures true
{
    write_byte(u8(x))
    return x
}

func main() {
    let a: u32 = loud(7)
    write_byte(u8(a % 256))
}
"""

NONCONST_ARG = """
func sq(x: u32) -> u32
    requires x < 1000
    ensures true
{
    return x * x
}

func main() {
    let n: u32 = 4
    let a: u32 = sq(n)
    write_byte(u8(a % 256))
}
"""


def run() -> list:
    fails: list = []
    tmp = ROOT / "tests" / "fold" / "_case.eat"
    try:
        # 1. годный вызов сворачивается, значение == эталону (9*9+1=82)
        program, typed, _ = _compile(FOLDABLE, tmp)
        n = fold_calls(program, typed.checker, str(tmp))
        call = _calls(program, "main")[0]
        if n != 1:
            fails.append(f"foldable: свёрнуто {n}, ожидалось 1")
        if not getattr(call, "folded", False):
            fails.append("foldable: вызов sq(9) не помечен folded")
        elif call.fold_value != 82:
            fails.append(f"foldable: значение {call.fold_value}, ожид. 82")

        # 2. trap при вычислении → не сворачивать (вызов остаётся)
        program, typed, _ = _compile(TRAP, tmp)
        n = fold_calls(program, typed.checker, str(tmp))
        call = _calls(program, "main")[0]
        if n != 0 or getattr(call, "folded", False):
            fails.append("trap: деление на ноль не должно сворачиваться")

        # 3. нечистая (write_byte) → негодна → не сворачивать
        program, typed, _ = _compile(IMPURE, tmp)
        n = fold_calls(program, typed.checker, str(tmp))
        call = [c for c in _calls(program, "main") if c.name == "loud"][0]
        if n != 0 or getattr(call, "folded", False):
            fails.append("impure: нечистый вызов не должен сворачиваться")

        # 4. аргумент — локаль (не константа) → не сворачивать (v1)
        program, typed, _ = _compile(NONCONST_ARG, tmp)
        n = fold_calls(program, typed.checker, str(tmp))
        call = [c for c in _calls(program, "main") if c.name == "sq"][0]
        if n != 0 or getattr(call, "folded", False):
            fails.append("nonconst-arg: sq(n) с локалью не сворачивается")
    finally:
        tmp.unlink(missing_ok=True)
    return fails


if __name__ == "__main__":
    problems = run()
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        print(f"\n{len(problems)} провалов")
        sys.exit(1)
    print("ЯРУС B OK (4/4: свёртка, trap, нечистая, локаль-аргумент)")
