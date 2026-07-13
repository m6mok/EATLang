# EATLang — собственный синтаксис, см. SPEC.md
# Компилятор: src/eatc/ (Python bootstrap; впереди — llvmlite → LLVM IR)

EATC = PYTHONPATH=src uv run python -m eatc

# Рантайм-модуль (фаза 6): логика строк/вывода/разбора — на EATLang,
# первый модуль каждой программы; в C остался шим аксиом ОС (runtime.c)
RT = selfhost/Rt.eat

EXAMPLES = \
	examples/hello_world/HelloWorld.eat \
	examples/math/Math.eat \
	examples/functions/Functions.eat \
	examples/if_statement/IfStatement.eat \
	examples/if_statement/Elif.eat \
	examples/iterator/Iterator.eat \
	examples/struct/Struct.eat \
	examples/alias/Alias.eat \
	examples/all/All.eat

# Компиляция всех примеров: парсинг, проверки Power of 10, типы,
# исполнение test-блоков
check:
	$(EATC) check $(EXAMPLES)

# Модульная программа: несколько файлов, последний — главный
MODULES_EXAMPLE = $(RT) examples/modules/ByteUtil.eat examples/modules/Main.eat

run_modules:
	$(EATC) run $(MODULES_EXAMPLE)

# Эмулятор MOS 6502 (examples/mos6502): все официальные опкоды,
# собственный тест-ROM в test-блоках; программа — байты со stdin
MOS6502_EXAMPLE = $(RT) examples/mos6502/Cpu6502.eat \
	examples/mos6502/Tests.eat examples/mos6502/Main.eat

run_mos6502:
	cat examples/mos6502/mul13x11.rom | $(EATC) run $(MOS6502_EXAMPLE)

# Проба self-host лексера: все кирпичи разом, вход — собственный исходник
LEXER_PROBE = $(RT) examples/lexer/LexUtil.eat examples/lexer/LexMain.eat

run_lexer_probe:
	cat examples/lexer/LexMain.eat | $(EATC) run $(LEXER_PROBE)

# Регрессионный набор верификатора (tests/verify/, docs/VERIFICATION_PLAN.md)
verify_suite:
	uv run python tests/verify_suite.py

# Нагрузочное тестирование (tests/bench/): пайплайн компилятора на
# синтетических модулях, интерпретатор против бинарника, стресс лимитов
# SPEC.md §6, self-hosted лексер/парсер против Python-эталона,
# скорость компиляции компилятором самого себя (секция compiler).
bench:
	uv run python tests/bench/bench.py

bench_quick:
	uv run python tests/bench/bench.py --quick

# Self-hosted компилятор (selfhost/, docs/SELFHOST.md): дифференциальная
# сверка с эталоном на каждом .eat репозитория + интерпретатор == бинарник.
# Фаза 1 — лексер (`eatc lex`), фаза 2 — парсер (`eatc parse`),
# фаза 4 — эмиссия LLVM IR (`eatc ir`).
SELFHOST_LEXER = $(RT) selfhost/Tok.eat selfhost/Lexer.eat selfhost/LexMain.eat
SELFHOST_PARSER = $(RT) selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/ParseMain.eat
SELFHOST_SIG = $(RT) selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/Check.eat selfhost/SigMain.eat
SELFHOST_TYPED = $(RT) selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/Check.eat selfhost/TypedMain.eat
SELFHOST_IR = $(RT) selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/Check.eat selfhost/Ir.eat selfhost/IrMain.eat
SELFHOST_IR_CODES = $(RT) selfhost/Tok.eat selfhost/Lexer.eat \
	selfhost/Ast.eat selfhost/Parser.eat selfhost/Check.eat \
	selfhost/Ir.eat selfhost/IrCodesMain.eat

