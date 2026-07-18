"""Кросс-языковое сравнение производительности EATLang с C, Rust, Go и
Python (docs/plans/CROSSLANG_BENCH_PLAN.md).

Методика:
- порты повторяют tests/bench/programs/*.eat 1:1 (те же типы, границы,
  свёртки); маркер `REPEAT = 1` подменяется раннером, как в bench.py;
- сверочный прогон: все языки на REPEAT=2 — stdout обязан совпасть
  байт-в-байт с EATLang-бинарником (иначе замер не засчитывается);
- замер: медиана из N прогонов под /usr/bin/time -l — стена,
  instructions retired, cycles elapsed (→ IPC, инструкций/оп),
  peak memory footprint;
- оси проверок: EATLang канон-IR (все trap'ы, `eatc ir` + clang) против
  штатного `eatc build` (доказанное снято верификатором); C -O2 против
  UBSan; Rust safe против unchecked-варианта файла; Go против
  -gcflags=-B;
- скорость компиляции и размер бинарника (после strip) — по разу.

Запуск: make bench_crosslang | uv run python tests/bench/crosslang/run.py
        [--quick] [--only arith,sort] [--json PATH]
Артефакты — в build/bench/crosslang/.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "build" / "bench" / "crosslang"
RT = ROOT / "selfhost" / "Rt.eat"
RUNTIME_C = ROOT / "src" / "eatc" / "runtime.c"
PROGRAMS = ROOT / "tests" / "bench" / "programs"

ENV = {**os.environ, "PYTHONPATH": "src"}

CLANG = shutil.which("clang")
RUSTC = shutil.which("rustc") or str(Path.home() / ".cargo/bin/rustc")
GO = shutil.which("go")
SELFIROPT = ROOT / "build" / "SelfIrOpt"     # самохост-эмиссия оси -O

# имя → (файл EATLang, базовых операций на REPEAT=1, REPEAT нативный,
#        REPEAT quick, REPEAT python, модули lib/ между Rt и программой)
BENCHES = {
    "arith": ("ArithBench", 1_000_000, 1024, 64, 8, []),
    "sort": ("SortBench", 250_000, 2048, 64, 8, []),
    "branch": ("BranchBench", 500_000, 2048, 64, 8, []),
    "bank": ("BankBench", 200_000, 2048, 64, 8, []),
    "strcmp": ("StrCmpBench", 20_000, 128, 16, 4, []),
    "u64": ("U64Bench", 200_000, 4096, 128, 8, []),
    # 128-битная арифметика lib/core/U128.eat (U128_PLAN, замер этапа 4):
    # "driver" вместо списка модулей — у U128 import-шапка, cat-режим
    # невозможен, поток собирает драйвер (eatc --lib . / stream)
    "u128": ("U128Bench", 20_000, 1024, 64, 8, "driver"),
    "u128div": ("U128DivBench", 4_400, 2048, 128, 32, "driver"),
    # HTTP-парсер lib/http/Http.eat (HTTP_PLAN): 2 000 запросов на REPEAT=1
    # (4 профиля × 500) — request-line, заголовки, роутер, keep-alive;
    # драйвер: HttpBench → lib/http/Http.eat → lib/fmt/Fmt.eat
    "http": ("HttpBench", 2_500, 256, 32, 4, "driver"),
    # ядро RESTful TODO-list lib/-free (TODO_REST_PLAN): пул из 64 слотов
    # под потоком create/toggle/serialize/remove — 2 048 операций на
    # REPEAT=1; store+сериализация (разбор запросов мерит `http`)
    "todo": ("TodoBench", 2_048, 256, 32, 4, []),
}

REP_VERIFY = 2          # сверочный REPEAT: одинаковый у всех языков
RUNS_FULL, RUNS_QUICK = 5, 3

# Макробенч mos6502: нагрузка — ROM со stdin (шагов ~ top*outer*mid*
# 256*7), метрика — нс/шаг; steps= парсится из отчёта эмулятора.
# (генератор, ROM сверки, ROM python, ROM native, ROM native quick)
MOS_EAT_SRC = ["lib/fmt/Hex.eat", "examples/mos6502/Cpu6502.eat",
               "examples/mos6502/Tests.eat", "examples/mos6502/Main.eat"]
MOS_ROMS = {
    "verify": ["--top", "1", "--outer", "1", "--middle", "16"],
    "py": ["--top", "1", "--outer", "8", "--middle", "255"],
    "native": ["--top", "64", "--outer", "32", "--middle", "255"],
    "native_quick": ["--top", "4", "--outer", "32", "--middle", "255"],
}

# маркеры константы REPEAT в исходниках (подменяются копией в OUT)
MARKERS = {
    "eat": "constexpr REPEAT: u32 = 1",
    "c": "static const uint32_t REPEAT = 1;",
    "rust": "const REPEAT: u32 = 1;",
    "go": "const REPEAT uint32 = 1",
    "py": "REPEAT = 1",
}


def scaled(lang: str, src: Path, rep: int) -> Path:
    """Копия исходника с REPEAT=rep (методика bench.py)."""
    text = src.read_text(encoding="utf-8")
    marker = MARKERS[lang]
    assert marker in text, f"{src.name}: нет маркера {marker!r}"
    dst = OUT / f"{src.stem}_{lang}_r{rep}{src.suffix}"
    dst.write_text(
        text.replace(marker, marker.replace("= 1", f"= {rep}")),
        encoding="utf-8")
    return dst


def sh(cmd, *, stdin_path=None, capture=False, check=True):
    fin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
    p = subprocess.run(
        [str(c) for c in cmd], stdin=fin,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE, cwd=ROOT, env=ENV)
    if stdin_path:
        fin.close()
    if check and p.returncode != 0:
        raise RuntimeError(
            f"{' '.join(str(c) for c in cmd)}: rc={p.returncode}\n"
            f"{p.stderr.decode(errors='replace')[-800:]}")
    return p


def eatc(*args):
    return [sys.executable, "-m", "eatc", *args]


class Measure:
    """Один прогон под /usr/bin/time -l: стена + счётчики процессора."""

    def __init__(self, wall, instructions, cycles, peak_rss, out):
        self.wall, self.out = wall, out
        self.instructions, self.cycles = instructions, cycles
        self.peak_rss = peak_rss


def run_measured(cmd, runs: int, stdin_path=None) -> Measure:
    """Стена — медиана runs прямых прогонов (perf_counter, тонкое
    разрешение); счётчики процессора и RSS — один прогон под
    /usr/bin/time -l (его стена квантуется по 10 мс и не годится)."""
    cmd = [str(c) for c in cmd]

    def spawn(full_cmd, capture):
        fin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
        p = subprocess.run(
            full_cmd, stdin=fin,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE, cwd=ROOT, env=ENV)
        if stdin_path:
            fin.close()
        return p

    walls = []
    for _ in range(runs + 1):        # +1 — прогрев, не учитывается
        t0 = time.perf_counter()
        p = spawn(cmd, capture=False)
        walls.append(time.perf_counter() - t0)
        if p.returncode != 0:
            raise RuntimeError(
                f"{cmd}: rc={p.returncode} "
                f"{p.stderr.decode(errors='replace')[-400:]}")
    walls = sorted(walls[1:])
    wall = walls[len(walls) // 2]

    p = spawn(["/usr/bin/time", "-l"] + cmd, capture=True)
    err = p.stderr.decode(errors="replace")

    def grab(pat):
        m = re.search(rf"(\d+)\s+{pat}", err)
        return int(m.group(1)) if m else 0

    return Measure(wall, grab("instructions retired"),
                   grab("cycles elapsed"),
                   grab("peak memory footprint"), p.stdout)


def timed_build(cmd) -> float:
    t0 = time.perf_counter()
    sh(cmd)
    return time.perf_counter() - t0


def stripped_size(binary: Path) -> int:
    cp = OUT / (binary.name + ".stripped")
    shutil.copy2(binary, cp)
    subprocess.run(["strip", "-x", str(cp)], cwd=ROOT,
                   capture_output=True)
    return cp.stat().st_size


# ---------------------------------------------------------------------------
# Варианты: label → build(name, rep) -> (run_cmd, bin_path|None, build_secs)

def build_eat(name, stem, libs, rep):
    """Штатный eatc build: доказанные проверки сняты верификатором."""
    src = scaled("eat", PROGRAMS / f"{name}.eat", rep)
    bin_ = OUT / f"{stem}_eat_r{rep}"
    if libs == "driver":
        secs = timed_build(eatc("build", "--lib", ROOT, src, "-o", bin_))
    else:
        secs = timed_build(eatc("build", RT, *libs, src, "-o", bin_))
    return [bin_], bin_, secs


def eat_cat(name, stem, libs, rep):
    """Конкатенация Rt + lib + программа — вход одно-файловых команд.
    В драйверном режиме ("driver") поток с #module-маркерами собирает
    eatc stream — вручную склеенный cat не разрешил бы import-шапки."""
    src = scaled("eat", PROGRAMS / f"{name}.eat", rep)
    cat = OUT / f"{stem}_eatcat_r{rep}.eat"
    if libs == "driver":
        p = sh(eatc("stream", "--lib", ROOT, src), capture=True)
        cat.write_bytes(p.stdout)
        return cat
    parts = [RT.read_text(encoding="utf-8")]
    parts += [(ROOT / lib).read_text(encoding="utf-8") for lib in libs]
    parts.append(src.read_text(encoding="utf-8"))
    cat.write_text("\n".join(parts), encoding="utf-8")
    return cat


def build_eat_traps(name, stem, libs, rep):
    """Канонический IR (`eatc ir`, все trap'ы) + clang -O2 + runtime.c —
    точка «все проверки в рантайме» оси налога на безопасность."""
    cat = eat_cat(name, stem, libs, rep)
    ll = OUT / f"{stem}_eatcat_r{rep}.ll"
    bin_ = OUT / f"{stem}_eattraps_r{rep}"
    t0 = time.perf_counter()
    p = sh(eatc("ir", cat), capture=True)
    ll.write_bytes(p.stdout)
    sh([CLANG, "-O2", ll, RUNTIME_C, "-o", bin_])
    return [bin_], bin_, time.perf_counter() - t0


def selfiropt_ll(cat: Path, ll: Path):
    """SelfIrOpt (самохост, ось -O: fold + элизия) < cat > ll.
    Ошибка самохоста уходит в stdout с rc 0 (F2) — ловим по контенту."""
    p = sh([SELFIROPT], stdin_path=cat, capture=True)
    if p.stdout.startswith(b"err") or not p.stdout:
        raise RuntimeError(f"SelfIrOpt: {p.stdout[:200]!r}")
    ll.write_bytes(p.stdout)


def build_eat_self(name, stem, libs, rep):
    """Селфхост-цепочка: SelfIrOpt (`ir -O`) + clang -O2 + runtime.c —
    компилятор, написанный на самом EATLang."""
    if not SELFIROPT.exists():
        return None
    cat = eat_cat(name, stem, libs, rep)
    ll = OUT / f"{stem}_eatself_r{rep}.ll"
    bin_ = OUT / f"{stem}_eatself_r{rep}"
    t0 = time.perf_counter()
    selfiropt_ll(cat, ll)
    sh([CLANG, "-O2", ll, RUNTIME_C, "-o", bin_])
    return [bin_], bin_, time.perf_counter() - t0


def build_c(stem, rep, sanitize=False):
    src = scaled("c", HERE / "c" / f"{stem}.c", rep)
    tag = "csan" if sanitize else "c"
    bin_ = OUT / f"{stem}_{tag}_r{rep}"
    flags = ["-O2"]
    if sanitize:
        flags += ["-fsanitize=undefined,bounds", "-fno-sanitize-recover=all"]
    secs = timed_build([CLANG, *flags, src, "-o", bin_])
    return [bin_], bin_, secs


def build_rust(stem, rep, unchecked=False):
    name = f"{stem}_unchecked" if unchecked else stem
    path = HERE / "rust" / f"{name}.rs"
    if not path.exists():
        return None            # unchecked-варианта нет (нет массивов)
    src = scaled("rust", path, rep)
    bin_ = OUT / f"{stem}_rust{'u' if unchecked else ''}_r{rep}"
    secs = timed_build([RUSTC, "-C", "opt-level=2", src, "-o", bin_])
    return [bin_], bin_, secs


def build_go(stem, rep, nobounds=False):
    src = scaled("go", HERE / "go" / f"{stem}.go", rep)
    tag = "gonb" if nobounds else "go"
    bin_ = OUT / f"{stem}_{tag}_r{rep}"
    cmd = [GO, "build"]
    if nobounds:
        cmd += ["-gcflags=-B"]
    secs = timed_build(cmd + ["-o", bin_, src])
    return [bin_], bin_, secs


def build_py(stem, rep):
    src = scaled("py", HERE / "py" / f"{stem}.py", rep)
    return [sys.executable, src], None, 0.0


def variants(name, stem, libs):
    """Порядок строк таблицы. None от builder'а — вариант недоступен."""
    return [
        ("EATLang build",
         lambda r: build_eat(name, stem, libs, r), "native"),
        ("EATLang все-trap",
         lambda r: build_eat_traps(name, stem, libs, r), "native"),
        ("EATLang selfhost -O",
         lambda r: build_eat_self(name, stem, libs, r), "native"),
        ("C -O2", lambda r: build_c(stem, r), "native"),
        ("C -O2 UBSan",
         lambda r: build_c(stem, r, sanitize=True), "native"),
        ("Rust -C2 safe", lambda r: build_rust(stem, r), "native"),
        ("Rust -C2 unchecked",
         lambda r: build_rust(stem, r, unchecked=True), "native"),
        ("Go", lambda r: build_go(stem, r), "native"),
        ("Go -gcflags=-B",
         lambda r: build_go(stem, r, nobounds=True), "native"),
        ("Python 3.11", lambda r: build_py(stem, r), "py"),
    ]


# ---------------------------------------------------------------------------

def fmt_s(s):
    return f"{s:.3f}s" if s >= 0.1 else f"{s * 1000:.1f}ms"


def fmt_n(n):
    for div, suf in ((1e9, "G"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            return f"{n / div:.2f}{suf}"
    return f"{n:.2f}"


def table(headers, rows):
    widths = [max(len(str(r[i])) for r in [headers] + rows)
              for i in range(len(headers))]

    def line(cells):
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))
    print(line(headers))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line(r))


