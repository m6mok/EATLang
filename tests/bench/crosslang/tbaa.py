"""Эксперимент §8.3 OPTIMIZATIONS_PLAN: alias-инфа в эмиссии —
TBAA-метаданные пост-проходом по llvmlite-модулю, строго build-only
слоем ВНЕ канона (src/eatc не тронут ни байтом: патчится
Codegen.generate в памяти этого процесса; `eatc ir`, гейты и
фикспойнт не видят эксперимента).

Гипотеза (дозамер 7.2, FINDINGS «HTTP-парсер»): разрыв EAT/C = 1,35
живёт в самом эмитируемом IR — без alias-инфы ни мид-энд llvmlite,
ни clang не промотируют поля 8,5-КБ Req через побайтовый цикл:
store в raw[i] (индекс переменный) может алиасить n/state/ls.

Схема тегов — скалярный TBAA: узел на идентичность (тип корня GEP,
путь: поле структуры — индексом, шаг массива — общий "[]", т.е. все
элементы одного массива делят узел). Тег ставится только на
load/store, чей указатель — цепочка GEP с первым индексом 0 и
константными индексами полей до корня (alloca/аргумент/глобал/
bitcast); всё прочее (memcpy агрегатов, str-глобалы под bitcast,
сам bitcast-корень) остаётся без тега = консервативный MayAlias.

Почему это корректно в EATLang: указателей и union в языке нет,
память двух разных путей полей не перекрывается никогда; enum с
нагрузкой — слот на вариант, не union (codegen.enum_ll_of); str-
литералы короче 256 читаются только через тип str (bitcast выдаёт
STR*-указатель, корень тот же). Разные корневые типы никогда не
смотрят в одну память (bitcast в эмиссии один — str-литералы).

Запуск: uv run python tests/bench/crosslang/tbaa.py
        [--quick] [--only http,branch,sort,mos6502] [--json PATH]
"""

import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run as cl  # noqa: E402  — методика замера crosslang

sys.path.insert(0, str(cl.ROOT / "src"))
from llvmlite import ir  # noqa: E402
import eatc.codegen as cgm  # noqa: E402
from eatc import __main__ as em  # noqa: E402

if sys.platform == "darwin":
    STACK = ["-Wl,-stack_size,0x10000000"]
else:
    STACK = ["-Wl,-z,stacksize=268435456"]

KEYS = ["http", "branch", "sort", "mos6502"]  # http + регресс-тройка


# ---------------------------------------------------------------------------
# Пост-проход: скалярные TBAA-теги по путям GEP

def _access_path(ptr):
    """Идентичность памяти под указателем: (repr корневого типа,
    кортеж шагов). None — путь не разобран, тег не ставим."""
    steps: list = []
    while type(ptr).__name__ == "GEPInstr":
        base = ptr.operands[0]
        idxs = ptr.operands[1:]
        bt = base.type
        if not isinstance(bt, ir.PointerType):
            return None
        if getattr(idxs[0], "constant", None) != 0:
            return None
        t = bt.pointee
        sub: list = []
        for ix in idxs[1:]:
            if isinstance(t, ir.ArrayType):
                sub.append("[]")
                t = t.element
            elif hasattr(t, "elements") and t.elements is not None:
                c = getattr(ix, "constant", None)
                if not isinstance(c, int):
                    return None
                sub.append(f".{c}")
                t = t.elements[c]
            else:
                return None
        steps = sub + steps
        ptr = base
    bt = ptr.type
    if not isinstance(bt, ir.PointerType):
        return None
    return (str(bt.pointee), tuple(steps))


