#!/usr/bin/env python3
"""Плоская версия lib/json/Json.eat для склейки LSP-сервера.

LSP-сервер (docs/plans/LSP_PLAN.md, этап 1) линкуется ПЛОСКОЙ
конкатенацией (модуль 0): фазы selfhost/ не экспортируют символы, а
модульный драйвер и плоская склейка не сочетаются. В плоском потоке
все имена глобальны, поэтому import-блоки не нужны — и запрещены
(проверка требует #module-границы, которых в склейке нет).

Этот скрипт снимает import-блоки с lib/json/Json.eat, оставляя export
(в склейке безвреден) и весь код. Символы, которые Json импортирует
(hex_val, is_digit, digit_value), уже глобальны из LIB_FRONT
(lib/fmt/Hex.eat, lib/fmt/Ascii.eat). Результат — build/JsonFlat.eat,
производный артефакт (не коммитится, пересобирается из Json.eat).

Запуск: python3 tools/json_flat.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "lib" / "json" / "Json.eat"
OUT = ROOT / "build" / "JsonFlat.eat"

# import-блок: `import {\n ... \n} from "путь"\n` (без вложенных `{`).
_IMPORT = re.compile(r'import \{[^}]*\} from "[^"]*"\n')


def main() -> int:
    text = SRC.read_text(encoding="utf-8")
    flat = _IMPORT.sub("", text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(flat, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