# Стек 128 МБ для бинарников, собираемых clang'ом из self-hosted IR
# (пулы компилятора живут в кадре main — как в src/eatc/codegen.py;
# кадр main самого self-hosted компилятора — ~85 МБ, фаза 5)
UNAME := $(shell uname)
ifeq ($(UNAME),Darwin)
STACK_FLAGS = -Wl,-stack_size,0x8000000
else
STACK_FLAGS = -Wl,-z,stacksize=134217728
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
	@$(EATC) build $(SELFHOST_LEXER) -o build/SelfLex > /dev/null
	@$(EATC) build $(SELFHOST_PARSER) -o build/SelfParse > /dev/null
	@$(EATC) build $(SELFHOST_SIG) -o build/SelfSig > /dev/null
	@$(EATC) build $(SELFHOST_TYPED) -o build/SelfTyped > /dev/null
	@$(EATC) build $(SELFHOST_IR) -o build/SelfIr > /dev/null
	@for f in $$(find examples selfhost tests -name '*.eat' | sort); do \
		$(EATC) lex $$f > /tmp/eat_lex_ref.txt; \
		./build/SelfLex < $$f > /tmp/eat_lex_self.txt; \
		diff /tmp/eat_lex_ref.txt /tmp/eat_lex_self.txt > /dev/null \
			&& echo "LEX OK $$f" \
			|| { echo "LEX DIFF $$f"; exit 1; }; \
		if $(EATC) parse $$f > /tmp/eat_parse_ref.txt 2>/dev/null; then \
			./build/SelfParse < $$f > /tmp/eat_parse_self.txt; \
			diff /tmp/eat_parse_ref.txt /tmp/eat_parse_self.txt > /dev/null \
				&& echo "PARSE OK $$f" \
				|| { echo "PARSE DIFF $$f"; exit 1; }; \
		fi; \
		if $(EATC) sig $$f > /tmp/eat_sig_ref.txt 2>/dev/null; then \
			./build/SelfSig < $$f > /tmp/eat_sig_self.txt; \
			diff /tmp/eat_sig_ref.txt /tmp/eat_sig_self.txt > /dev/null \
				&& echo "SIG OK $$f" \
				|| { echo "SIG DIFF $$f"; exit 1; }; \
		fi; \
		if $(EATC) typed $$f > /tmp/eat_typed_ref.txt 2>/dev/null; then \
			./build/SelfTyped < $$f > /tmp/eat_typed_self.txt; \
			diff /tmp/eat_typed_ref.txt /tmp/eat_typed_self.txt > /dev/null \
				&& echo "TYPED OK $$f" \
				|| { echo "TYPED DIFF $$f"; exit 1; }; \
		fi; \
		cat $(RT) $$f > /tmp/eat_ir_in.eat; \
		if $(EATC) ir /tmp/eat_ir_in.eat > /tmp/eat_ir_ref.ll 2>/dev/null; then \
			./build/SelfIr < /tmp/eat_ir_in.eat > /tmp/eat_ir_self.ll; \
			diff /tmp/eat_ir_ref.ll /tmp/eat_ir_self.ll > /dev/null \
				&& echo "IR OK $$f" \
				|| { echo "IR DIFF $$f"; exit 1; }; \
		fi; \
	done
	@cat $(SELFHOST_SIG) > /tmp/eat_sig_all.eat
	@$(EATC) sig /tmp/eat_sig_all.eat > /tmp/eat_sig_ref.txt
	@./build/SelfSig < /tmp/eat_sig_all.eat > /tmp/eat_sig_self.txt
	@diff /tmp/eat_sig_ref.txt /tmp/eat_sig_self.txt > /dev/null \
		&& echo "SIG OK (конкатенация собственных исходников)" || exit 1
	@cat $(SELFHOST_TYPED) > /tmp/eat_typed_all.eat
	@$(EATC) typed /tmp/eat_typed_all.eat > /tmp/eat_typed_ref.txt
	@./build/SelfTyped < /tmp/eat_typed_all.eat > /tmp/eat_typed_self.txt
	@diff /tmp/eat_typed_ref.txt /tmp/eat_typed_self.txt > /dev/null \
		&& echo "TYPED OK (тайпчекер типизирует сам себя)" || exit 1
	@cat $(SELFHOST_LEXER) | $(EATC) run $(SELFHOST_LEXER) > /tmp/eat_lex_interp.txt
	@cat $(SELFHOST_LEXER) | ./build/SelfLex > /tmp/eat_lex_native.txt
	@diff /tmp/eat_lex_interp.txt /tmp/eat_lex_native.txt \
		&& echo "VERIFIED SelfLex (interp == native == эталон)" || exit 1
	@cat $(SELFHOST_PARSER) | $(EATC) run $(SELFHOST_PARSER) > /tmp/eat_parse_interp.txt
	@cat $(SELFHOST_PARSER) | ./build/SelfParse > /tmp/eat_parse_native.txt
	@diff /tmp/eat_parse_interp.txt /tmp/eat_parse_native.txt \
		&& echo "VERIFIED SelfParse (interp == native == эталон)" || exit 1
	@cat $(SELFHOST_SIG) | $(EATC) run $(SELFHOST_SIG) > /tmp/eat_sig_interp.txt
	@cat $(SELFHOST_SIG) | ./build/SelfSig > /tmp/eat_sig_native.txt
	@diff /tmp/eat_sig_interp.txt /tmp/eat_sig_native.txt \
		&& echo "VERIFIED SelfSig (interp == native == эталон)" || exit 1
	@cat examples/lexer/LexUtil.eat examples/lexer/LexMain.eat > /tmp/eat_typed_probe.eat
	@cat /tmp/eat_typed_probe.eat | $(EATC) run $(SELFHOST_TYPED) > /tmp/eat_typed_interp.txt
	@cat /tmp/eat_typed_probe.eat | ./build/SelfTyped > /tmp/eat_typed_native.txt
	@diff /tmp/eat_typed_interp.txt /tmp/eat_typed_native.txt \
		&& echo "VERIFIED SelfTyped (interp == native, проба лексера)" || exit 1
	@$(EATC) ir /tmp/eat_typed_all.eat > /tmp/eat_ir_ref.ll
	@./build/SelfIr < /tmp/eat_typed_all.eat > /tmp/eat_ir_self.ll
	@diff /tmp/eat_ir_ref.ll /tmp/eat_ir_self.ll > /dev/null \
		&& echo "IR OK (самоприменение: IR всего фронтенда байт-в-байт)" || exit 1
	@clang /tmp/eat_ir_self.ll src/eatc/runtime.c -o /tmp/eat_ir_typed_bin \
		$(STACK_FLAGS) 2>/dev/null
	@/tmp/eat_ir_typed_bin < /tmp/eat_typed_probe.eat > /tmp/eat_ir_e2e.txt
	@$(EATC) typed /tmp/eat_typed_probe.eat > /tmp/eat_typed_ref.txt
	@diff /tmp/eat_typed_ref.txt /tmp/eat_ir_e2e.txt \
		&& echo "VERIFIED SelfIr (тайпчекер, собранный clang из self-IR, == эталон)" \
		|| exit 1
	@cat $(RT) examples/hello_world/HelloWorld.eat | $(EATC) run $(SELFHOST_IR) > /tmp/eat_ir_interp.txt
	@cat $(RT) examples/hello_world/HelloWorld.eat | ./build/SelfIr > /tmp/eat_ir_native.txt
	@diff /tmp/eat_ir_interp.txt /tmp/eat_ir_native.txt \
		&& echo "VERIFIED SelfIr (interp == native)" || exit 1

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

