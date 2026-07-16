#!/usr/bin/env python3
"""Проверка стиля исходников .eat (REFACTOR_SELFHOST_PLAN, этап 1).

Потолки репозитория (не языка — языковой предел §6 SPEC был бы
отдельным решением, D3 плана):

- длина строки ≤ 100 кодпойнтов Unicode (len(str) в Python; не байт —
  кириллица в UTF-8 двухбайтная);
- строк на файл selfhost/ ≤ MAX_FILE_LINES — включается на этапе 4
  (распил Check/Ir/Verify), до него потолок выключен (None).

Гоняется первым шагом `make check` по всем *.eat репозитория, кроме
сгенерированных (build/) и окружения (.venv/).
"""

import pathlib
import sys

MAX_LINE = 100          # кодпойнтов на строку, все *.eat
MAX_FILE_LINES = None   # строк на файл selfhost/; этап 4 включит (2500)
SKIP_PARTS = {"build", ".venv"}

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    failures = 0
    for path in sorted(ROOT.rglob("*.eat")):
        rel = path.relative_to(ROOT)
        if SKIP_PARTS & set(rel.parts):
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, 1):
            if len(line) > MAX_LINE:
                print(f"{rel}:{lineno}: строка {len(line)} > {MAX_LINE} кодпойнтов")
                failures += 1
        if MAX_FILE_LINES is not None and rel.parts[0] == "selfhost":
            if len(lines) > MAX_FILE_LINES:
                print(f"{rel}: файл {len(lines)} > {MAX_FILE_LINES} строк")
                failures += 1
    if failures:
        print(f"check_style: нарушений — {failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
