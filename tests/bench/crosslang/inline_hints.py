"""Разведка §7.6, кандидат 2 (этап 1): инлайн-хинты малых листовых
функций post-parse в build-конвейере (Python-only, канон .ll не
меняется).

Эвристика — codegen.inline_hints (порог «малости» T инструкций в
теле + бюджет роста B = размер × (call-site'ов − 1); «листовая» —
замыкание снизу вверх по графу вызовов: DAG, рекурсии в языке нет).
Строгий лист — частный случай; из четырёх хелперов 37-й итерации
(`ea_mem`/`ea_alu`/`shift_val`/`flags_byte`) строгий лист только
последний. По вердикту этапа 1 ручка посажена в `eatc build`
(T=384, B=768) — вариант «llvmlite без хинтов» строится репликой.

Варианты на байт-идентичном .ll (различие — только атрибут):

- build (llvmlite)      — штатный `eatc build` (с хинтами после
  посадки; конвейер: NewPM speed_level=2 + machine opt=2
  emit_object + clang-линк .o);
- llvmlite без хинтов   — та же реплика конвейера, атрибутов нет
  (базовая точка «до»);
- +hints T=N[,B=M]      — реплика с post-parse атрибутами через
  ValueRef.add_function_attribute (как 37-я итерация);
- .ll → clang -O2       — тот же текстовый .ll целиком через clang;
- .ll+hints → clang     — атрибут дописан в define-строки текста
  (сверка: снятие атрибута возвращает исходник байт-в-байт);
- C -O2                 — якорь (порт есть у strcmp/u128/mos6502).

Методика замера — run.py (медиана 5 прямых прогонов, счётчики
/usr/bin/time -l), сверка stdout всех вариантов байт-в-байт.

Запуск: uv run python tests/bench/crosslang/inline_hints.py
        [--quick] [--only strcmp,mos6502] [--limits 64,160]
        [--json PATH]
"""

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))
import run as cl        # noqa: E402 — методика и сборки crosslang
import backends as bk   # noqa: E402 — measure_entries, STACK, _machine
from eatc.codegen import inline_hints  # noqa: E402 — сама эвристика

# (имя программы, базовых операций, REPEAT full, REPEAT quick, libs);
# numparse нет в реестре crosslang — REPEAT как в make bench (×64)
BENCH_DEFS = {
    "strcmp": ("StrCmpBench", 20_000, 128, 16, []),
    "numparse": ("NumParseBench", 200_000, 64, 8, ["lib/fmt/Parse.eat"]),
    "u128": ("U128Bench", 20_000, 1024, 64, "driver"),
}
C_PORTS = {"strcmp", "u128"}  # у numparse C-порта нет

LIMITS = [32, 64, 96, 128, 160, 224, 384]


# ---------------------------------------------------------------------------
# Сборки: llvmlite-путь (реплика compile_binary) и clang-путь по тексту
# Эвристика — сама codegen.inline_hints (переехала по вердикту этапа 1)

def llvmlite_bin(src_ll: Path, bin_: Path, limit=None,
                 budget=None) -> set:
    """Реплика конвейера `eatc build` от готового .ll; limit=None —
    без хинтов (штатный путь ДО посадки ручки), иначе post-parse
    атрибуты; budget=None — без ограды роста."""
    llvm, machine = bk._machine()
    ref = llvm.parse_assembly(src_ll.read_text(encoding="utf-8"))
    ref.verify()
    names = set()
    if limit:
        names = set(inline_hints(
            ref, limit, budget if budget is not None else 1 << 60))
    pto = llvm.create_pipeline_tuning_options(speed_level=2)
    pb = llvm.create_pass_builder(machine, pto)
    pb.getModulePassManager().run(ref, pb)
    obj = bin_.with_suffix(".o")
    obj.write_bytes(machine.emit_object(ref))
    cl.sh(["clang", "-O2", obj, cl.RUNTIME_C, "-o", bin_] + bk.STACK)
    obj.unlink()
    return names


def hinted_ll(src_ll: Path, dst_ll: Path, names: set):
    """Текстовая копия .ll с ` alwaysinline` в define-строках names;
    сверка байт-идентичности: снятие атрибута возвращает исходник."""
    src = src_ll.read_text(encoding="utf-8")
    out = []
    for line in src.splitlines(keepends=True):
        if line.startswith("define"):
            m = re.match(r'define[^@]*@"([^"]+)"', line)
            if m and m.group(1) in names:
                line = line.rstrip("\n") + " alwaysinline\n"
        out.append(line)
    text = "".join(out)
    assert text.replace(" alwaysinline\n", "\n") == src, \
        f"{dst_ll}: правка не свелась к атрибуту"
    dst_ll.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------