def annotate(module: ir.Module) -> dict:
    """Навесить !tbaa на все разобранные load/store; вернуть счётчики."""
    root = module.add_metadata(["eatlang tbaa"])
    zero = ir.Constant(ir.IntType(64), 0)
    tags: dict = {}
    stats = {"tagged": 0, "skipped": 0, "nodes": 0}

    def tag_of(ident):
        tag = tags.get(ident)
        if tag is None:
            node = module.add_metadata(
                [f"{ident[0]}|{'/'.join(ident[1])}", root, zero]
            )
            tag = module.add_metadata([node, node, zero])
            tags[ident] = tag
            stats["nodes"] += 1
        return tag

    for fn in module.functions:
        for blk in fn.blocks:
            for instr in blk.instructions:
                kind = type(instr).__name__
                if kind == "LoadInstr":
                    ptr = instr.operands[0]
                elif kind == "StoreInstr":
                    ptr = instr.operands[1]
                else:
                    continue
                ident = _access_path(ptr)
                if ident is None:
                    stats["skipped"] += 1
                    continue
                instr.set_metadata("tbaa", tag_of(ident))
                stats["tagged"] += 1
    return stats


# Патч generate: тот же кодоген, плюс аннотация при включённом флаге
_ORIG_GENERATE = cgm.Codegen.generate
_PATCH = {"on": False, "stats": None}


def _generate(self):
    module = _ORIG_GENERATE(self)
    if _PATCH["on"]:
        _PATCH["stats"] = annotate(module)
    return module


cgm.Codegen.generate = _generate


def build_tbaa(paths: list, bin_: Path, lib_root=None) -> dict:
    """`eatc build` в этом процессе с TBAA-постпроходом; .ll с тегами
    остаётся рядом с бинарником (вход clang-варианта)."""
    em.LIB_ROOTS[:] = [str(lib_root)] if lib_root else []
    _PATCH["on"] = True
    try:
        rc = em.cmd_build([str(p) for p in paths], str(bin_))
    finally:
        _PATCH["on"] = False
        em.LIB_ROOTS[:] = []
    if rc != 0:
        raise RuntimeError(f"cmd_build rc={rc} для {bin_}")
    return _PATCH["stats"]


# ---------------------------------------------------------------------------
# Варианты и замер (методика backends.py: сверка stdout, медиана 5)

def measure_entries(rows, bench, runs, entries, op_unit,
                    verify_stdin, measure_stdin, ops_static=None):
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


def entries_for(paths, stem, rep, lib_root, base_cmd, base_bin):
    """Тройка вариантов: штатный build, build+TBAA (llvmlite),
    тот же теговый .ll через clang -O2."""
    bin_t = cl.OUT / f"{stem}_tbaa_r{rep}"
    stats = build_tbaa(paths, bin_t, lib_root)
    print(f"  TBAA: тегов {stats['tagged']}, узлов {stats['nodes']}, "
          f"без тега {stats['skipped']}")
    ll_t = bin_t.with_suffix(".ll")
    bin_c = cl.OUT / f"{stem}_tbaa_clang_r{rep}"
    cl.sh(["clang", "-O2", ll_t, cl.RUNTIME_C, "-o", bin_c] + STACK)
    return [
        ("build (llvmlite)", base_cmd, base_bin),
        ("build+TBAA (llvmlite)", [bin_t], bin_t),
        (".ll+TBAA → clang -O2", [bin_c], bin_c),
    ]


def bench_micro(key, quick, rows):
    name, base_ops, rep_full, rep_quick, _rep_py, libs = cl.BENCHES[key]
    rep = rep_quick if quick else rep_full
    runs = cl.RUNS_QUICK if quick else cl.RUNS_FULL
    print(f"\n=== {key} ({name}, REPEAT={rep}) ===")
    cmd, bin_, _secs = cl.build_eat(name, key, libs, rep)
    src = cl.OUT / f"{name}_eat_r{rep}.eat"
    if libs == "driver":
        paths, lib_root = [src], cl.ROOT
    else:
        paths = [cl.RT, *(cl.ROOT / lb for lb in libs), src]
        lib_root = None
    entries = entries_for(paths, key, rep, lib_root, cmd, bin_)
    measure_entries(rows, key, runs, entries, "оп", None, None,
                    ops_static=base_ops * rep)


