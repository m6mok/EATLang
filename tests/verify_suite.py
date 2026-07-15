"""Регрессионный набор верификатора.

Каждый кейс в tests/verify/*.eat объявляет ожидание в первой строке:

    #! expect: bounds=1/1 overflow=2/2

Ключи — виды проверок (overflow, div, bounds, cast, requires,
ensures, assert), значения — «доказано/всего». Перечисленные виды
сравниваются точно; неперечисленные игнорируются. Ожидание вида
`x=0/1` — обязательное «НЕ доказано» (защита от ложных доказательств).

Отдельный вид — негатив компиляции: `#! expect: error=<подстрока>`
(остаток строки целиком) — кейс обязан упасть на parse/check/typecheck
с EatError, содержащей подстроку.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from eatc.checks import check_program  # noqa: E402
from eatc.errors import EatError  # noqa: E402
from eatc.parser import parse_file  # noqa: E402
from eatc.typechecker import typecheck  # noqa: E402
from eatc.verifier import verify, verify_dump  # noqa: E402


def parse_expectations(path: Path) -> dict:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#! expect:"):
            body = line.removeprefix("#! expect:").strip()
            if body.startswith("error="):
                # подстрока ошибки — остаток строки целиком (с пробелами)
                return {"error": body.removeprefix("error=")}
            return {
                k: v for k, v in (p.split("=", 1) for p in body.split())
            }
    raise ValueError(f"{path}: нет строки '#! expect:'")


def run_case(path: Path) -> list[str]:
    expects = parse_expectations(path)
    if "error" in expects:
        want = expects["error"]
        try:
            program = parse_file(str(path))
            check_program(program, str(path))
            typecheck(program, str(path))
        except EatError as err:
            if want in str(err):
                return []
            return [f"error: ожидалось «{want}», получено «{err}»"]
        return [f"error: ожидалось «{want}», но компиляция прошла"]
    program = parse_file(str(path))
    check_program(program, str(path))
    typed = typecheck(program, str(path))
    stats = verify(program, typed.checker)
    actual = {
        kind: f"{v[0]}/{v[1]}" for kind, v in stats["by_kind"].items()
    }
    failures = []
    # Дамп `eatc verify` (SELFHOST_VERIFIER_PLAN этап 0) — источник
    # тех же чисел, что и `#! expect:`: агрегат построчных обязательств
    # обязан сходиться со stats
    dumped: dict = {}
    for line in verify_dump(program, typed.checker)[:-1]:
        kind, _pos, verdict = line.split()
        entry = dumped.setdefault(kind, [0, 0])
        entry[1] += 1
        entry[0] += 1 if verdict == "proven" else 0
    if dumped != stats["by_kind"]:
        failures.append("дамп eatc verify расходится со stats верификатора")
    for kind, want in expects.items():
        got = actual.get(kind, "0/0")
        if got != want:
            failures.append(f"{kind}: ожидалось {want}, получено {got}")
    return failures


def main() -> int:
    cases = sorted((Path(__file__).parent / "verify").glob("*.eat"))
    if not cases:
        print("нет кейсов в tests/verify/", file=sys.stderr)
        return 2
    failed = 0
    for path in cases:
        try:
            failures = run_case(path)
        except (EatError, ValueError) as err:
            print(f"ERROR {path.name}: {err}")
            failed += 1
            continue
        if failures:
            failed += 1
            print(f"FAIL {path.name}: {'; '.join(failures)}")
        else:
            print(f"PASS {path.name}")
    total = len(cases)
    print(f"\n{total - failed}/{total} кейсов прошло")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
