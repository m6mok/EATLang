# EATLang — собственный синтаксис, см. SPEC.md
# Компилятор: src/eatc/ (Python bootstrap; впереди — llvmlite → LLVM IR)

EATC = PYTHONPATH=src uv run python -m eatc

# Параллелизм пофайловых циклов гейта (OPTIMIZATIONS_PLAN §3.5):
# воркеры tests/gate/*.sh через xargs -P, временные файлы уникальны
# (mktemp) — гейты в разных worktree больше не делят /tmp
JOBS ?= $(shell sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)

# Рантайм-модуль (фаза 6): логика строк/вывода/разбора — на EATLang,
# первый модуль каждой программы; в C остался шим аксиом ОС (runtime.c)
RT = selfhost/Rt.eat

EXAMPLES = \
	examples/hello_world/HelloWorld.eat \
	examples/math/Math.eat \
	examples/functions/Functions.eat \
	examples/if_statement/IfStatement.eat \
	examples/iterator/Iterator.eat \
	examples/struct/Struct.eat \
	examples/alias/Alias.eat \
	examples/all/All.eat

# Elif — витрина драйвера импортов (read_line/parse_i32 из lib/,
# этап 2 модулей): собирается с --lib ., отдельно от списка выше
ELIF_MAIN = examples/if_statement/Elif.eat

# JSON — витрина lib/Json.eat (docs/plans/JSON_PLAN.md): bounded-JSON
# без рекурсии/кучи/while; check исполняет и тесты самого модуля
JSON_MAIN = examples/json/Main.eat

# Fixed — витрина lib/Fixed.eat (docs/plans/FIXED_POINT_PLAN.md):
# дроби Q16.16 без float; первый lib→lib импорт (Fixed → Fmt)
FIXED_MAIN = examples/fixed/Main.eat

# Компиляция всех примеров: парсинг, проверки Power of 10, типы,
# исполнение test-блоков
check:
	uv run python tests/check_style.py
	$(EATC) check $(EXAMPLES)
	$(EATC) check --lib . $(ELIF_MAIN)
	$(EATC) check --lib . $(JSON_MAIN)
	$(EATC) check --lib . $(FIXED_MAIN)
	$(EATC) check --lib . examples/blinky_cli/BlinkyCli.eat
	$(EATC) check --lib . examples/async/Async.eat
	$(EATC) check --lib . examples/async/Pipe.eat
	$(EATC) check --lib . examples/async/Debounce.eat
	$(EATC) check --lib . $(HTTP_ECHO_MAIN)
	$(EATC) check --lib . $(HTTP_HELLO_MAIN)
	$(EATC) check --lib . $(HTTP_POOL_MAIN)
	$(EATC) check --lib . $(HTTP_ROUTER_MAIN)

# Библиотека lib/ (docs/MODULES_PLAN.md §7, этап 0 — конкатенация):
# модули подключаются явным списком файлов после $(RT); LIB_FRONT —
# модули, нужные самому self-hosted фронтенду (Tok/Lexer/Parser/Check)
LIB_FRONT = lib/Const.eat lib/Ascii.eat lib/Buf.eat lib/Hex.eat

# Модульная программа: import-блоки, драйвер строит DAG и подставляет
# Rt.eat и lib/ сам (docs/MODULES_PLAN.md §4); --lib . — корень путей
MODULES_MAIN = examples/modules/Main.eat

run_modules:
	$(EATC) run --lib . $(MODULES_MAIN)

# Эмулятор MOS 6502 (examples/mos6502): все официальные опкоды,
# собственный тест-ROM в test-блоках; программа — байты со stdin
MOS6502_EXAMPLE = $(RT) lib/Hex.eat examples/mos6502/Cpu6502.eat \
	examples/mos6502/Tests.eat examples/mos6502/Main.eat

run_mos6502:
	cat examples/mos6502/mul13x11.rom | $(EATC) run $(MOS6502_EXAMPLE)

# Кооперативная асинхронность (docs/plans/ASYNC_PLAN.md): суперцикл
# в main на аксиомах in_avail()/ticks(); словарь идиомы — lib/Async.eat
# (ярус 1: Poll/Timer/Debounce), примеры собирает драйвер (--lib .).
# Async — две независимые задачи; Pipe — конвейер фильтров stdin с
# бюджетом на виток (кольца, backpressure); Debounce — витрина lib
# (кнопка с дребезгом + пульс). Сверка детерминирована: stdin — файл
# (in_avail = остаток до EOF), EAT_TICKS=virt — виртуальные часы
# (+1 на вызов ticks())
ASYNC_MAIN = examples/async/Async.eat
PIPE_MAIN = examples/async/Pipe.eat
DEBOUNCE_MAIN = examples/async/Debounce.eat

run_async:
	EAT_TICKS=virt $(EATC) run --lib . $(ASYNC_MAIN) < examples/async/input.txt

run_async_pipe:
	EAT_TICKS=virt $(EATC) run --lib . $(PIPE_MAIN) < examples/async/pipe_input.txt

run_async_debounce:
	EAT_TICKS=virt $(EATC) run --lib . $(DEBOUNCE_MAIN) < examples/async/debounce_input.txt

# HTTP-трек (docs/plans/HTTP_PLAN.md, этап 0): эхо-сервер на
# сокет-аксиомах SPEC §7. Сверка — записанный транскрипт соединений
# EAT_NET=<файл> (решение H2: события accept/data/close потребляются
# по порядку, вывод socket_write_span — в stdout тем же потоком, что
# write); живые сокеты — только make serve, ВНЕ гейта verify.
HTTP_ECHO_MAIN = examples/http/Echo.eat
HTTP_HELLO_MAIN = examples/http/Hello.eat
HTTP_POOL_MAIN = examples/http/Pool.eat
HTTP_ROUTER_MAIN = examples/http/Router.eat

