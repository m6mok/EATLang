"""Каталог недоказанных проверок верификатора (трек 3).

Запуск из корня:
  uv run python tests/verify_catalog.py <файлы.eat...> [--top N]

Собирает программу как `eatc build`, гоняет верификатор и печатает:
  - сводку по видам (доказано/всего);
  - топ кластеров недоказанного (вид + файл), с примерами строк;
  - гистограмму по файлам.
Это карта работ: бить по самым частым классам (docs/TRACKS.md, трек 3).
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eatc.checks import check_program  # noqa: E402
from eatc.parser import parse_files  # noqa: E402
from eatc.typechecker import typecheck  # noqa: E402
from eatc.verifier import Verifier  # noqa: E402


def load_program(paths):
    """Многомодульная программа как в eatc build (_compile_many)."""
    main = paths[-1]
    program = parse_files(paths)
    check_program(program, main)
    typed = typecheck(program, main)
    return program, typed


def main(argv):
    top = 10
    if "--top" in argv:
        i = argv.index("--top")
        top = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        print(__doc__)
        return 2
    program, typed = load_program(argv)
    v = Verifier(program, typed.checker)
    stats = v.run()
    print(f"доказано {stats['proven']} из {stats['total']}")
    for kind, (ok, tot) in sorted(stats["by_kind"].items()):
        print(f"  {kind}: {ok}/{tot} (остаток {tot - ok})")

    clusters: Counter = Counter()
    samples: dict = defaultdict(list)
    by_file: Counter = Counter()
    for (kind, _), (ok, node) in v.checks.items():
        if ok:
            continue
        src = getattr(node, "src_file", None) or "<main>"
        line = getattr(node, "line", 0)
        key = (kind, src)
        clusters[key] += 1
        if len(samples[key]) < 3:
            samples[key].append(line)
        by_file[src] += 1

    print(f"\nтоп-{top} кластеров недоказанного (вид × файл):")
    for (kind, src), n in clusters.most_common(top):
        lines = ", ".join(str(x) for x in sorted(samples[(kind, src)]))
        print(f"  {n:5d}  {kind:9s} {src} (строки: {lines}, ...)")

    print("\nпо файлам:")
    for src, n in by_file.most_common():
        print(f"  {n:5d}  {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