def bench_one(key, quick, results):
    name, base_ops, rep_full, rep_quick, rep_py, libs = BENCHES[key]
    rep_native = rep_quick if quick else rep_full
    runs = RUNS_QUICK if quick else RUNS_FULL
    print(f"\n=== {key} ({name}: {base_ops / 1e6:.2f}M оп на REPEAT=1, "
          f"native x{rep_native}, python x{rep_py}) ===")

    # 1. Сверка: все варианты на REPEAT=REP_VERIFY, stdout байт-в-байт
    reference = None
    checked = []
    for label, builder, klass in variants(name, key, libs):
        built = builder(REP_VERIFY)
        if built is None:
            continue
        cmd = built[0]
        out = sh(cmd, capture=True).stdout
        if reference is None:
            reference = out
        if out != reference:
            print(f"  СВЕРКА ПРОВАЛЕНА {label}: {out!r} != {reference!r}")
            results["fails"].append(f"{key}: {label}")
            continue
        checked.append((label, builder, klass))
    print(f"  сверка REPEAT={REP_VERIFY}: {reference!r} — "
          f"{len(checked)} вариантов сходятся")

    # старт процесса: python — накладной расход интерпретатора
    py_start = run_measured([sys.executable, "-c", "pass"], runs).wall

    # 2. Замер
    rows = []
    for label, builder, klass in checked:
        rep = rep_py if klass == "py" else rep_native
        cmd, bin_, build_secs = builder(rep)
        m = run_measured(cmd, runs)
        ops = base_ops * rep
        wall = m.wall - (py_start if klass == "py" else 0.0)
        wall = max(wall, 1e-9)
        row = {
            "bench": key, "label": label, "ops": ops,
            "wall": m.wall, "ns_op": wall / ops * 1e9,
            "instructions": m.instructions, "cycles": m.cycles,
            "ipc": m.instructions / m.cycles if m.cycles else 0.0,
            "instr_op": m.instructions / ops,
            "peak_rss": m.peak_rss,
            "build_secs": build_secs,
            "bin_size": stripped_size(bin_) if bin_ else 0,
        }
        results["rows"].append(row)
        rows.append([
            label, f"{fmt_n(ops)} оп", fmt_s(m.wall),
            f"{row['ns_op']:.3f}", f"{row['instr_op']:.2f}",
            f"{row['ipc']:.2f}", f"{m.peak_rss / 2**20:.1f}M",
            fmt_s(build_secs) if build_secs else "—",
            f"{row['bin_size'] // 1024}K" if row["bin_size"] else "—",
        ])
    table(["вариант", "работа", "стена", "нс/оп", "инстр/оп",
           "IPC", "RSS", "сборка", "бинарник"], rows)