run_http_echo:
	EAT_NET=examples/http/echo_net.txt $(EATC) run --lib . $(HTTP_ECHO_MAIN)

run_http_hello:
	EAT_NET=examples/http/hello_net.txt $(EATC) run --lib . $(HTTP_HELLO_MAIN)

# пул + keep-alive + idle-таймаут: Timer на виртуальных часах
run_http_pool:
	EAT_TICKS=virt EAT_NET=examples/http/pool_net.txt \
		$(EATC) run --lib . $(HTTP_POOL_MAIN)

# роутер: таблица маршрутов + параметры пути + HTML
run_http_router:
	EAT_NET=examples/http/router_net.txt $(EATC) run --lib . $(HTTP_ROUTER_MAIN)

# живой роутер: curl http://127.0.0.1:8080/greet/мир
serve_router:
	@$(EATC) build --lib . $(HTTP_ROUTER_MAIN) -o build/HttpRouter > /dev/null
	./build/HttpRouter $(PORT)

# Живой режим (вне гейта сверки): реальные неблокирующие сокеты.
# Порт — аргумент (решение H3): make serve PORT=9090; дефолт 8080.
# Проверка руками: printf 'привет' | nc 127.0.0.1 8080
serve:
	@$(EATC) build --lib . $(HTTP_ECHO_MAIN) -o build/HttpEcho > /dev/null
	./build/HttpEcho $(PORT)

# Живой Hello-сервер (этап 1): curl -i http://127.0.0.1:8080/
serve_hello:
	@$(EATC) build --lib . $(HTTP_HELLO_MAIN) -o build/HttpHello > /dev/null
	./build/HttpHello $(PORT)

# Проба self-host лексера: все кирпичи разом, вход — собственный исходник
LEXER_PROBE = $(RT) lib/Ascii.eat examples/lexer/LexUtil.eat examples/lexer/LexMain.eat

run_lexer_probe:
	cat examples/lexer/LexMain.eat | $(EATC) run $(LEXER_PROBE)

# Регрессионный набор верификатора (tests/verify/, docs/VERIFICATION_PLAN.md)
verify_suite:
	uv run python tests/verify_suite.py

# Ярус B comptime (§11 COMPTIME_PLAN): свёртка вызовов `build --fold`.
# Юнит — три исхода свёртки + паритет значения; e2e — бинарник с флагом
# и без == интерпретатор (наблюдаемое поведение неизменно, флаг вне гейта)
verify_fold:
	uv run python tests/fold/fold_test.py
	@$(EATC) build $(RT) tests/fold/Fold.eat -o build/FoldNo > /dev/null
	@$(EATC) build --fold $(RT) tests/fold/Fold.eat -o build/FoldYes > /dev/null
	@echo "" | $(EATC) run $(RT) tests/fold/Fold.eat > /tmp/eat_fold_interp.txt
	@./build/FoldNo > /tmp/eat_fold_no.txt
	@./build/FoldYes > /tmp/eat_fold_yes.txt
	@diff /tmp/eat_fold_interp.txt /tmp/eat_fold_no.txt \
		&& diff /tmp/eat_fold_interp.txt /tmp/eat_fold_yes.txt \
		&& echo "FOLD OK (build --fold == build == интерпретатор)" || exit 1

# Снапшот интерфейса lib/ (MODULES_PLAN §6): sig потока драйвера от
# пробы tests/sig/SigProbe.eat (Rt + все модули lib/) diff'ается с
# закоммиченным tests/sig/lib.sig — дрейф сигнатур/экспортов красный.
# Осознанное изменение интерфейса: make regen_sig и закоммитить diff.
verify_sig:
	@$(EATC) stream --lib . tests/sig/SigProbe.eat > /tmp/eat_sig_stream.eat
	@$(EATC) sig /tmp/eat_sig_stream.eat > /tmp/eat_sig_now.txt
	@diff tests/sig/lib.sig /tmp/eat_sig_now.txt \
		&& echo "SIG OK (интерфейс lib/ == снапшот)" \
		|| { echo "SIG DRIFT: интерфейс lib/ изменился — осознанно? make regen_sig"; exit 1; }

regen_sig:
	@$(EATC) stream --lib . tests/sig/SigProbe.eat > /tmp/eat_sig_stream.eat
	@$(EATC) sig /tmp/eat_sig_stream.eat > tests/sig/lib.sig
	@echo "tests/sig/lib.sig обновлён"

# Нагрузочное тестирование (tests/bench/): пайплайн компилятора на
# синтетических модулях, интерпретатор против бинарника, стресс лимитов
# SPEC.md §6, self-hosted лексер/парсер против Python-эталона,
# скорость компиляции компилятором самого себя (секция compiler).
bench:
	uv run python tests/bench/bench.py

bench_quick:
	uv run python tests/bench/bench.py --quick

# Кросс-языковое сравнение (tests/bench/crosslang/, план
# CROSSLANG_BENCH_PLAN): EATLang против C/Rust/Go/Python. Ручная цель,
# не гейт — требует clang, rustc и go на машине.
bench_crosslang:
	uv run python tests/bench/crosslang/run.py

# Self-hosted компилятор (selfhost/, docs/SELFHOST.md): дифференциальная
# сверка с эталоном на каждом .eat репозитория + интерпретатор == бинарник.
# Фаза 1 — лексер (`eatc lex`), фаза 2 — парсер (`eatc parse`),
# фаза 4 — эмиссия LLVM IR (`eatc ir`).
SELFHOST_LEXER = $(RT) $(LIB_FRONT) selfhost/Tok.eat selfhost/Lexer.eat \
	selfhost/LexMain.eat
