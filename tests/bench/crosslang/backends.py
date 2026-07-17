"""Эксперимент §7.2 OPTIMIZATIONS_PLAN: конвейер сборки — llvmlite
против clang на байт-идентичном .ll.

Вход обоих бэкендов — один файл: неоптимизированный .ll с элизией
(после 7.1 — без assume), который `eatc build` пишет рядом с
бинарником. Варианты:

- build (llvmlite)  — штатный путь: llvmlite NewPM speed_level=2 +
  machine opt=2 emit_object + clang-линк .o (LLVM 22.1 из llvmlite);
- .ll → clang -O2   — тот же .ll целиком через clang (мид-энд +
  кодоген Apple clang) + runtime.c, флаги линковки те же;
- .ll → clang -flto — путь `build --release` (clang -O2 -flto);
- декомпозиция (--decompose, branch и mos6502):
  llvmlite-мид → clang -O2      (чей мид-энд виноват);
  clang-мид → llvmlite-кодоген  (чей кодоген виноват).

Методика замера — run.py (медиана 5 прямых прогонов + счётчики
/usr/bin/time -l). Запуск дважды подряд — оценка дрейфа ±5 %.

Запуск: uv run python tests/bench/crosslang/backends.py
        [--quick] [--only branch,mos6502] [--decompose] [--json PATH]
"""

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run as cl  # noqa: E402  — контур crosslang: методика и сборки

if sys.platform == "darwin":
    STACK = ["-Wl,-stack_size,0x10000000"]
else:
    STACK = ["-Wl,-z,stacksize=268435456"]

MICRO = ["arith", "sort", "branch", "u64"]   # состав этапа 7.2


# ---------------------------------------------------------------------------
# llvmlite-полуфабрикаты (зеркалят compile_binary, канон не трогают)

def _machine():
    import llvmlite.binding as llvm
    try:
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()
    except RuntimeError:
        pass
    return llvm, llvm.Target.from_default_triple().create_target_machine(
        opt=2)


def llvmlite_mid(src_ll: Path, dst_ll: Path):
    """Мид-энд llvmlite (NewPM speed_level=2) без кодогена: .ll → .ll.

    LLVM 22 (llvmlite) печатает атрибуты, которых Apple clang 21 не
    знает, — вычищаем: это подсказки оптимизатору, не семантика."""
    llvm, machine = _machine()
    ref = llvm.parse_assembly(src_ll.read_text(encoding="utf-8"))
    ref.verify()
    pto = llvm.create_pipeline_tuning_options(speed_level=2)
    pb = llvm.create_pass_builder(machine, pto)
    pb.getModulePassManager().run(ref, pb)
    text = str(ref)
    for attr in ("nocreateundeforpoison ", "captures(none) ",
                 "dead_on_return "):
        text = text.replace(attr, "")
    # llvm.lifetime.* в LLVM 22 сменили сигнатуру — clang 21 их не
    # съест; маркеры стековой раскраски, семантики не несут — долой
    text = "\n".join(l for l in text.splitlines()
                     if "llvm.lifetime" not in l)
    dst_ll.write_text(text, encoding="utf-8")


def llvmlite_codegen(src_ll: Path, bin_: Path):
    """Кодоген llvmlite (machine opt=2, БЕЗ пассов) + clang-линк."""
    llvm, machine = _machine()
    ref = llvm.parse_assembly(src_ll.read_text(encoding="utf-8"))
    ref.verify()
    obj = bin_.with_suffix(".o")
    obj.write_bytes(machine.emit_object(ref))
    cl.sh(["clang", "-O2", obj, cl.RUNTIME_C, "-o", bin_] + STACK)
    obj.unlink()


def clang_bin(src_ll: Path, bin_: Path, lto=False):
    """clang по текстовому .ll + runtime.c; флаги линковки как у build."""
    flags = ["-O2", "-flto"] if lto else ["-O2"]
    cl.sh(["clang", *flags, src_ll, cl.RUNTIME_C, "-o", bin_] + STACK)


def clang_mid(src_ll: Path, dst_ll: Path):
    """Мид-энд clang (-O2 -S -emit-llvm) без кодогена: .ll → .ll."""
    cl.sh(["clang", "-O2", "-S", "-emit-llvm", src_ll, "-o", dst_ll])


# ---------------------------------------------------------------------------

def variants(ll: Path, stem: str, decompose: bool):
    """label → builder(bin_path): бинарники из ОДНОГО .ll."""
    out = [
        (".ll → clang -O2", lambda b: clang_bin(ll, b)),
        (".ll → clang -flto (release)",
         lambda b: clang_bin(ll, b, lto=True)),
    ]
    if decompose:
        def mid_llvmlite_clang(b):
            mid = cl.OUT / f"{stem}_midllvmlite.ll"
            llvmlite_mid(ll, mid)
            clang_bin(mid, b)

        def mid_clang_llvmlite(b):
            mid = cl.OUT / f"{stem}_midclang.ll"
            clang_mid(ll, mid)
            llvmlite_codegen(mid, b)

        out += [
            ("llvmlite-мид → clang -O2", mid_llvmlite_clang),
            ("clang-мид → llvmlite-кодоген", mid_clang_llvmlite),
        ]
    return out