# ==== Трек 2 (МК): кросс-компиляция ARM Cortex-M3 ======================
# Канонический .ll платформонезависим — clang перекладывает его под
# thumbv7m-none-eabi, ld.lld собирает ELF для платы QEMU mps2-an385
# (mcu/mps2_an385.ld). Аксиомы ОС — mcu/runtime_mcu.c: вывод в CMSDK
# UART0, вход прошит в образ (mcu/embed_input.py — у UART нет EOF),
# exit/trap — полухостинг. Тулчейн: brew install lld qemu.
#
# LTO — только для кода программы (-flto на .ll, −32 % флеша,
# линковка мгновенная): шим остаётся нативным объектом, иначе lld
# выбрасывает __aeabi_*-хелперы на разрешении символов — ссылки
# на них появляются лишь при LTO-кодогенерации.

ARM_CC = clang --target=thumbv7m-none-eabi -mcpu=cortex-m3 -O2 \
	-ffreestanding -fno-unwind-tables -Wno-override-module
ARM_QEMU = qemu-system-arm -M mps2-an385 -semihosting -display none \
	-monitor none -serial stdio

ARM_MCU_DEPS = mcu/runtime_mcu.c mcu/mps2_an385.ld mcu/embed_input.py

build/arm/Mos6502.elf: $(MOS6502_EXAMPLE) $(ARM_MCU_DEPS) \
		examples/mos6502/mul13x11.rom
	@mkdir -p build/arm
	$(EATC) build --trap-codes $(MOS6502_EXAMPLE) -o build/arm/Mos6502
	uv run python mcu/embed_input.py examples/mos6502/mul13x11.rom \
		> build/arm/rom_input.c
	$(ARM_CC) -flto -c build/arm/Mos6502.ll -o build/arm/Mos6502.o
	$(ARM_CC) -c mcu/runtime_mcu.c -o build/arm/runtime_mcu.o
	$(ARM_CC) -c build/arm/rom_input.c -o build/arm/rom_input.o
	ld.lld -T mcu/mps2_an385.ld build/arm/Mos6502.o \
		build/arm/runtime_mcu.o build/arm/rom_input.o \
		-o build/arm/Mos6502.elf
	@xcrun llvm-size build/arm/Mos6502.elf

