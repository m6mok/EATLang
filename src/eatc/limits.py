"""Пределы компилятора (SPEC.md §6). Фиксированные пулы вместо кучи."""

MAX_STMTS_PER_FUNC = 60  # правило 4 NASA
MAX_PARAMS = 6
MAX_BLOCK_DEPTH = 8
MAX_EXPR_DEPTH = 32
MAX_TOKENS_PER_FILE = 131_072
MAX_AST_NODES = 131_072  # ёмкость пула узлов self-hosted парсера (2 банка)
MAX_FUNCS_PER_PROGRAM = 1_024
MAX_STR_CAPACITY = 256  # == EAT_STR_CAP рантайма: тип не обещает больше буфера
MAX_ARRAY_ELEMS = 65_536
MAX_MODULES = 64  # именованных модулей в потоке (#module)
MAX_IMPORT_BINDS = 512  # импортированных имён на программу
MAX_MODULE_PATH = 128  # длина канонического пути модуля в байтах
# comptime (§5): предел шагов на ОДИН const-вызов (не суммарный —
# иначе порядок объявлений влиял бы на успех). Шаг — одно вычисленное
# выражение (eval) или инструкция (exec_stmt) вычислителя; определение
# фиксировано в SPEC §6 и зеркалится в selfhost Eval.eat байт-в-байт.
# 1e6: таблица CRC 256×8 ≈ 20К шагов, запас ×50.
MAX_COMPTIME_STEPS = 1_000_000
