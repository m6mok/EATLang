"""Нагрузочное тестирование EATLang (make bench / make bench_quick).

Секции:
  pipeline — скорость стадий eatc (lex/parse/typed/ir) на синтетических
             модулях ступенчатых размеров + многомодульный фронтенд;
  runtime  — бенчмарк-программы tests/bench/programs/: интерпретатор
             против нативного бинарника, дифференциальная сверка вывода;
  stress   — входы на лимитах SPEC.md §6 и за ними: принять или быстро
             упасть с внятной ошибкой, без зависаний;
  selfhost — self-hosted лексер/парсер (нативные бинарники) против
             Python-эталона на большом входе, байт-в-байт сверка дампов;
  compiler — постоянная метрика скорости самого компилятора: фазовые
             self-hosted бинарники (SelfLex..SelfIr) компилируют
             конкатенацию собственных модулей (вход verify_bootstrap),
             время и дампы сверяются с Python-эталоном;
  size     — размеры бинарников и данных (метрика для МК/флеша, трек 2):
             файл, секции __text/__const, строковые глобалы канона и
             доля trap-строк в них, размер канонического .ll.

Запуск из корня репозитория:
  uv run python tests/bench/bench.py [--quick] [--only pipeline,stress]

Артефакты (входы, бинарники, дампы) — в build/bench/.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
RT = ROOT / "selfhost" / "Rt.eat"
PROGRAMS = Path(__file__).resolve().parent / "programs"
OUT = ROOT / "build" / "bench"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(SRC))

import genprog  # noqa: E402
from eatc.lexer import Lexer  # noqa: E402

ENV = {**os.environ, "PYTHONPATH": str(SRC)}
STRESS_TIMEOUT = 60  # секунд: дольше — считаем зависанием

# Размеры пайплайна: функций в синтетическом модуле (~757 токенов каждая)
SIZES_FULL = [("S", 16), ("M", 64), ("L", 160)]
SIZES_QUICK = [("S", 16), ("M", 64)]
XL_FUNCS = 992          # многомодульная программа (предел языка — 1024)
XL_FUNCS_PER_FILE = 144

# Базовый объём работы бенчмарк-программ (операций на REPEAT=1)
# и множитель REPEAT для нативного замера.
RUNTIME_PROGRAMS = [
    # (файл, базовых операций, REPEAT full, REPEAT quick)
    ("ArithBench", 1_000_000, 256, 32),
    ("CallBench", 500_000, 256, 32),
    ("ArrayBench", 520_192, 256, 32),
    ("StructBench", 500_000, 256, 32),
    ("AggBench", 200_000, 160, 20),
    ("NumParseBench", 200_000, 64, 8),
    ("StrBench", 1_280_000, 8, 2),
    # расширение 2026-07-14: слои плана оптимизаций (COMPTIME_PLAN §0,
    # TRACKS 3/4) — каждая программа метрика своего слоя
    ("U64Bench", 200_000, 1024, 128),
    ("I64Bench", 200_000, 1024, 128),
    ("BitsBench", 200_000, 1024, 128),
    ("TrapBench", 200_000, 512, 64),
    ("MatchBench", 200_000, 2048, 256),
    ("RetBench", 100_000, 1024, 128),
    ("CopyBench", 200_000, 1024, 128),
    ("IoBench", 1_400_000, 256, 32),
    # вторая волна 2026-07-14: ввод/строки/пулы/ветвления/машины
    ("StrCmpBench", 20_000, 64, 8),
    ("BankBench", 200_000, 512, 64),
    ("SortBench", 250_000, 512, 64),
    ("BranchBench", 500_000, 512, 64),
    ("MachineBench", 500_000, 512, 64),
]
RUNTIME_QUICK = {"ArithBench", "StrBench", "TrapBench"}

# ReadBench — отдельный контур: нагрузку задаёт размер stdin, а не REPEAT.
# Базовый вход читает и интерпретатор; нативный замер — на входе x множитель.
READ_BASE_BYTES = 256 * 1024
READ_MULT_FULL, READ_MULT_QUICK = 256, 32


def gen_read_input(path, size):
    """Детерминированный вход: 64К-блок LCG-байт (печатаемые + \\n),
    затиражированный до размера — содержимое не влияет на путь чтения."""
    block = bytearray()
    x = 7
    for _ in range(65536):
        x = (x * 1103515245 + 12345) % (1 << 31)
        b = 32 + (x >> 16) % 95
        block.append(10 if b == 96 else b)
    data = bytes(block) * (size // 65536 + 1)
    path.write_bytes(data[:size])


def eatc(*args) -> list:
    return [sys.executable, "-m", "eatc", *args]


def count_tokens(text: str) -> int:
    return len(Lexer(text, "<bench>").tokenize())


class Res:
    def __init__(self, secs, rc, rss_mb, out, err):
        self.secs, self.rc, self.rss_mb = secs, rc, rss_mb
        self.out, self.err = out, err


def run_timed(cmd, *, stdin_path=None, capture=False, stdout_path=None,
              repeats=1) -> Res:
    """Минимум wall-time по repeats прогонам; RSS ребёнка через wait4."""
    best, rss, rc, out, err = None, 0.0, 0, b"", b""
    for _ in range(repeats):
        fin = open(stdin_path, "rb") if stdin_path else subprocess.DEVNULL
        if stdout_path:
            fout = open(stdout_path, "wb")
        elif capture:
            fout = subprocess.PIPE
        else:
            fout = subprocess.DEVNULL
        t0 = time.perf_counter()
        p = subprocess.Popen(cmd, stdin=fin, stdout=fout,
                             stderr=subprocess.PIPE, cwd=ROOT, env=ENV)
        if capture:
            out = p.stdout.read()
        err = p.stderr.read()
        _, status, ru = os.wait4(p.pid, 0)
        dt = time.perf_counter() - t0
        p.returncode = os.waitstatus_to_exitcode(status)
        rc = p.returncode
        peak = ru.ru_maxrss  # darwin: байты; linux: КБ
        if sys.platform != "darwin":
            peak *= 1024
        rss = max(rss, peak / (1 << 20))
        if stdin_path:
            fin.close()
        if stdout_path:
            fout.close()
        if best is None or dt < best:
            best = dt
        if rc != 0:
            break
    return Res(best, rc, rss, out or b"", err or b"")


def fmt_s(secs) -> str:
    return f"{secs:8.2f}s"


def fmt_rate(n_per_s) -> str:
    if n_per_s >= 1e6:
        return f"{n_per_s / 1e6:6.2f}M/с"
    return f"{n_per_s / 1e3:6.0f}K/с"


def section(title):
    print(f"\n==== {title} " + "=" * max(0, 66 - len(title)))


def table(headers, rows):
    widths = [max(len(str(headers[i])), *(len(str(r[i])) for r in rows))
              if rows else len(str(headers[i])) for i in range(len(headers))]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))


FAILURES: list = []


def fail(msg):
    FAILURES.append(msg)
    print(f"  !! FAIL: {msg}")


def errtail(err: bytes, n: int = 300) -> str:
    """Хвост stderr: у ошибок компиляции суть в первой строке, у
    Python-трейсбеков — в последней; берём первую строку + хвост."""
    text = err.decode(errors="replace").strip()
    if len(text) <= n:
        return text
    head = text.splitlines()[0][:100]
    return f"{head} … {text[-n:]}"


# ==== Секция 1: пайплайн компилятора ====================================

def bench_pipeline(quick: bool):
    section("ПАЙПЛАЙН КОМПИЛЯТОРА (Python-бутстрап eatc)")
    rt_text = RT.read_text(encoding="utf-8")
    repeats = 1 if quick else 2

    # базовая цена запуска процесса (пустая программа)
    tiny = OUT / "tiny.eat"
    tiny.write_text("func main() {\n}\n", encoding="utf-8")
    base = run_timed(eatc("lex", str(tiny)), repeats=3)
    print(f"базовая цена запуска (lex пустой программы): {base.secs:.2f}s\n")

    rows = []
    sizes = SIZES_QUICK if quick else SIZES_FULL
    inputs = []
    for label, n_funcs in sizes:
        text = genprog.gen_module(0, n_funcs, with_main=True)
        path = OUT / f"pipe_{label}.eat"
        path.write_text(text, encoding="utf-8")
        tokens = count_tokens(text)
        inputs.append((label, path, tokens))

        ir_path = OUT / f"pipe_{label}_rt.eat"
        ir_path.write_text(rt_text + "\n" + text, encoding="utf-8")

        stage_times = {}
        for stage, cmd_path in [("lex", path), ("parse", path),
                                ("typed", path), ("ir", ir_path)]:
            r = run_timed(eatc(stage, str(cmd_path)), repeats=repeats)
            if r.rc != 0:
                fail(f"pipeline {label}/{stage}: rc={r.rc}: "
                     f"{errtail(r.err)}")
            stage_times[stage] = r
        rows.append([
            f"{label} ({n_funcs} функций)",
            f"{len(text) / 1024:.0f} КБ",
            f"{tokens}",
            fmt_s(stage_times["lex"].secs),
            fmt_s(stage_times["parse"].secs),
            fmt_s(stage_times["typed"].secs),
            fmt_s(stage_times["ir"].secs),
            fmt_rate(tokens / max(1e-9, stage_times["parse"].secs)),
            f"{stage_times['ir'].rss_mb:.0f} МБ",
        ])
    table(["вход", "размер", "токенов", "lex", "parse", "typed",
           "ir (c Rt)", "parse ток/с", "peak RSS"], rows)

    if not quick:
        print("\nмногомодульная программа "
              f"({XL_FUNCS} функций, {XL_FUNCS_PER_FILE} на файл; "
              "предел языка — 1024):")
        files = genprog.gen_program(XL_FUNCS, XL_FUNCS_PER_FILE)
        paths = []
        total_bytes = total_tokens = 0
        for i, text in enumerate(files):
            p = OUT / f"xl_{i:02d}.eat"
            p.write_text(text, encoding="utf-8")
            paths.append(str(p))
            total_bytes += len(text)
            total_tokens += count_tokens(text)
        r = run_timed(eatc("run", str(RT), *paths))
        if r.rc != 0:
            fail(f"pipeline XL run: {errtail(r.err)}")
        print(f"  {len(files)} файлов, {total_bytes / 1024:.0f} КБ, "
              f"{total_tokens} токенов: полный фронтенд + интерпретация "
              f"main за {r.secs:.2f}s ({fmt_rate(total_tokens / r.secs)} "
              f"токенов), peak RSS {r.rss_mb:.0f} МБ")
    return inputs


# ==== Секция 2: скорость программ =======================================

def bench_runtime(quick: bool):
    section("СКОРОСТЬ ПРОГРАММ (интерпретатор против бинарника)")
    rows = []
    for name, base_ops, rep_full, rep_quick in RUNTIME_PROGRAMS:
        if quick and name not in RUNTIME_QUICK:
            continue
        src = PROGRAMS / f"{name}.eat"
        text = src.read_text(encoding="utf-8")

        # интерпретатор: базовая порция, вывод забираем для сверки
        interp = run_timed(eatc("run", str(RT), str(src)), capture=True)
        if interp.rc != 0:
            fail(f"runtime {name} interp: {errtail(interp.err)}")
            continue

        # сборка базового варианта и дифференциальная сверка вывода
        bin_base = OUT / name
        build = run_timed(
            eatc("build", str(RT), str(src), "-o", str(bin_base)))
        if build.rc != 0:
            fail(f"runtime {name} build: {errtail(build.err)}")
            continue
        nat_base = run_timed([str(bin_base)], capture=True, repeats=3)
        same = nat_base.out == interp.out
        if not same:
            fail(f"runtime {name}: вывод интерпретатора и бинарника "
                 f"расходится: {interp.out!r} != {nat_base.out!r}")

        # нативный замер: REPEAT масштабируем, чтобы уйти от шума таймера
        rep = rep_quick if quick else rep_full
        marker = "const REPEAT: u32 = 1"
        assert marker in text, f"{name}: нет константы REPEAT"
        xl_src = OUT / f"{name}XL.eat"
        xl_src.write_text(text.replace(
            marker, f"const REPEAT: u32 = {rep}"), encoding="utf-8")
        bin_xl = OUT / f"{name}XL"
        bxl = run_timed(eatc("build", str(RT), str(xl_src),
                             "-o", str(bin_xl)))
        if bxl.rc != 0:
            fail(f"runtime {name} XL build: {errtail(bxl.err)}")
            continue
        nat = run_timed([str(bin_xl)], repeats=3)
        if nat.rc != 0:
            fail(f"runtime {name} XL: rc={nat.rc} {errtail(nat.err)}")
            continue

        i_rate = base_ops / interp.secs
        n_rate = base_ops * rep / nat.secs
        rows.append([
            name,
            f"{base_ops / 1e6:.2f}M оп",
            fmt_s(interp.secs),
            fmt_rate(i_rate),
            fmt_s(build.secs),
            f"{fmt_s(nat.secs)} (x{rep})",
            fmt_rate(n_rate),
            f"x{n_rate / i_rate:,.0f}".replace(",", " "),
            "да" if same else "НЕТ",
        ])
    bench_read(quick, rows)
    table(["программа", "порция", "интерп", "интерп оп/с", "сборка",
           "бинарник", "бинарник оп/с", "ускорение", "вывод =="], rows)


def bench_read(quick: bool, rows: list):
    """ReadBench: путь ввода (read_byte/Result). Нагрузка — размер stdin."""
    src = PROGRAMS / "ReadBench.eat"
    base_in = OUT / "read_in_base.bin"
    if not base_in.exists() or base_in.stat().st_size != READ_BASE_BYTES:
        gen_read_input(base_in, READ_BASE_BYTES)

    interp = run_timed(eatc("run", str(RT), str(src)),
                       stdin_path=str(base_in), capture=True)
    if interp.rc != 0:
        fail(f"runtime ReadBench interp: {errtail(interp.err)}")
        return
    bin_path = OUT / "ReadBench"
    build = run_timed(eatc("build", str(RT), str(src), "-o", str(bin_path)))
    if build.rc != 0:
        fail(f"runtime ReadBench build: {errtail(build.err)}")
        return
    nat_base = run_timed([str(bin_path)], stdin_path=str(base_in),
                         capture=True, repeats=3)
    same = nat_base.out == interp.out
    if not same:
        fail(f"runtime ReadBench: вывод расходится: "
             f"{interp.out!r} != {nat_base.out!r}")

    mult = READ_MULT_QUICK if quick else READ_MULT_FULL
    xl_in = OUT / "read_in_xl.bin"
    xl_size = READ_BASE_BYTES * mult
    if not xl_in.exists() or xl_in.stat().st_size != xl_size:
        gen_read_input(xl_in, xl_size)
    nat = run_timed([str(bin_path)], stdin_path=str(xl_in), repeats=3)
    if nat.rc != 0:
        fail(f"runtime ReadBench XL: rc={nat.rc} {errtail(nat.err)}")
        return

    i_rate = READ_BASE_BYTES / interp.secs
    n_rate = xl_size / nat.secs
    rows.append([
        "ReadBench",
        f"{READ_BASE_BYTES / 1e6:.2f}M байт",
        fmt_s(interp.secs),
        fmt_rate(i_rate),
        fmt_s(build.secs),
        f"{fmt_s(nat.secs)} (вход x{mult})",
        fmt_rate(n_rate),
        f"x{n_rate / i_rate:,.0f}".replace(",", " "),
        "да" if same else "НЕТ",
    ])


# ==== Секция 3: стресс лимитов ==========================================

def bench_stress(quick: bool):
    section("СТРЕСС ЛИМИТОВ (SPEC.md §6): принять или быстро отказать")
    cases = [
        ("токены: ~130К (под пределом)", genprog.stress_tokens(130_000),
         "lex", True),
        ("токены: ~140К (за пределом 131072)",
         genprog.stress_tokens(140_000), "lex", False),
        ("функции: 1024 (на пределе)", genprog.stress_funcs(1024),
         "check", True),
        ("функции: 1025 (за пределом)", genprog.stress_funcs(1025),
         "check", False),
        ("операторы: 60 (на пределе)", genprog.stress_stmts(60),
         "check", True),
        ("операторы: 61 (за пределом)", genprog.stress_stmts(61),
         "check", False),
        ("блоки: глубина 8 (на пределе)", genprog.stress_block_depth(8),
         "check", True),
        ("блоки: глубина 9 (за пределом)", genprog.stress_block_depth(9),
         "check", False),
        ("выражение: 31 скобка (на пределе)",
         genprog.stress_expr_depth(31), "check", True),
        ("выражение: 32 скобки (за пределом)",
         genprog.stress_expr_depth(32), "check", False),
    ]
    rows = []
    for i, (label, text, cmd, expect_ok) in enumerate(cases):
        path = OUT / f"stress_{i:02d}.eat"
        path.write_text(text, encoding="utf-8")
        t0 = time.perf_counter()
        try:
            p = subprocess.run(eatc(cmd, str(path)), cwd=ROOT, env=ENV,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE,
                               timeout=STRESS_TIMEOUT)
            dt = time.perf_counter() - t0
            got_ok = p.returncode == 0
            err1 = p.stderr.decode().splitlines()
            clean = (not got_ok) == bool(err1)  # отказ обязан объясниться
            verdict = "PASS" if got_ok == expect_ok and clean else "FAIL"
            if got_ok:
                result = "принят"
            elif err1:
                result = "отказ: " + err1[0].split("error:")[-1].strip()[:52]
            else:
                result = "молчаливый отказ"
        except subprocess.TimeoutExpired:
            dt, verdict, result = STRESS_TIMEOUT, "FAIL", "зависание"
        if verdict == "FAIL":
            fail(f"stress «{label}»: {result}")
        rows.append([label, f"{len(text) / 1024:.0f} КБ", f"{dt:6.2f}s",
                     result, verdict])
    table(["случай", "вход", "время", "итог", "вердикт"], rows)


# ==== Секция 4: self-hosted компилятор ==================================

LIB_FRONT = ["lib/Ascii.eat", "lib/Buf.eat", "lib/Hex.eat"]

SELF_BINARIES = {
    "SelfLex": LIB_FRONT + ["selfhost/Tok.eat", "selfhost/Lexer.eat",
                            "selfhost/LexMain.eat"],
    "SelfParse": LIB_FRONT + ["selfhost/Tok.eat", "selfhost/Lexer.eat",
                              "selfhost/Ast.eat", "selfhost/Parser.eat",
                              "selfhost/ParseMain.eat"],
}


def bench_selfhost(quick: bool, inputs):
    section("SELF-HOSTED КОМПИЛЯТОР против Python-эталона")
    if not inputs:
        text = genprog.gen_module(0, 64, with_main=True)
        path = OUT / "self_input.eat"
        path.write_text(text, encoding="utf-8")
        inputs = [("M", path, count_tokens(text))]

    bins = {}
    for name, mods in SELF_BINARIES.items():
        binary = ROOT / "build" / name
        if not binary.exists():
            if quick:
                print(f"  {name} не собран — пропуск "
                      f"(соберите: make verify_selfhost)")
                continue
            print(f"  сборка {name} Python-бутстрапом "
                  f"(само по себе нагрузочный тест)...")
            mods_abs = [str(RT)] + [str(ROOT / m) for m in mods]
            r = run_timed(eatc("build", *mods_abs, "-o", str(binary)))
            if r.rc != 0:
                fail(f"selfhost: сборка {name}: {errtail(r.err)}")
                continue
            print(f"    собран за {r.secs:.2f}s")
        bins[name] = binary

    rows = []
    for name, py_cmd in [("SelfLex", "lex"), ("SelfParse", "parse")]:
        if name not in bins:
            continue
        # от большего входа к меньшему: пулы self-hosted компилятора
        # меньше лимитов Python-эталона (например, ≤65536 узлов AST) —
        # отказ «err: ...» фиксируем и спускаемся на ступень ниже
        for label, path, tokens in reversed(inputs):
            self_dump = OUT / f"self_{py_cmd}_self.txt"
            nat = run_timed([str(bins[name])], stdin_path=str(path),
                            stdout_path=str(self_dump), repeats=3)
            # отказ пулов: rc=1 + «err: ...» в stderr (err в stdout —
            # наследие до eprint-хелпера)
            first = self_dump.read_bytes()[:200]
            rej = nat.err[:200] if nat.err.startswith(b"err:") else (
                first if first.startswith(b"err:") else None)
            if rej is not None:
                print(f"  {name}: вход {label} ({tokens} токенов) "
                      f"отвергнут пулами: "
                      f"{rej.decode().splitlines()[0][:70]}")
                continue
            if nat.rc != 0:
                fail(f"selfhost: {name}: rc={nat.rc} "
                     f"{errtail(nat.err)}")
                break
            ref_dump = OUT / f"self_{py_cmd}_ref.txt"
            py = run_timed(eatc(py_cmd, str(path)),
                           stdout_path=str(ref_dump))
            if py.rc != 0:
                fail(f"selfhost: эталон {py_cmd}: "
                     f"{errtail(py.err)}")
                break
            same = ref_dump.read_bytes() == self_dump.read_bytes()
            if not same:
                fail(f"selfhost: дамп {name} расходится с эталоном "
                     f"({ref_dump} vs {self_dump})")
            rows.append([
                f"{py_cmd}, вход {label} ({tokens} токенов)",
                fmt_s(py.secs), fmt_rate(tokens / py.secs),
                fmt_s(nat.secs), fmt_rate(tokens / nat.secs),
                f"x{py.secs / nat.secs:.1f}",
                "да" if same else "НЕТ",
            ])
            break
    if rows:
        table(["стадия", "Python", "ток/с", "нативный", "ток/с",
               "ускорение", "дамп =="], rows)


# ==== Секция 5: компиляция компилятора ==================================

# Фазовые бинарники self-hosted компилятора (зеркало списков Makefile);
# вход всех замеров — конкатенация модулей SelfIr (вход verify_bootstrap)
SELF_FRONT = ["selfhost/Tok.eat", "selfhost/Lexer.eat"]
SELF_MID = SELF_FRONT + ["selfhost/Ast.eat", "selfhost/Parser.eat",
                         "selfhost/Check.eat"]
SELF_STAGES = [
    ("SelfLex", "lex", LIB_FRONT + SELF_FRONT + ["selfhost/LexMain.eat"]),
    ("SelfParse", "parse",
     LIB_FRONT + SELF_FRONT + ["selfhost/Ast.eat", "selfhost/Parser.eat",
                               "selfhost/ParseMain.eat"]),
    ("SelfSig", "sig", LIB_FRONT + SELF_MID + ["selfhost/SigMain.eat"]),
    ("SelfTyped", "typed", LIB_FRONT + SELF_MID + ["selfhost/TypedMain.eat"]),
    ("SelfIr", "ir",
     LIB_FRONT + ["lib/Fmt.eat"] + SELF_MID + ["selfhost/Ir.eat",
                                               "selfhost/IrMain.eat"]),
]


def stage_binary(name, mods, quick):
    """build/<name>, свежий относительно исходников selfhost/; устаревший
    бинарник молча выдаёт err: в stdout — поэтому пересборка (полный
    режим) или пропуск с подсказкой (быстрый)."""
    binary = ROOT / "build" / name
    srcs = [RT] + [ROOT / m for m in mods]
    deps = srcs + [ROOT / "src" / "eatc" / "runtime.c"]
    fresh = binary.exists() and \
        binary.stat().st_mtime >= max(d.stat().st_mtime for d in deps)
    if fresh:
        return binary
    state = "устарел" if binary.exists() else "не собран"
    if quick:
        print(f"  {name} {state} — пропуск (соберите: make verify_selfhost)")
        return None
    print(f"  {name} {state} — сборка Python-бутстрапом...")
    # пути относительно корня: они попадают в trap-сообщения, и
    # абсолютные раздували бы данные против сборки из make
    r = run_timed(eatc("build", *(str(s.relative_to(ROOT)) for s in srcs),
                       "-o", str(binary)))
    if r.rc != 0:
        fail(f"compiler: сборка {name}: {errtail(r.err)}")
        return None
    print(f"    собран за {r.secs:.2f}s")
    return binary


def bench_compiler(quick: bool):
    section("КОМПИЛЯЦИЯ КОМПИЛЯТОРА (selfhost-бинарники на своих исходниках)")
    parts = [RT] + [ROOT / m for m in SELF_STAGES[-1][2]]
    data = b"".join(p.read_bytes() for p in parts)
    src = OUT / "self_src.eat"
    src.write_bytes(data)
    tokens = count_tokens(data.decode("utf-8"))
    print(f"вход: конкатенация {len(parts)} модулей компилятора "
          f"({len(data) / 1024:.0f} КБ, {tokens} токенов)")

    stage_repeats = 2 if quick else 3
    py_repeats = 1 if quick else 2
    rows = []
    for name, py_cmd, mods in SELF_STAGES:
        binary = stage_binary(name, mods, quick)
        if binary is None:
            continue
        self_dump = OUT / f"comp_{py_cmd}_self.txt"
        nat = run_timed([str(binary)], stdin_path=str(src),
                        stdout_path=str(self_dump), repeats=stage_repeats)
        if nat.rc != 0 or self_dump.read_bytes()[:4].startswith(b"err:"):
            fail(f"compiler: {name}: rc={nat.rc}, "
                 f"stderr {nat.err[:80]!r}, вывод "
                 f"{self_dump.read_bytes()[:80]!r}")
            continue
        ref_dump = OUT / f"comp_{py_cmd}_ref.txt"
        py = run_timed(eatc(py_cmd, str(src)), stdout_path=str(ref_dump),
                       repeats=py_repeats)
        if py.rc != 0:
            fail(f"compiler: эталон {py_cmd}: {errtail(py.err)}")
            continue
        same = ref_dump.read_bytes() == self_dump.read_bytes()
        if not same:
            fail(f"compiler: дамп {name} расходится с эталоном "
                 f"({ref_dump} vs {self_dump})")
        rows.append([
            f"{py_cmd} ({name})",
            fmt_s(nat.secs), fmt_rate(tokens / nat.secs),
            fmt_s(py.secs), fmt_rate(tokens / py.secs),
            f"x{py.secs / nat.secs:.1f}",
            f"{self_dump.stat().st_size / (1 << 20):.2f} МБ",
            "да" if same else "НЕТ",
        ])
    if rows:
        table(["стадия", "нативный", "ток/с", "Python", "ток/с",
               "нативн./Python", "вывод", "дамп =="], rows)


# ==== Секция 6: размеры бинарников и данных (метрика МК/флеша) ==========

# Типичная МК-программа набора — эмулятор mos6502 (examples/);
# после этапа модулей зависит от lib/Hex.eat (зеркало MOS6502_EXAMPLE
# из Makefile — модули подключаются явным списком файлов)
MOS_LIB = [Path("lib/Hex.eat")]
MOS_SRCS = ["Cpu6502.eat", "Tests.eat", "Main.eat"]


def example_binary(name, srcs, quick, flags=()):
    """build/<name> из списка исходников; та же логика свежести,
    что у stage_binary. flags — доп. флаги eatc build (--trap-codes)."""
    binary = ROOT / "build" / name
    deps = srcs + [ROOT / "src" / "eatc" / "runtime.c"]
    fresh = binary.exists() and \
        binary.stat().st_mtime >= max(d.stat().st_mtime for d in deps)
    if fresh:
        return binary
    state = "устарел" if binary.exists() else "не собран"
    if quick:
        print(f"  {name} {state} — пропуск (соберите: make verify)")
        return None
    print(f"  {name} {state} — сборка Python-бутстрапом...")
    # относительные пути — см. stage_binary (trap-сообщения)
    r = run_timed(eatc("build", *flags,
                       *(str(s.relative_to(ROOT)) for s in srcs),
                       "-o", str(binary)))
    if r.rc != 0:
        fail(f"size: сборка {name}: {errtail(r.err)}")
        return None
    print(f"    собран за {r.secs:.2f}s")
    return binary


def darwin_sections(binary):
    """Размеры секций кода/констант (байт): на macOS — `size -m`
    (__text/__const), на linux — `size -A` (.text/.rodata под теми же
    ключами). Пусто при ошибке — колонки покажут «-»."""
    if sys.platform == "darwin":
        r = subprocess.run(["size", "-m", str(binary)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return {}
        secs = {}
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("Section __"):
                name, _, val = line.partition(":")
                key = name.split()[1]
                # __const бывает и в __TEXT, и в __DATA_CONST — сумма
                secs[key] = secs.get(key, 0) + int(val)
        return secs
    r = subprocess.run(["size", "-A", str(binary)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    secs = {}
    alias = {".text": "__text", ".rodata": "__const"}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in alias:
            secs[alias[parts[0]]] = int(parts[1])
    return secs


def ll_string_stats(ll_path):
    """Канонический .ll: (строковых глобалов, из них trap, байт в trap,
    вызовов llvm.memcpy). Trap-строки — глобалы вида
    `stdin:line:col: error: trap: ...` — главный раздуватель данных."""
    total = traps = trap_bytes = memcpy = 0
    with open(ll_path, encoding="utf-8") as f:
        for line in f:
            if line.startswith('@"str.'):
                total += 1
                if "error: trap" in line:
                    traps += 1
                    m = re.search(r"\[(\d+) x i8\]", line)
                    if m:
                        trap_bytes += int(m.group(1))
            elif "llvm.memcpy" in line:
                memcpy += 1
    return total, traps, trap_bytes, memcpy


def bench_size(quick: bool):
    section("РАЗМЕРЫ (бинарник, секции, строковые данные — метрика флеша)")
    targets = []
    for name, _, mods in SELF_STAGES:
        binary = stage_binary(name, mods, quick)
        if binary is not None:
            targets.append((name, binary))
    mos_srcs = [RT] + [ROOT / m for m in MOS_LIB] + \
        [ROOT / "examples" / "mos6502" / m for m in MOS_SRCS]
    hello_srcs = [RT, ROOT / "examples" / "hello_world" / "HelloWorld.eat"]
    ir_srcs = [RT] + [ROOT / m for m in SELF_STAGES[-1][2]]
    mos = example_binary("Mos6502", mos_srcs, quick)
    if mos is not None:
        targets.append(("Mos6502", mos))
    hello = example_binary("HelloWorld", hello_srcs, quick)
    if hello is not None:
        targets.append(("HelloWorld", hello))
    # режим trap-кодов (--trap-codes): вклад trap-строк во флеш
    for label, bname, srcs in (
        ("SelfIr (trap-коды)", "SelfIrTc", ir_srcs),
        ("Mos6502 (trap-коды)", "Mos6502Tc", mos_srcs),
        ("HelloWorld (trap-коды)", "HelloWorldTc", hello_srcs),
    ):
        b = example_binary(bname, srcs, quick, flags=("--trap-codes",))
        if b is not None:
            targets.append((label, b))

    def kb(n):
        return f"{n / 1024:.1f} КБ" if n is not None else "-"

    rows = []
    for name, binary in targets:
        secs = darwin_sections(binary)
        ll = binary.with_suffix(".ll")
        if ll.exists():
            total, traps, tbytes, memcpy = ll_string_stats(ll)
            ll_col = f"{ll.stat().st_size / (1 << 20):.2f} МБ"
            str_col, trap_col = str(total), str(traps)
            tb_col, mc_col = kb(tbytes), str(memcpy)
        else:
            ll_col = str_col = trap_col = tb_col = mc_col = "-"
        rows.append([
            name,
            kb(binary.stat().st_size),
            kb(secs.get("__text")),
            kb(secs.get("__const")),
            str_col, trap_col, tb_col, mc_col, ll_col,
        ])
    if rows:
        table(["программа", "бинарник", "__text", "__const",
               "стр-глобалов", "trap-строк", "trap-байт", "memcpy",
               "канон .ll"], rows)


# ==== Точка входа =======================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true",
                    help="быстрый прогон: меньше размеры и повторы")
    ap.add_argument("--only", default="",
                    help="секции через запятую: pipeline,runtime,"
                         "stress,selfhost,compiler,size")
    args = ap.parse_args()
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    def wanted(name):
        return not only or name in only

    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    print(f"Нагрузочное тестирование EATLang "
          f"({'быстрый' if args.quick else 'полный'} режим); "
          f"артефакты: {OUT.relative_to(ROOT)}/")

    inputs = None
    if wanted("pipeline"):
        inputs = bench_pipeline(args.quick)
    if wanted("runtime"):
        bench_runtime(args.quick)
    if wanted("stress"):
        bench_stress(args.quick)
    if wanted("selfhost"):
        bench_selfhost(args.quick, inputs)
    if wanted("compiler"):
        bench_compiler(args.quick)
    if wanted("size"):
        bench_size(args.quick)

    section("ИТОГО")
    print(f"общее время: {time.perf_counter() - t0:.1f}s")
    if FAILURES:
        print(f"ПРОВАЛОВ: {len(FAILURES)}")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