SELFHOST_PARSER = $(RT) $(LIB_FRONT) selfhost/Tok.eat selfhost/Lexer.eat \
	selfhost/Ast.eat selfhost/Parser.eat selfhost/ParserExpr.eat selfhost/ParseMain.eat
SELFHOST_SIG = $(RT) $(LIB_FRONT) selfhost/Tok.eat selfhost/Lexer.eat \
	selfhost/Ast.eat selfhost/Parser.eat selfhost/ParserExpr.eat selfhost/Check.eat \
	selfhost/CheckConst.eat selfhost/CheckBody.eat selfhost/CheckDump.eat \
	selfhost/SigMain.eat
SELFHOST_TYPED = $(RT) $(LIB_FRONT) selfhost/Tok.eat selfhost/Lexer.eat \
	selfhost/Ast.eat selfhost/Parser.eat selfhost/ParserExpr.eat selfhost/Check.eat \
	selfhost/CheckConst.eat selfhost/CheckBody.eat selfhost/CheckDump.eat \
	selfhost/TypedMain.eat
SELFHOST_IR = $(RT) $(LIB_FRONT) lib/Fmt.eat selfhost/Tok.eat selfhost/Lexer.eat \
	selfhost/Ast.eat selfhost/Parser.eat selfhost/ParserExpr.eat selfhost/Check.eat \
	selfhost/CheckConst.eat selfhost/CheckBody.eat selfhost/CheckDump.eat \
	selfhost/Ir.eat selfhost/IrEmit.eat selfhost/IrExpr.eat selfhost/IrStmt.eat \
	selfhost/IrMain.eat
SELFHOST_IR_CODES = $(RT) $(LIB_FRONT) lib/Fmt.eat selfhost/Tok.eat \
	selfhost/Lexer.eat selfhost/Ast.eat selfhost/Parser.eat selfhost/ParserExpr.eat selfhost/Check.eat \
	selfhost/CheckConst.eat selfhost/CheckBody.eat selfhost/CheckDump.eat \
	selfhost/Ir.eat selfhost/IrEmit.eat selfhost/IrExpr.eat selfhost/IrStmt.eat \
	selfhost/IrCodesMain.eat
SELFHOST_IR_OPT = $(RT) $(LIB_FRONT) lib/Fmt.eat selfhost/Tok.eat \
	selfhost/Lexer.eat selfhost/Ast.eat selfhost/Parser.eat selfhost/ParserExpr.eat selfhost/Check.eat \
	selfhost/CheckConst.eat selfhost/CheckBody.eat selfhost/CheckDump.eat \
	selfhost/CheckFold.eat \
	selfhost/Verify.eat selfhost/VerifyExpr.eat selfhost/VerifyRel.eat \
	selfhost/VerifyFlow.eat selfhost/VerifyDump.eat \
	selfhost/Ir.eat selfhost/IrEmit.eat selfhost/IrExpr.eat selfhost/IrStmt.eat \
	selfhost/IrOptMain.eat
# Фаза 7 — статический верификатор (docs/SELFHOST_VERIFIER_PLAN.md).
# Зеркало verifier.py; вход как у `eatc verify` — одиночный .eat со stdin
# (без Rt/lib). Этап 1: интервальное ядро на курируемом списке кейсов.
# CheckFold — для `-O` (этап 5): ct_fold_pass перед verify по argv-флагу.
SELFHOST_VERIFY = $(RT) $(LIB_FRONT) selfhost/Tok.eat selfhost/Lexer.eat \
	selfhost/Ast.eat selfhost/Parser.eat selfhost/ParserExpr.eat selfhost/Check.eat \
	selfhost/CheckConst.eat selfhost/CheckBody.eat selfhost/CheckDump.eat \
	selfhost/CheckFold.eat \
	selfhost/Verify.eat selfhost/VerifyExpr.eat selfhost/VerifyRel.eat \
	selfhost/VerifyFlow.eat selfhost/VerifyDump.eat selfhost/VerifyMain.eat
# Курируемый список кейсов (растёт по мере покрытия, как verify_suite):
# этап 1 — bounds/overflow/div/cast/requires/ensures/assert.
VERIFY_GATE = 01_bounds_const_index 02_bounds_loop_var 03_bounds_requires \
	04_pool_append 05_prefix_scan 06_div_nonzero 07_max_relational \
	08_ensures_structural 09_countdown 10_accumulator 11_modular_const \
	12_modular_relation 13_off_by_one 14_len_capacity 15_neg_wrong_ensures \
	16_neg_loop_overflow 17_neg_unguarded_pool 18_cursor_subtraction \
	19_assign_relation \
	20_lockstep_counters 21_modular_arith_ensures \
	22_char_byte 23_enum_payload 24_byte_io \
	25_var_self_pool 26_bitwise_shift 27_break_for \
	28_write_span 29_write_span_guard 30_hex_bnot_interval \
	31_u16_cast 32_u64_cast 33_module_ensures_boundary \
	34_neg_module_mask_hidden 35_ctor_payload_bounds \
	36_neg_ctor_bounds 37_neg_ctor_context 38_neg_none_parens \
	39_pool_invariant_bounds 40_neg_pool_wide_store 41_pool_sentinel_hole \
	42_loop_hole_accumulator 43_neg_loop_hole_widened \
	44_comptime_const 45_neg_comptime_impure 46_neg_comptime_trap \
	47_neg_comptime_budget 48_neg_comptime_cycle 49_comptime_array \
	50_neg_comptime_array_trap 54_fold_call_point