def variant_entries(ll: Path, stem: str, limits, base_entries,
                    budget=None):
    """base_entries + пары (llvmlite, clang) на каждый порог."""
    entries = list(base_entries)
    btag = f",B={budget}" if budget is not None else ""
    prev = set()
    for lim in limits:
        b = cl.OUT / f"{stem}_hints{lim}"
        names = llvmlite_bin(ll, b, limit=lim, budget=budget)
        fresh = sorted(n for n in names - prev)
        print(f"  T={lim}{btag}: помечено {len(names)}"
              + (f" (+{len(fresh)}: {', '.join(fresh)})" if fresh else
                 " (без новых)"))
        if names == prev and prev:
            print(f"  T={lim}{btag}: набор не вырос — вариант пропущен")
            continue
        prev = set(names)
        entries.append((f"+hints T={lim}{btag} (llvmlite)", [b], b))
        hll = cl.OUT / f"{stem}_hints{lim}.ll"
        hinted_ll(ll, hll, names)
        bc = cl.OUT / f"{stem}_hints{lim}_clang"
        bk.clang_bin(hll, bc)
        entries.append((f".ll+hints T={lim}{btag} → clang -O2", [bc], bc))
    return entries


def bench_micro(key, quick, limits, rows, budget=None):
    name, base_ops, rep_full, rep_quick, libs = BENCH_DEFS[key]
    rep = rep_quick if quick else rep_full
    runs = cl.RUNS_QUICK if quick else cl.RUNS_FULL
    print(f"\n=== {key} ({name}, REPEAT={rep}) ===")

    cmd, bin_, _secs = cl.build_eat(name, f"ih_{key}", libs, rep)
    ll = bin_.with_suffix(".ll")
    assert ll.exists(), f"{ll}: build не оставил .ll"

    base = [("build (llvmlite)", cmd, bin_)]
    bn = cl.OUT / f"ih_{key}_nohints"
    llvmlite_bin(ll, bn)
    base.append(("llvmlite без хинтов", [bn], bn))
    bc = cl.OUT / f"ih_{key}_clang"
    bk.clang_bin(ll, bc)
    base.append((".ll → clang -O2", [bc], bc))
    if key in C_PORTS:
        base.append(("C -O2",) + cl.build_c(key, rep)[:2])
    entries = variant_entries(ll, f"ih_{key}", limits, base,
                              budget)
    bk.measure_entries(rows, key, runs, entries, "оп", None, None,
                       ops_static=base_ops * rep)


def bench_mos(quick, limits, rows, budget=None):
    runs = cl.RUNS_QUICK if quick else cl.RUNS_FULL
    roms = {}
    for tag in ("verify", "native", "native_quick"):
        roms[tag] = cl.OUT / f"rom_{tag}.rom"
        cl.sh([sys.executable, HERE / "gen6502.py", *cl.MOS_ROMS[tag],
               "-o", roms[tag]])
    heavy = roms["native_quick" if quick else "native"]
    print("\n=== mos6502 (нагрузка — ROM со stdin, метрика — нс/шаг) ===")

    eat_srcs = [cl.ROOT / p for p in cl.MOS_EAT_SRC]
    bin_ = cl.OUT / "ih_mos"
    cl.sh(cl.eatc("build", cl.RT, *eat_srcs, "-o", bin_))
    ll = bin_.with_suffix(".ll")
    assert ll.exists(), f"{ll}: build не оставил .ll"

    base = [("build (llvmlite)", [bin_], bin_)]
    bn = cl.OUT / "ih_mos_nohints"
    llvmlite_bin(ll, bn)
    base.append(("llvmlite без хинтов", [bn], bn))
    bc = cl.OUT / "ih_mos_clang"
    bk.clang_bin(ll, bc)
    base.append((".ll → clang -O2", [bc], bc))
    src_c = HERE / "c" / "mos6502.c"
    bin_c = cl.OUT / "ih_mos_c"
    cl.sh(["clang", "-O2", src_c, "-o", bin_c])
    base.append(("C -O2", [bin_c], bin_c))
    entries = variant_entries(ll, "ih_mos", limits, base,
                              budget)
    bk.measure_entries(rows, "mos6502", runs, entries, "шаг",
                       roms["verify"], heavy)


def main():
    argv = sys.argv[1:]
    quick = "--quick" in argv
    only = None
    if "--only" in argv:
        only = set(argv[argv.index("--only") + 1].split(","))
    budget = None
    if "--budget" in argv:
        budget = int(argv[argv.index("--budget") + 1])
    limits = LIMITS
    if "--limits" in argv:
        limits = [int(x)
                  for x in argv[argv.index("--limits") + 1].split(",")]
    json_path = cl.OUT / "inline_hints.json"
    if "--json" in argv:
        json_path = Path(argv[argv.index("--json") + 1])

    cl.OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.perf_counter()
    for key in BENCH_DEFS:
        if only and key not in only:
            continue
        bench_micro(key, quick, limits, rows, budget)
    if not only or "mos6502" in only:
        bench_mos(quick, limits, rows, budget)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"\nJSON: {json_path}")
    print(f"общее время: {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