def mos_builders():
    """Варианты макробенча: (label, builder() -> (cmd, bin, secs), класс).
    Порт отсутствует на диске — вариант пропускается со строкой-notice."""
    eat_srcs = [ROOT / p for p in MOS_EAT_SRC]

    def b_eat():
        bin_ = OUT / "mos_eat"
        secs = timed_build(eatc("build", RT, *eat_srcs, "-o", bin_))
        return [bin_], bin_, secs

    def mos_cat():
        cat = OUT / "mos_cat.eat"
        cat.write_text("\n".join(
            p.read_text(encoding="utf-8") for p in [RT] + eat_srcs),
            encoding="utf-8")
        return cat

    def b_eat_traps():
        cat = mos_cat()
        ll, bin_ = OUT / "mos_cat.ll", OUT / "mos_eattraps"
        t0 = time.perf_counter()
        ll.write_bytes(sh(eatc("ir", cat), capture=True).stdout)
        sh([CLANG, "-O2", ll, RUNTIME_C, "-o", bin_])
        return [bin_], bin_, time.perf_counter() - t0

    def b_eat_self():
        if not SELFIROPT.exists():
            return None
        cat = mos_cat()
        ll, bin_ = OUT / "mos_self.ll", OUT / "mos_eatself"
        t0 = time.perf_counter()
        selfiropt_ll(cat, ll)
        sh([CLANG, "-O2", ll, RUNTIME_C, "-o", bin_])
        return [bin_], bin_, time.perf_counter() - t0

    def b_c(sanitize=False):
        src = HERE / "c" / "mos6502.c"
        bin_ = OUT / ("mos_csan" if sanitize else "mos_c")
        flags = ["-O2"]
        if sanitize:
            flags += ["-fsanitize=undefined,bounds",
                      "-fno-sanitize-recover=all"]
        secs = timed_build([CLANG, *flags, src, "-o", bin_])
        return [bin_], bin_, secs

    def b_rust():
        src = HERE / "rust" / "mos6502.rs"
        bin_ = OUT / "mos_rust"
        secs = timed_build([RUSTC, "-C", "opt-level=2", src, "-o", bin_])
        return [bin_], bin_, secs

    def b_go():
        src = HERE / "go" / "mos6502.go"
        bin_ = OUT / "mos_go"
        secs = timed_build([GO, "build", "-o", bin_, src])
        return [bin_], bin_, secs

    def b_py():
        return [sys.executable, HERE / "py" / "mos6502.py"], None, 0.0

    return [
        ("EATLang build", b_eat, "native", None),
        ("EATLang все-trap", b_eat_traps, "native", None),
        ("EATLang selfhost -O", b_eat_self, "native", None),
        ("C -O2", b_c, "native", HERE / "c" / "mos6502.c"),
        ("C -O2 UBSan", lambda: b_c(True), "native",
         HERE / "c" / "mos6502.c"),
        ("Rust -C2 safe", b_rust, "native", HERE / "rust" / "mos6502.rs"),
        ("Go", b_go, "native", HERE / "go" / "mos6502.go"),
        ("Python 3.11", b_py, "py", HERE / "py" / "mos6502.py"),
    ]