# Полносоставные программы примеров (Rt + lib + модули) для гейта
# конкатенаций (FAULTS 2026-07-17: дрейф решений верификатора виден
# только в контексте вызовов — hex_digit; пофайловый вакуумный паритет
# файлов lib/ без main его не видит). Драйверные main'ы разворачивает
# `eatc stream --lib .`; mos6502 — явный список через запятую
# (конкатенация этапа 0). Воркер — tests/gate/verify_prog.sh.
VERIFY_PROGS = examples/if_statement/Elif.eat examples/json/Main.eat \
	examples/fixed/Main.eat examples/modules/Main.eat \
	examples/async/Async.eat examples/async/Pipe.eat \
	examples/async/Debounce.eat examples/http/Echo.eat \
	examples/http/Hello.eat examples/http/Pool.eat \
	examples/http/Router.eat examples/blinky_cli/BlinkyCli.eat \
	$(RT),lib/Hex.eat,examples/mos6502/Cpu6502.eat,examples/mos6502/Tests.eat,examples/mos6502/Main.eat

# Стек 128 МБ для бинарников, собираемых clang'ом из self-hosted IR
# (пулы компилятора живут в кадре main — как в src/eatc/codegen.py;
# кадр main самого self-hosted компилятора — ~85 МБ, фаза 5)
UNAME := $(shell uname)
ifeq ($(UNAME),Darwin)
STACK_FLAGS = -Wl,-stack_size,0x10000000
else
STACK_FLAGS = -Wl,-z,stacksize=268435456
endif

run_selfhost_lexer:
	cat $(SELFHOST_LEXER) | $(EATC) run $(SELFHOST_LEXER)

run_selfhost_parser:
	cat $(SELFHOST_PARSER) | $(EATC) run $(SELFHOST_PARSER)

run_selfhost_sig:
	cat $(SELFHOST_SIG) | $(EATC) run $(SELFHOST_SIG)

run_selfhost_ir:
	cat $(RT) examples/hello_world/HelloWorld.eat | $(EATC) run $(SELFHOST_IR)

verify_selfhost:
	@$(EATC) build $(SELFHOST_LEXER) -o build/SelfLex > /dev/null & p1=$$!; \
	$(EATC) build $(SELFHOST_PARSER) -o build/SelfParse > /dev/null & p2=$$!; \
	$(EATC) build $(SELFHOST_SIG) -o build/SelfSig > /dev/null & p3=$$!; \
	$(EATC) build $(SELFHOST_TYPED) -o build/SelfTyped > /dev/null & p4=$$!; \
	$(EATC) build $(SELFHOST_IR) -o build/SelfIr > /dev/null & p5=$$!; \
	wait $$p1 && wait $$p2 && wait $$p3 && wait $$p4 && wait $$p5
	@find examples lib selfhost tests -name '*.eat' | sort | \
		EATC='$(EATC)' RT='$(RT)' xargs -P $(JOBS) -n 1 sh tests/gate/selfhost_file.sh
	@EATC='$(EATC)' RT='$(RT)' STACK_FLAGS='$(STACK_FLAGS)' \
		SELFHOST_LEXER='$(SELFHOST_LEXER)' SELFHOST_PARSER='$(SELFHOST_PARSER)' \
		SELFHOST_SIG='$(SELFHOST_SIG)' SELFHOST_TYPED='$(SELFHOST_TYPED)' \
		SELFHOST_IR='$(SELFHOST_IR)' MODULES_MAIN='$(MODULES_MAIN)' \
		sh tests/gate/selfhost_tail.sh

# Фаза 5: bootstrap — self-hosted компилятор собирает сам себя.
# stage1 — build/SelfIr (собран Python-бутстрапом) эмитит IR собственных
# восьми модулей; сверка с `eatc ir` байт-в-байт. clang собирает из этого
# IR stage2 — и stage2 эмитит для тех же исходников тот же IR (фикспойнт).
verify_bootstrap:
	@$(EATC) build $(SELFHOST_IR) -o build/SelfIr > /dev/null
	@cat $(SELFHOST_IR) > /tmp/eat_boot_src.eat
	@$(EATC) ir /tmp/eat_boot_src.eat > /tmp/eat_boot_ref.ll
	@./build/SelfIr < /tmp/eat_boot_src.eat > /tmp/eat_boot_1.ll
	@diff /tmp/eat_boot_ref.ll /tmp/eat_boot_1.ll > /dev/null \
		&& echo "BOOT OK (stage1: IR самого компилятора == эталон eatc ir)" \
		|| { echo "BOOT DIFF stage1"; exit 1; }
	@clang /tmp/eat_boot_1.ll src/eatc/runtime.c -o build/SelfIr2 \
		$(STACK_FLAGS) 2>/dev/null
	@./build/SelfIr2 < /tmp/eat_boot_src.eat > /tmp/eat_boot_2.ll
	@diff /tmp/eat_boot_1.ll /tmp/eat_boot_2.ll > /dev/null \
		&& echo "BOOT OK (fixpoint: stage2 эмитит байт-в-байт тот же IR)" \
		|| { echo "BOOT DIFF fixpoint"; exit 1; }

# Режим trap-кодов (МК, метрика флеша): self-hosted эмиттер
# SelfIrCodes против эталона `eatc ir --trap-codes`, байт-в-байт
verify_trapcodes:
	@$(EATC) build $(SELFHOST_IR_CODES) -o build/SelfIrCodes > /dev/null
	@cat $(SELFHOST_IR) > /tmp/eat_tc_src.eat
	@$(EATC) ir --trap-codes /tmp/eat_tc_src.eat > /tmp/eat_tc_ref.ll
	@./build/SelfIrCodes < /tmp/eat_tc_src.eat > /tmp/eat_tc_self.ll
	@diff /tmp/eat_tc_ref.ll /tmp/eat_tc_self.ll > /dev/null \
		&& echo "TRAPCODES OK (IR режима кодов == эталон eatc ir --trap-codes)" \
		|| { echo "TRAPCODES DIFF"; exit 1; }

