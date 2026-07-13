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