def measure_entries(rows, bench, runs, entries, op_unit, verify_stdin,
                    measure_stdin, ops_static=None):
    """Сверка stdout всех entries между собой, затем замер каждого.

    entries: (label, cmd, bin_path); ops — либо ops_static, либо
    steps= из отчёта эмулятора (op_unit решает подпись колонки)."""
    ref_out, checked = None, []
    for label, cmd, bin_ in entries:
        out = cl.sh(cmd, stdin_path=verify_stdin, capture=True).stdout
        if ref_out is None:
            ref_out = out
        if out != ref_out:
            print(f"  СВЕРКА ПРОВАЛЕНА {label}")
            continue
        checked.append((label, cmd, bin_))
    print(f"  сверка: {len(checked)} вариантов сходятся")

    printed = []
    for label, cmd, bin_ in checked:
        m = cl.run_measured(cmd, runs, stdin_path=measure_stdin)
        if ops_static is None:
            mm = re.search(rb"steps=(\d+)", m.out)
            ops = int(mm.group(1)) if mm else 1
        else:
            ops = ops_static
        row = {
            "bench": bench, "label": label, "ops": ops, "wall": m.wall,
            "ns_op": m.wall / ops * 1e9,
            "instructions": m.instructions, "cycles": m.cycles,
            "ipc": m.instructions / m.cycles if m.cycles else 0.0,
            "instr_op": m.instructions / ops,
            "bin_size": cl.stripped_size(bin_),
        }
        rows.append(row)
        printed.append([
            label, cl.fmt_s(m.wall), f"{row['ns_op']:.3f}",
            f"{row['instr_op']:.2f}", f"{row['ipc']:.2f}",
            f"{row['bin_size'] // 1024}K",
        ])
    cl.table(["вариант", "стена", f"нс/{op_unit}", f"инстр/{op_unit}",
              "IPC", "бинарник"], printed)


def bench_micro(key, quick, decompose, rows):
    name, base_ops, rep_full, rep_quick, _rep_py, libs = cl.BENCHES[key]
    rep = rep_quick if quick else rep_full
    runs = cl.RUNS_QUICK if quick else cl.RUNS_FULL
    print(f"\n=== {key} ({name}, REPEAT={rep}) ===")

    # штатный build: бинарник + его же .ll (вход всех остальных)
    cmd, bin_, _secs = cl.build_eat(name, key, libs, rep)
    ll = bin_.with_suffix(".ll")
    assert ll.exists(), f"{ll}: build не оставил .ll"

    entries = [("build (llvmlite)", cmd, bin_)]
    for label, builder in variants(ll, key, decompose and key == "branch"):
        b = cl.OUT / (key + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", label))
        builder(b)
        entries.append((label, [b], b))
    measure_entries(rows, key, runs, entries, "оп", None, None,
                    ops_static=base_ops * rep)


def bench_mos(quick, decompose, rows):
    runs = cl.RUNS_QUICK if quick else cl.RUNS_FULL
    roms = {}
    for tag in ("verify", "native", "native_quick"):
        roms[tag] = cl.OUT / f"rom_{tag}.rom"
        cl.sh([sys.executable, HERE / "gen6502.py", *cl.MOS_ROMS[tag],
               "-o", roms[tag]])
    heavy = roms["native_quick" if quick else "native"]
    print("\n=== mos6502 (нагрузка — ROM со stdin, метрика — нс/шаг) ===")

    eat_srcs = [cl.ROOT / p for p in cl.MOS_EAT_SRC]
    bin_ = cl.OUT / "mosb_eat"
    cl.sh(cl.eatc("build", cl.RT, *eat_srcs, "-o", bin_))
    ll = bin_.with_suffix(".ll")
    assert ll.exists(), f"{ll}: build не оставил .ll"

    entries = [("build (llvmlite)", [bin_], bin_)]
    for label, builder in variants(ll, "mosb", decompose):
        b = cl.OUT / ("mosb_" + re.sub(r"[^a-zA-Z0-9]+", "_", label))
        builder(b)
        entries.append((label, [b], b))
    measure_entries(rows, "mos6502", runs, entries, "шаг",
                    roms["verify"], heavy)


def main():
    argv = sys.argv[1:]
    quick = "--quick" in argv
    decompose = "--decompose" in argv
    only = None
    if "--only" in argv:
        only = set(argv[argv.index("--only") + 1].split(","))
    json_path = cl.OUT / "backends.json"
    if "--json" in argv:
        json_path = Path(argv[argv.index("--json") + 1])

    cl.OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    t0 = time.perf_counter()
    for key in MICRO:
        if only and key not in only:
            continue
        bench_micro(key, quick, decompose, rows)
    if not only or "mos6502" in only:
        bench_mos(quick, decompose, rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"\nJSON: {json_path}")
    print(f"общее время: {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