# Ось -O (SELFHOST_OPT_PLAN §11, SELFHOST_VERIFIER_PLAN этап 5):
# конвейер проходов fold → verify в self-hosted компиляторе — элизия
# доказанных проверок, nsw/nuw (llvm.assume снят по замеру
# OPTIMIZATIONS_PLAN §7.1). SelfIrOpt == эталон
# `eatc ir -O` байт-в-байт на входах со сворачиваемыми вызовами
# (D6: tests/fold + примеры), на кейсах верификатора (tests/verify —
# концентрат доказуемых обязательств) и на самоприменении (годность
# и элизия гоняются по всем вызовам фронтенда, §9).
verify_selfhost_opt:
	@$(EATC) build $(SELFHOST_IR_OPT) -o build/SelfIrOpt > /dev/null
	@{ echo tests/fold/Fold.eat; find examples tests/verify -name '*.eat' | sort; } | \
		EATC='$(EATC)' RT='$(RT)' xargs -P $(JOBS) -n 1 sh tests/gate/opt_file.sh
	@cat $(SELFHOST_TYPED) > /tmp/eat_iro_all.eat
	@$(EATC) ir -O /tmp/eat_iro_all.eat > /tmp/eat_iro_ref.ll
	@./build/SelfIrOpt < /tmp/eat_iro_all.eat > /tmp/eat_iro_self.ll
	@diff /tmp/eat_iro_ref.ll /tmp/eat_iro_self.ll > /dev/null \
		&& echo "IR-O OK (самоприменение: -O на всём фронтенде байт-в-байт)" \
		|| { echo "IR-O DIFF (самоприменение)"; exit 1; }
	@printf '%s\n' $(VERIFY_PROGS) | \
		EATC='$(EATC)' MODE=iropt xargs -P $(JOBS) -n 1 sh tests/gate/verify_prog.sh

# Фаза 7 — self-hosted верификатор (docs/SELFHOST_VERIFIER_PLAN.md,
# этап 1): SelfVerify == эталон `eatc verify` байт-в-байт на курируемом
# списке кейсов (дамп обязательств в стабильном порядке + футер).
verify_selfhost_verify:
	@$(EATC) build $(SELFHOST_VERIFY) -o build/SelfVerify > /dev/null
	@printf '%s\n' $(VERIFY_GATE) | \
		EATC='$(EATC)' xargs -P $(JOBS) -n 1 sh tests/gate/verify_case.sh

# Этап 4: полнорепный паритет дампа + самоприменение. Каждый .eat
# репозитория (вход `cat Rt.eat ФАЙЛ`, как IR-гейт; файлы без main —
# паритет отрицательного случая: оба дампа пусты) и главный тест —
# верификатор верифицирует сам себя (конкатенация Rt + lib + фронтенд +
# Verify + VerifyMain одним входом, 138K токенов, 8K обязательств).
# Этап 5 (решение Э2): каждый вход дополнительно сверяется под `-O`
# (fold перед verify) — множество решений элизии сверяется ДО сверки
# эмиссии (урок SELFHOST_OPT_PLAN §9).
verify_selfhost_verify_all:
	@$(EATC) build $(SELFHOST_VERIFY) -o build/SelfVerify > /dev/null
	@find examples lib selfhost tests -name '*.eat' | sort | \
		EATC='$(EATC)' RT='$(RT)' xargs -P $(JOBS) -n 1 sh tests/gate/verify_all_file.sh
	@cat $(SELFHOST_VERIFY) > /tmp/eat_vfy_selfapp.eat
	@$(EATC) verify /tmp/eat_vfy_selfapp.eat > /tmp/eat_vfy_ref.txt
	@./build/SelfVerify < /tmp/eat_vfy_selfapp.eat > /tmp/eat_vfy_self.txt
	@diff /tmp/eat_vfy_ref.txt /tmp/eat_vfy_self.txt > /dev/null \
		&& echo "VERIFY OK (самоприменение: верификатор верифицирует сам себя)" \
		|| { echo "VERIFY DIFF (самоприменение)"; exit 1; }
	@$(EATC) verify /tmp/eat_vfy_selfapp.eat -O > /tmp/eat_vfy_ref.txt
	@./build/SelfVerify -O < /tmp/eat_vfy_selfapp.eat > /tmp/eat_vfy_self.txt
	@diff /tmp/eat_vfy_ref.txt /tmp/eat_vfy_self.txt > /dev/null \
		&& echo "VERIFY-O OK (самоприменение под конвейером оси -O)" \
		|| { echo "VERIFY-O DIFF (самоприменение)"; exit 1; }
	@printf '%s\n' $(VERIFY_PROGS) | \
		EATC='$(EATC)' xargs -P $(JOBS) -n 1 sh tests/gate/verify_prog.sh

# ==== Трек 2 (МК): кросс-компиляция ARM Cortex-M ========================
# Структура портов (docs/MCU_PLAN.md §4): mcu/common/ — стартап,
# EABI-хелперы, шим аксиом поверх board_putc; mcu/boards/<board>/ —
# board.c (UART платы), board.ld (память), board.mk (--target, RAM,
# QEMU-машина или команда прошивки). Вход прошивается в образ
# (mcu/common/embed_input.py — у UART нет EOF), живой ввод — extern.
#
#   make mcu       BOARD=mps2_an385 SRC="selfhost/Rt.eat App.eat" \
#                  [EXTERN="drv.c"] [INPUT=data.bin]   # прошивка .elf
#   make mcu_run   BOARD=… SRC=…                       # запуск в QEMU
#
# Сборка печатает отчёт §8 и сверяет стек+данные с RAM платы
# (mcu/common/check_mem.py) — переполнение валит сборку. LTO — только
# на коде программы (−32 % флеша): биткодный шим lld выбрасывает
# __aeabi_* на разрешении символов. Тулчейн: brew install lld qemu.

