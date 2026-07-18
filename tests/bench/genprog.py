"""Генераторы синтетических .eat-программ для нагрузочного тестирования.

Два семейства входов:
  * gen_module / gen_program — валидные программы ступенчатых размеров
    для замеров пайплайна (lex/parse/typed/ir) и многомодульной сборки;
  * stress_* — входы на лимитах SPEC.md §6 и сразу за ними: компилятор
    обязан либо принять файл, либо быстро упасть с внятной ошибкой.

Шаблон функции подобран под лимиты: ≤ 54 операторов (предел 60),
2 параметра (предел 6), плоские выражения (предел глубины 32),
арифметика по модулю 65536 — не переполняет u32 в рантайме.
Цепочки вызовов bench_fN → bench_fN-1 рвутся на границах групп
CALL_GROUP, чтобы глубина стека вызовов оставалась малой.
"""

CALL_GROUP = 32  # длина цепочки вызовов внутри группы функций
STMTS_PER_FUNC = 54


def _fname(idx: int) -> str:
    return f"bench_f{idx:05d}"


def gen_func(idx: int) -> str:
    """Одна синтетическая функция: ~850 токенов, тип-корректна."""
    lines = [
        f"func {_fname(idx)}(a: u32, b: u32) -> u32",
        "    requires true",
        "    ensures true",
        "{",
        "    var x0: u32 = a % 1024",
        "    var x1: u32 = b % 1024",
    ]
    stmts = 2
    if idx % CALL_GROUP != 0:
        lines.append(
            f"    x0 = (x0 + {_fname(idx - 1)}(x1, x0)) % 65536"
        )
        stmts += 1
    k = 0
    while stmts < STMTS_PER_FUNC - 1:
        lines.append(f"    x0 = (x0 * 31 + x1 + {k % 97}) % 65536")
        lines.append(f"    x1 = (x1 * 17 + x0 + {k % 89}) % 65536")
        stmts += 2
        k += 1
    lines.append("    return (x0 + x1) % 65536")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def gen_main(func_indexes) -> str:
    """main суммирует головы групп; ≤ 60 операторов."""
    lines = ["func main() {", "    var acc: u32 = 0"]
    for i in func_indexes:
        lines.append(f"    acc = (acc + {_fname(i)}(3, 5)) % 65536")
    lines.append('    print("checksum {acc}")')
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def gen_module(start: int, n_funcs: int, with_main: bool = False,
               total_funcs: int | None = None) -> str:
    """Модуль из n_funcs функций с индексами start..start+n_funcs-1.

    with_main добавляет main, который вызывает головы групп всего
    диапазона 0..total_funcs (по умолчанию — этого модуля).
    """
    parts = ["# Синтетический модуль нагрузочного теста (genprog.py)", ""]
    for i in range(start, start + n_funcs):
        parts.append(gen_func(i))
    if with_main:
        total = total_funcs if total_funcs is not None else start + n_funcs
        heads = [i for i in range(0, total, CALL_GROUP)]
        # последняя функция цепочки каждой группы — её хвост
        tails = [min(h + CALL_GROUP, total) - 1 for h in heads]
        parts.append(gen_main(tails[:56]))
    return "\n".join(parts)


def gen_program(n_funcs: int, funcs_per_file: int):
    """Многомодульная программа: список текстов файлов, main — в последнем."""
    files = []
    start = 0
    while start < n_funcs:
        n = min(funcs_per_file, n_funcs - start)
        last = start + n >= n_funcs
        files.append(gen_module(start, n, with_main=last,
                                total_funcs=n_funcs))
        start += n
    return files


# ==== Стресс лимитов (SPEC.md §6) =======================================

def stress_tokens(n_tokens: int) -> str:
    """~n_tokens токенов: идентификаторы + переводы строк. Только для lex."""
    per_line = 63  # 63 идентификатора + NEWLINE = 64 токена на строку
    lines = []
    total = 0
    while total < n_tokens:
        lines.append(" ".join("x" for _ in range(per_line)))
        total += per_line + 1
    return "\n".join(lines) + "\n"


def stress_funcs(n_funcs: int) -> str:
    """n_funcs функций всего (включая main) — предел 2048."""
    parts = []
    for i in range(n_funcs - 1):
        parts.append(
            f"func tiny{i:05d}() -> u32\n"
            "    requires true\n"
            "    ensures true\n"
            "{\n"
            f"    return {i % 100}\n"
            "}\n"
        )
    parts.append('func main() {\n    print("ok")\n}\n')
    return "\n".join(parts)


def stress_stmts(n_stmts: int) -> str:
    """Одна функция с n_stmts операторами — предел 60."""
    lines = ["func main() {", "    var x: u32 = 0"]
    for i in range(n_stmts - 1):
        lines.append(f"    x = (x + {i % 100}) % 65536")
    lines.append("}")
    return "\n".join(lines) + "\n"


def stress_block_depth(depth: int) -> str:
    """Вложенные if — предел глубины блоков 8 (тело функции — уровень 1)."""
    lines = ["func main() {", "    var x: u32 = 0"]
    pad = "    "
    for d in range(depth - 1):
        lines.append(pad * (d + 1) + "if true {")
    lines.append(pad * depth + "x = 1")
    for d in range(depth - 1, 0, -1):
        lines.append(pad * d + "}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def stress_expr_depth(parens: int) -> str:
    """Выражение из parens вложенных скобок — предел глубины AST 32."""
    expr = "(" * parens + "1" + ")" * parens
    return (
        "func main() {\n"
        f"    var x: u32 = {expr}\n"
        '    print("x {x}")\n'
        "}\n"
    )