arm_mos6502: build/arm/Mos6502.elf

run_arm_mos6502: build/arm/Mos6502.elf
	$(ARM_QEMU) -kernel build/arm/Mos6502.elf

# Сверка кросс-сборки: вывод программы в QEMU (UART -> stdout)
# байт-в-байт равен интерпретатору и нативному бинарнику хоста
verify_arm: build/arm/Mos6502.elf
	@cat examples/mos6502/mul13x11.rom | $(EATC) run $(MOS6502_EXAMPLE) \
		> /tmp/eat_interp.txt
	@$(ARM_QEMU) -kernel build/arm/Mos6502.elf > /tmp/eat_arm.txt
	@diff /tmp/eat_interp.txt /tmp/eat_arm.txt \
		&& echo "VERIFIED ARM Mos6502 (QEMU mps2-an385 == интерпретатор)" \
		|| exit 1

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

# Линковка: IR + шим аксиом ОС (runtime.c) → нативный бинарник
link:
	@test -f "$(LL)" || { echo "нет $(LL) — сначала make compile SRC=..."; exit 1; }
	@clang -O2 $(LL) src/eatc/runtime.c -o $(BIN) -Wno-override-module $(STACK_FLAGS)
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
	$(EATC) run examples/if_statement/Elif.eat

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
	@for f in $(EXAMPLES); do $(EATC) build $(RT) $$f || exit 1; done

# Сверка: вывод бинарника == вывод интерпретатора на каждом примере
verify: build_all_examples
	@for f in $(EXAMPLES); do \
		name=$$(basename $$f .eat); \
		case $$name in Elif) input="42"; ;; *) input=""; ;; esac; \
		echo "$$input" | $(EATC) run $(RT) $$f > /tmp/eat_interp.txt; \
		echo "$$input" | ./build/$$name > /tmp/eat_native.txt; \
		diff /tmp/eat_interp.txt /tmp/eat_native.txt \
			&& echo "VERIFIED $$name" || exit 1; \
	done
	@$(EATC) build $(MODULES_EXAMPLE) -o build/Modules > /dev/null
	@$(EATC) run $(MODULES_EXAMPLE) > /tmp/eat_interp.txt
	@./build/Modules > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Modules" || exit 1
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