.PHONY: mcu mcu_run mcu_flash verify_mcu verify_mcu_blinky \
	verify_mcu_cli verify_arm

BOARD ?= mps2_an385
include mcu/boards/$(BOARD)/board.mk
MCU_CC = clang $(ARCH_FLAGS) -O2 -ffreestanding -fno-unwind-tables \
	-Wno-override-module
MCU_QEMU = qemu-system-arm -M $(QEMU_MACHINE) -semihosting \
	-display none -monitor none -serial stdio
# llvm-objcopy для .bin/.hex прошивочных плат: в тулчейне Xcode его
# нет — берём из brew llvm (как lld)
MCU_OBJCOPY ?= $(shell brew --prefix llvm 2>/dev/null)/bin/llvm-objcopy
MCU_PROG = $(basename $(notdir $(lastword $(SRC))))
MCU_DIR = build/mcu/$(BOARD)
MCU_COMMON = mcu/common/runtime.c mcu/common/startup.c \
	mcu/common/eabi64.c mcu/common/shim.c
# все объекты прошивки: общий шим, board.c, BOARD_EXTRA платы (.c/.S,
# напр. boot2 у pico), прошитый вход и extern-драйверы проекта
MCU_OBJS = $(addprefix $(MCU_DIR)/,$(addsuffix .o,$(MCU_PROG) \
	$(basename $(notdir $(MCU_COMMON))) board input \
	$(basename $(notdir $(BOARD_EXTRA) $(EXTERN)))))

