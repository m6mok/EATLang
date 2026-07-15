#!/usr/bin/env python3
"""Регенерация инициализатора `Verify { ... }` в selfhost/VerifyMain.eat.

Гигантский литерал состояния верификатора (сотни полей struct St,
Check, Verify) — нуль-инициализация, кроме `Check.p: p` (уже собранный
Parser) и горстки полей-сентинелов (NONE). При добавлении поля в
struct St / struct Verify (этап 2+ верификатора) литерал ломается —
этот скрипт пересобирает его из объявлений полей, чтобы правка была
воспроизводимой (не ручная).

Не трогает литералы `Lexer {...}` и `Parser {...}` в main() — у них
ненулевые начальные значения (line: 1, col: 1, …), они пишутся руками.

Запуск:  python3 tools/gen_verifymain.py   (перезаписывает VerifyMain.eat)
         python3 tools/gen_verifymain.py --check  (только сверка, код 1 при расхождении)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    ROOT / "selfhost" / "Verify.eat",
    ROOT / "selfhost" / "Check.eat",
]
TARGET = ROOT / "selfhost" / "VerifyMain.eat"

# Поля, инициализируемые сентинелом NONE (а не нулём).
NONE_FIELDS = {"fhx", "cnd", "cca_bs", "res_expr"}


def parse_structs(text):
    """{имя struct: [(поле, тип), ...]} — поля до первого метода."""
    structs = {}
    i = 0
    lines = text.splitlines()
    while i < len(lines):
        m = re.match(r"struct (\w+) \{", lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        fields = []
        i += 1
        while i < len(lines) and not lines[i].startswith("}"):
            line = lines[i].split("#", 1)[0].rstrip()
            fm = re.match(r"\s+(\w+): (.+)$", line)
            if re.match(r"\s+func ", lines[i]):
                # начались методы — поля кончились; домотать до конца struct
                depth = 1
                while i < len(lines) and depth > 0:
                    depth += lines[i].count("{") - lines[i].count("}")
                    i += 1
                break
            if fm:
                fields.append((fm.group(1), fm.group(2).strip()))
            i += 1
        structs[name] = fields
    return structs


def zero(field, ty, structs):
    """Нуль-значение поля типа ty (рекурсивно для вложенных struct)."""
    if ty == "bool":
        return "false"
    m = re.match(r"\[\[(\w+); (\d+)\]; (\d+)\]$", ty)
    if m:
        return f"[[0; {m.group(2)}]; {m.group(3)}]"
    m = re.match(r"\[(\w+); (\d+)\]$", ty)
    if m:
        elem, n = m.group(1), m.group(2)
        if elem in structs:
            return f"[{struct_lit(elem, structs)}; {n}]"
        fill = "NONE" if field in NONE_FIELDS else "0"
        return f"[{fill}; {n}]"
    if ty in structs:
        return struct_lit(ty, structs)
    if field in NONE_FIELDS:
        return "NONE"
    return "0"


def struct_lit(name, structs):
    parts = []
    for field, ty in structs[name]:
        # Check.p — уже собранный Parser (локальная переменная p)
        if name == "Check" and field == "p" and ty == "Parser":
            parts.append("p: p")
        else:
            parts.append(f"{field}: {zero(field, ty, structs)}")
    return f"{name} {{ " + ", ".join(parts) + " }"


def main():
    text = "\n".join(f.read_text(encoding="utf-8") for f in FILES)
    structs = parse_structs(text)
    lit = struct_lit("Verify", structs)
    line = f"            var v: Verify = {lit}"

    src = TARGET.read_text(encoding="utf-8")
    new = re.sub(
        r"^ +var v: Verify = Verify \{.*\}$",
        lambda _: line,
        src,
        count=1,
        flags=re.MULTILINE,
    )
    if "--check" in sys.argv:
        if new != src:
            sys.stderr.write("VerifyMain.eat расходится с генератором\n")
            return 1
        return 0
    TARGET.write_text(new, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