def bench_mos(quick, results):
    """Макробенч: эмулятор mos6502, нагрузка — ROM со stdin."""
    runs = RUNS_QUICK if quick else RUNS_FULL
    roms = {}
    for tag, args in MOS_ROMS.items():
        roms[tag] = OUT / f"rom_{tag}.rom"
        sh([sys.executable, HERE / "gen6502.py", *args,
            "-o", roms[tag]])
    heavy = roms["native_quick" if quick else "native"]
    mul = ROOT / "examples" / "mos6502" / "mul13x11.rom"
    print("\n=== mos6502 (эмулятор examples/mos6502; "
          "нагрузка — ROM со stdin, метрика — нс/шаг) ===")

    # сборка + сверка на двух лёгких ROM: отчёты байт-в-байт
    built, reference = [], {}
    for label, builder, klass, src in mos_builders():
        if src is not None and not src.exists():
            print(f"  {label}: порт {src.name} ещё не создан — пропуск")
            continue
        made = builder()
        if made is None:
            print(f"  {label}: вариант недоступен — пропуск")
            continue
        cmd, bin_, secs = made
        ok = True
        for rom in (mul, roms["verify"]):
            out = sh(cmd, stdin_path=rom, capture=True).stdout
            if rom not in reference:
                reference[rom] = out
            if out != reference[rom]:
                print(f"  СВЕРКА ПРОВАЛЕНА {label} на {rom.name}: "
                      f"{out!r} != {reference[rom]!r}")
                results["fails"].append(f"mos6502: {label} ({rom.name})")
                ok = False
        if ok:
            built.append((label, cmd, bin_, secs, klass))
    print(f"  сверка (mul13x11 + rom_verify): {len(built)} "
          f"вариантов сходятся")

    py_start = run_measured([sys.executable, "-c", "pass"], runs).wall
    rows = []
    for label, cmd, bin_, build_secs, klass in built:
        rom = roms["py"] if klass == "py" else heavy
        m = run_measured(cmd, runs, stdin_path=rom)
        mm = re.search(rb"steps=(\d+)", m.out)
        steps = int(mm.group(1)) if mm else 0
        wall = max(m.wall - (py_start if klass == "py" else 0.0), 1e-9)
        row = {
            "bench": "mos6502", "label": label, "ops": steps,
            "wall": m.wall, "ns_op": wall / steps * 1e9,
            "instructions": m.instructions, "cycles": m.cycles,
            "ipc": m.instructions / m.cycles if m.cycles else 0.0,
            "instr_op": m.instructions / steps,
            "peak_rss": m.peak_rss, "build_secs": build_secs,
            "bin_size": stripped_size(bin_) if bin_ else 0,
        }
        results["rows"].append(row)
        rows.append([
            label, f"{fmt_n(steps)} шаг", fmt_s(m.wall),
            f"{row['ns_op']:.3f}", f"{row['instr_op']:.2f}",
            f"{row['ipc']:.2f}", f"{m.peak_rss / 2**20:.1f}M",
            fmt_s(build_secs) if build_secs else "—",
            f"{row['bin_size'] // 1024}K" if row["bin_size"] else "—",
        ])
    table(["вариант", "работа", "стена", "нс/шаг", "инстр/шаг",
           "IPC", "RSS", "сборка", "бинарник"], rows)


def main():
    argv = sys.argv[1:]
    quick = "--quick" in argv
    only = None
    if "--only" in argv:
        only = set(argv[argv.index("--only") + 1].split(","))
    json_path = OUT / "results.json"
    if "--json" in argv:
        json_path = Path(argv[argv.index("--json") + 1])

    OUT.mkdir(parents=True, exist_ok=True)
    missing = [n for n, p in (("clang", CLANG), ("go", GO)) if not p]
    if not Path(RUSTC).exists():
        missing.append("rustc")
    if missing:
        print(f"нет тулчейнов: {', '.join(missing)} — установите и повторите")
        return 2

    results = {"rows": [], "fails": []}
    t0 = time.perf_counter()
    for key in BENCHES:
        if only and key not in only:
            continue
        bench_one(key, quick, results)
    if not only or "mos6502" in only:
        bench_mos(quick, results)
    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nJSON: {json_path}")
    print(f"общее время: {time.perf_counter() - t0:.1f}s")
    if results["fails"]:
        print(f"ПРОВАЛЫ СВЕРКИ: {results['fails']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