mcu:
	@test -n "$(SRC)" || { echo 'использование: make mcu BOARD=... SRC="Мод.eat Main.eat" [EXTERN=drv.c] [INPUT=file]'; exit 1; }
	@mkdir -p $(MCU_DIR)
	$(EATC) build --trap-codes --no-bin $(SRC) -o $(MCU_DIR)/$(MCU_PROG) \
		| tee $(MCU_DIR)/$(MCU_PROG).report
	@if [ -n "$(INPUT)" ]; then \
		uv run python mcu/common/embed_input.py $(INPUT) > $(MCU_DIR)/input.c; \
	else \
		uv run python mcu/common/embed_input.py /dev/null > $(MCU_DIR)/input.c; \
	fi
	$(MCU_CC) -flto -c $(MCU_DIR)/$(MCU_PROG).ll -o $(MCU_DIR)/$(MCU_PROG).o
	@for f in $(MCU_COMMON) mcu/boards/$(BOARD)/board.c $(BOARD_EXTRA) \
			$(MCU_DIR)/input.c $(EXTERN); do \
		o=$${f##*/}; \
		$(MCU_CC) -c $$f -o $(MCU_DIR)/$${o%.*}.o || exit 1; \
	done
	ld.lld -T mcu/boards/$(BOARD)/board.ld $(MCU_OBJS) \
		-o $(MCU_DIR)/$(MCU_PROG).elf
	@xcrun llvm-size $(MCU_DIR)/$(MCU_PROG).elf
	@uv run python mcu/common/check_mem.py $(MCU_DIR)/$(MCU_PROG).report \
		$(MCU_DIR)/$(MCU_PROG).elf $(RAM_SIZE)
	$(MCU_POST)

# Прошивка реальной платы: board.mk задаёт FLASH_CMD (st-flash,
# picotool, nrfjprog — см. mcu/README.md); у QEMU-плат её нет
mcu_flash: mcu
	@test -n "$(FLASH_CMD)" || { \
		echo "плата $(BOARD) — QEMU-цель, прошивать нечего"; exit 1; }
	$(FLASH_CMD)

mcu_run: mcu
	$(MCU_QEMU) -kernel $(MCU_DIR)/$(MCU_PROG).elf

# Сверка МК-сборок в QEMU (все платы mcu/boards/ c QEMU-машиной):
#   mos6502 (без extern) — вывод == интерпретатор; только mps2-an385:
#   в 16/8/128 КБ RAM остальных плат его 262 КБ стека не влезают —
#   это ровно то, что ловит автосверка §8;
#   extern-пример Blinky — вывод == хостовый бинарник с host_driver.c
#   (интерпретатор extern не исполняет — эталоном служит хост).
QEMU_BOARDS = mps2_an385 microbit stm32vldiscovery netduinoplus2
# прошивочные порты (§5 MCU_PLAN): QEMU-машины нет — в CI-воротах
# сборка прошивки + автосверка §8, проверка на железе — у пользователя
FLASH_BOARDS = pico bluepill f4discovery nrf52840dk
# флагманский пример §6: один исходник на все порты, граница — mcu/Mcu.eat
BLINKY_CLI_SRC = --lib . examples/blinky_cli/BlinkyCli.eat

verify_mcu:
	@$(MAKE) -s mcu BOARD=mps2_an385 SRC="$(MOS6502_EXAMPLE)" \
		INPUT=examples/mos6502/mul13x11.rom > /dev/null
	@cat examples/mos6502/mul13x11.rom | $(EATC) run $(MOS6502_EXAMPLE) \
		> /tmp/eat_interp.txt
	@qemu-system-arm -M mps2-an385 -semihosting -display none \
		-monitor none -serial stdio \
		-kernel build/mcu/mps2_an385/Main.elf > /tmp/eat_mcu.txt
	@diff /tmp/eat_interp.txt /tmp/eat_mcu.txt \
		&& echo "VERIFIED MCU Mos6502 (mps2_an385: QEMU == интерпретатор)" \
		|| exit 1
	@$(EATC) build --no-bin $(RT) examples/extern/Blinky.eat \
		-o build/Blinky > /dev/null
	@clang -O2 build/Blinky.ll src/eatc/runtime.c \
		examples/extern/host_driver.c -o build/Blinky \
		-Wno-override-module $(STACK_FLAGS)
	@./build/Blinky > /tmp/eat_host.txt
	@for b in $(QEMU_BOARDS); do \
		$(MAKE) -s verify_mcu_blinky BOARD=$$b || exit 1; \
	done
	@$(EATC) build --no-bin $(BLINKY_CLI_SRC) -o build/BlinkyCli > /dev/null
	@clang -O2 build/BlinkyCli.ll src/eatc/runtime.c \
		examples/blinky_cli/host_driver.c -o build/BlinkyCli \
		-Wno-override-module $(STACK_FLAGS)
	@./build/BlinkyCli < examples/blinky_cli/cmds.txt > /tmp/eat_cli_host.txt
	@for b in $(QEMU_BOARDS); do \
		$(MAKE) -s verify_mcu_cli BOARD=$$b || exit 1; \
	done
	@for b in $(FLASH_BOARDS); do \
		$(MAKE) -s mcu BOARD=$$b SRC="$(BLINKY_CLI_SRC)" > /dev/null \
			&& echo "BUILD OK blinky_cli ($$b: прошивка собрана, §8 в норме)" \
			|| exit 1; \
	done

# Один порт: Blinky в QEMU == хостовый эталон (вызывается verify_mcu)
verify_mcu_blinky:
	@$(MAKE) -s mcu BOARD=$(BOARD) SRC="$(RT) examples/extern/Blinky.eat" \
		EXTERN=examples/extern/mcu_driver.c > /dev/null
	@$(MCU_QEMU) -kernel $(MCU_DIR)/Blinky.elf > /tmp/eat_mcu.txt
	@diff /tmp/eat_host.txt /tmp/eat_mcu.txt \
		&& echo "VERIFIED MCU Blinky ($(BOARD): QEMU == хост, extern)" \
		|| exit 1

# Один порт: blinky_cli в QEMU == хостовый эталон (вызывается verify_mcu);
# команды идут в UART со stdin QEMU, вывод зависит только от них.
# sleep 1 — модель USART STM32 в QEMU роняет байты, пока гость не
# включил UART (CR1.UE|RE): вход подаётся после загрузки платы
verify_mcu_cli:
	@$(MAKE) -s mcu BOARD=$(BOARD) SRC="$(BLINKY_CLI_SRC)" > /dev/null
	@{ sleep 1; cat examples/blinky_cli/cmds.txt; } | \
		$(MCU_QEMU) -kernel $(MCU_DIR)/BlinkyCli.elf > /tmp/eat_cli_mcu.txt
	@diff /tmp/eat_cli_host.txt /tmp/eat_cli_mcu.txt \
		&& echo "VERIFIED MCU blinky_cli ($(BOARD): QEMU == хост, шим §6)" \
		|| exit 1

# Обратная совместимость с первым этапом трека 2
verify_arm: verify_mcu

# ==== Сборка языка и программ ===========================================
# Компилятор EATLang — фильтр stdin → stdout: получает конкатенацию
# модулей программы (рантайм-модуль $(RT) — первым) и печатает LLVM IR.
#
#   make eatc                                # язык из Python-бутстрапа
#   make eatc_self                           # язык, собранный самим собой
#   make compile SRC="Mod.eat Main.eat"      # .eat → build/Main.ll
#   make link    SRC="Mod.eat Main.eat"      # build/Main.ll → build/Main
#   make run     SRC="Mod.eat Main.eat"      # запустить build/Main
#   make binary  SRC="Mod.eat Main.eat"      # компиляция + линковка
#
# Имена артефактов — по последнему модулю (главному); переопределяются
# через LL=... и BIN=... Компилятор для compile — COMPILER=build/eatc
# (поменяйте на build/eatc-self, чтобы собирать компилятором,
# собранным самим собой — IR байт-в-байт тот же).

EATC_SOURCES = $(SELFHOST_IR) $(wildcard src/eatc/*.py) src/eatc/runtime.c

# Язык из Python: бутстрап собирает self-hosted компилятор
build/eatc: $(EATC_SOURCES)
	$(EATC) build $(SELFHOST_IR) -o build/eatc

eatc: build/eatc

# Язык из EAT: компилятор компилирует сам себя, clang линкует
build/eatc-self: build/eatc
	cat $(SELFHOST_IR) | ./build/eatc > build/eatc-self.ll
	clang -O2 build/eatc-self.ll src/eatc/runtime.c -o build/eatc-self \
		-Wno-override-module $(STACK_FLAGS)

eatc_self: build/eatc-self

COMPILER ?= build/eatc
PROG = $(basename $(notdir $(lastword $(SRC))))
LL ?= build/$(PROG).ll
BIN ?= build/$(PROG)

# Компиляция: модули программы → текстовый LLVM IR
compile: $(COMPILER)
	@test -n "$(SRC)" || { echo 'использование: make compile SRC="Мод1.eat Main.eat"'; exit 1; }
	@cat $(RT) $(SRC) | ./$(COMPILER) > $(LL) || { rm -f $(LL); exit 1; }
	@echo "$(LL)"

# Линковка: IR + шим аксиом ОС (runtime.c) [+ extern-драйверы
# проекта: EXTERN="drv.c"] → нативный бинарник
link:
	@test -f "$(LL)" || { echo "нет $(LL) — сначала make compile SRC=..."; exit 1; }
	@clang -O2 $(LL) src/eatc/runtime.c $(EXTERN) -o $(BIN) -Wno-override-module $(STACK_FLAGS)
	@echo "$(BIN)"

# Запуск слинкованной программы (stdin проходит насквозь)
run:
	@test -x "$(BIN)" || { echo "нет $(BIN) — сначала make binary SRC=..."; exit 1; }
	@./$(BIN)

# Бинарник из файлов: компиляция + линковка
binary: compile link

run_hello_world:
	$(EATC) run examples/hello_world/HelloWorld.eat

run_math:
	$(EATC) run examples/math/Math.eat

run_functions:
	$(EATC) run examples/functions/Functions.eat

run_if_statement:
	$(EATC) run examples/if_statement/IfStatement.eat

run_elif:
	$(EATC) run --lib . $(ELIF_MAIN)

run_json:
	$(EATC) run --lib . $(JSON_MAIN)

run_fixed:
	$(EATC) run --lib . $(FIXED_MAIN)

run_iterator:
	$(EATC) run examples/iterator/Iterator.eat

run_struct:
	$(EATC) run examples/struct/Struct.eat

run_alias:
	$(EATC) run examples/alias/Alias.eat

run_all:
	$(EATC) run examples/all/All.eat

# Нативные бинарники (LLVM → build/<Имя>)
build_all_examples:
	@printf '%s\n' $(EXAMPLES) | \
		EATC='$(EATC)' RT='$(RT)' xargs -P $(JOBS) -n 1 sh tests/gate/example_build.sh

# Сверка: вывод бинарника == вывод интерпретатора на каждом примере
verify: build_all_examples
	@printf '%s\n' $(EXAMPLES) | \
		EATC='$(EATC)' RT='$(RT)' xargs -P $(JOBS) -n 1 sh tests/gate/example_verify.sh
	@$(EATC) build --lib . $(ELIF_MAIN) -o build/Elif > /dev/null
	@echo "42" | $(EATC) run --lib . $(ELIF_MAIN) > /tmp/eat_interp.txt
	@echo "42" | ./build/Elif > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Elif" || exit 1
	@$(EATC) build --lib . $(MODULES_MAIN) -o build/Modules > /dev/null
	@$(EATC) run --lib . $(MODULES_MAIN) > /tmp/eat_interp.txt
	@./build/Modules > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Modules" || exit 1
	@$(EATC) build --lib . $(JSON_MAIN) -o build/Json > /dev/null
	@$(EATC) run --lib . $(JSON_MAIN) > /tmp/eat_interp.txt
	@./build/Json > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Json" || exit 1
	@$(EATC) build --lib . $(FIXED_MAIN) -o build/Fixed > /dev/null
	@$(EATC) run --lib . $(FIXED_MAIN) > /tmp/eat_interp.txt
	@./build/Fixed > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Fixed" || exit 1
	@$(EATC) build $(MOS6502_EXAMPLE) -o build/Mos6502 > /dev/null
	@cat examples/mos6502/mul13x11.rom | $(EATC) run $(MOS6502_EXAMPLE) > /tmp/eat_interp.txt
	@cat examples/mos6502/mul13x11.rom | ./build/Mos6502 > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Mos6502" || exit 1
	@$(EATC) build $(LEXER_PROBE) -o build/Lexer > /dev/null
	@cat examples/lexer/LexMain.eat | $(EATC) run $(LEXER_PROBE) > /tmp/eat_interp.txt
	@cat examples/lexer/LexMain.eat | ./build/Lexer > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED LexerProbe" || exit 1
	@$(EATC) build --lib . $(ASYNC_MAIN) -o build/Async > /dev/null
	@EAT_TICKS=virt $(EATC) run --lib . $(ASYNC_MAIN) < examples/async/input.txt > /tmp/eat_interp.txt
	@EAT_TICKS=virt ./build/Async < examples/async/input.txt > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Async" || exit 1
	@$(EATC) build --lib . $(PIPE_MAIN) -o build/Pipe > /dev/null
	@EAT_TICKS=virt $(EATC) run --lib . $(PIPE_MAIN) < examples/async/pipe_input.txt > /tmp/eat_interp.txt
	@EAT_TICKS=virt ./build/Pipe < examples/async/pipe_input.txt > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Pipe" || exit 1
	@$(EATC) build --lib . $(DEBOUNCE_MAIN) -o build/Debounce > /dev/null
	@EAT_TICKS=virt $(EATC) run --lib . $(DEBOUNCE_MAIN) < examples/async/debounce_input.txt > /tmp/eat_interp.txt
	@EAT_TICKS=virt ./build/Debounce < examples/async/debounce_input.txt > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Debounce" || exit 1
	@$(EATC) build --lib . $(HTTP_ECHO_MAIN) -o build/HttpEcho > /dev/null
	@EAT_NET=examples/http/echo_net.txt $(EATC) run --lib . $(HTTP_ECHO_MAIN) > /tmp/eat_interp.txt
	@EAT_NET=examples/http/echo_net.txt ./build/HttpEcho > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED HttpEcho" || exit 1
	@$(EATC) build --lib . $(HTTP_HELLO_MAIN) -o build/HttpHello > /dev/null
	@EAT_NET=examples/http/hello_net.txt $(EATC) run --lib . $(HTTP_HELLO_MAIN) > /tmp/eat_interp.txt
	@EAT_NET=examples/http/hello_net.txt ./build/HttpHello > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED HttpHello" || exit 1
	@$(EATC) build --lib . $(HTTP_POOL_MAIN) -o build/HttpPool > /dev/null
	@EAT_TICKS=virt EAT_NET=examples/http/pool_net.txt $(EATC) run --lib . $(HTTP_POOL_MAIN) > /tmp/eat_interp.txt
	@EAT_TICKS=virt EAT_NET=examples/http/pool_net.txt ./build/HttpPool > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED HttpPool" || exit 1
	@$(EATC) build --lib . $(HTTP_ROUTER_MAIN) -o build/HttpRouter > /dev/null
	@EAT_NET=examples/http/router_net.txt $(EATC) run --lib . $(HTTP_ROUTER_MAIN) > /tmp/eat_interp.txt
	@EAT_NET=examples/http/router_net.txt ./build/HttpRouter > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED HttpRouter" || exit 1