def bench_mos(quick, rows):
    runs = cl.RUNS_QUICK if quick else cl.RUNS_FULL
    roms = {}
    for tag in ("verify", "native", "native_quick"):
        roms[tag] = cl.OUT / f"rom_{tag}.rom"
        cl.sh([sys.executable, HERE / "gen6502.py", *cl.MOS_ROMS[tag],
               "-o", roms[tag]])
    heavy = roms["native_quick" if quick else "native"]
    print("\n=== mos6502 (нагрузка — ROM со stdin, метрика — нс/шаг) ===")
    eat_srcs = [cl.ROOT / p for p in cl.MOS_EAT_SRC]
    bin_ = cl.OUT / "most_eat"
    cl.sh(cl.eatc("build", cl.RT, *eat_srcs, "-o", bin_))
    entries = entries_for([cl.RT, *eat_srcs], "most", 1, None,
                          [bin_], bin_)
    measure_entries(rows, "mos6502", runs, entries, "шаг",
                    roms["verify"], heavy)


# Идиома EAT «скан с нуля под стражем» (границы циклов статичны,
# Power of 10): те же два скана C-порта в форме lib/Http.eat —
# цена идиомы, измеренная «известно-хорошим» тулчейном clang
_IDIOM = [(
    """    for (uint32_t i = b0; i < e0; i++) {
        if (r->raw[i] == 32) {
            return i;
        }
    }
    return HTTP_NONE;""",
    """    uint32_t at = HTTP_NONE;
    for (uint32_t i = 0; i < 8192; i++) {
        if (i >= e0 || at != HTTP_NONE) break;
        if (i >= b0) {
            if (r->raw[i] == 32) at = i;
        }
    }
    return at;""",
), (
    """    uint32_t colon = HTTP_NONE;
    for (uint32_t i = ls2; i < le; i++) {
        if (r->raw[i] == 58) {
            colon = i;
            break;
        }
    }""",
    """    uint32_t colon = HTTP_NONE;
    for (uint32_t i = 0; i < 8192; i++) {
        if (i >= le || colon != HTTP_NONE) break;
        if (i >= ls2) {
            if (r->raw[i] == 58) colon = i;
        }
    }""",
)]


def bench_c_control(quick, rows):
    """Контроль гипотезы с двух сторон C-портом http: (1) без strict
    aliasing (-fno-strict-aliasing = отнять у clang его TBAA);
    (2) с EAT-идиомой сканов «с нуля под стражем» (find_sp + двоеточие
    parse_header) — цена идиомы против цены alias-инфы."""
    rep = 32 if quick else 256
    runs = cl.RUNS_QUICK if quick else cl.RUNS_FULL
    print(f"\n=== http C-контроль (aliasing/идиома, REPEAT={rep}) ===")
    src = cl.scaled("c", HERE / "c" / "http.c", rep)
    text = src.read_text(encoding="utf-8")
    for old, new in _IDIOM:
        assert old in text, "c/http.c: скан-идиома уехала, обнови _IDIOM"
        text = text.replace(old, new)
    src_idiom = cl.OUT / f"http_c_eatidiom_r{rep}.c"
    src_idiom.write_text(text, encoding="utf-8")
    entries = []
    for label, flags, s in (
            ("C -O2", ["-O2"], src),
            ("C -O2 -fno-strict-aliasing",
             ["-O2", "-fno-strict-aliasing"], src),
            ("C -O2, EAT-идиома сканов", ["-O2"], src_idiom)):
        b = cl.OUT / ("httpc_" + re.sub(r"[^a-zA-Z0-9]+", "_", label))
        cl.sh(["clang", *flags, s, "-o", b])
        entries.append((label, [b], b))
    measure_entries(rows, "http_c", runs, entries, "оп", None, None,
                    ops_static=2_000 * rep)


def main():
    argv = sys.argv[1:]
    quick = "--quick" in argv
    only = None
    if "--only" in argv:
        only = set(argv[argv.index("--only") + 1].split(","))
    json_path = cl.OUT / "tbaa.json"
    if "--json" in argv:
        json_path = Path(argv[argv.index("--json") + 1])

    cl.OUT.mkdir(parents=True, exist_ok=True)
    rows: list = []
    t0 = time.perf_counter()
    for key in KEYS:
        if only and key not in only:
            continue
        if key == "mos6502":
            bench_mos(quick, rows)
        else:
            bench_micro(key, quick, rows)
    if not only or "http" in only:
        bench_c_control(quick, rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(f"\nJSON: {json_path}")
    print(f"общее время: {time.perf_counter() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
