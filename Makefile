# EATLang — собственный синтаксис, см. SPEC.md
# Компилятор: src/eatc/ (Python bootstrap; впереди — llvmlite → LLVM IR)

EATC = PYTHONPATH=src uv run python -m eatc

EXAMPLES = \
	examples/hello_world/HelloWorld.eat \
	examples/math/Math.eat \
	examples/functions/Functions.eat \
	examples/if_statement/IfStatement.eat \
	examples/if_statement/Elif.eat \
	examples/iterator/Iterator.eat \
	examples/struct/Struct.eat \
	examples/all/All.eat

# Компиляция всех примеров: парсинг, проверки Power of 10, типы,
# исполнение test-блоков
check:
	$(EATC) check $(EXAMPLES)

# Модульная программа: несколько файлов, последний — главный
MODULES_EXAMPLE = examples/modules/ByteUtil.eat examples/modules/Main.eat

run_modules:
	$(EATC) run $(MODULES_EXAMPLE)

# Проба self-host лексера: все кирпичи разом, вход — собственный исходник
LEXER_PROBE = examples/lexer/LexUtil.eat examples/lexer/LexMain.eat

run_lexer_probe:
	cat examples/lexer/LexMain.eat | $(EATC) run $(LEXER_PROBE)

# Регрессионный набор верификатора (tests/verify/, docs/VERIFICATION_PLAN.md)
verify_suite:
	uv run python tests/verify_suite.py

# Self-hosted компилятор (selfhost/, docs/SELFHOST.md): дифференциальная
# сверка с эталоном на каждом .eat репозитория + интерпретатор == бинарник.
# Фаза 1 — лексер (`eatc lex`), фаза 2 — парсер (`eatc parse`),
# фаза 4 — эмиссия LLVM IR (`eatc ir`).
SELFHOST_LEXER = selfhost/Tok.eat selfhost/Lexer.eat selfhost/LexMain.eat
SELFHOST_PARSER = selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/ParseMain.eat
SELFHOST_SIG = selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/Check.eat selfhost/SigMain.eat
SELFHOST_TYPED = selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/Check.eat selfhost/TypedMain.eat
SELFHOST_IR = selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/Check.eat selfhost/Ir.eat selfhost/IrMain.eat

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
	cat examples/hello_world/HelloWorld.eat | $(EATC) run $(SELFHOST_IR)

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
		if $(EATC) ir $$f > /tmp/eat_ir_ref.ll 2>/dev/null; then \
			./build/SelfIr < $$f > /tmp/eat_ir_self.ll; \
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
	@cat examples/hello_world/HelloWorld.eat | $(EATC) run $(SELFHOST_IR) > /tmp/eat_ir_interp.txt
	@cat examples/hello_world/HelloWorld.eat | ./build/SelfIr > /tmp/eat_ir_native.txt
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

run_all:
	$(EATC) run examples/all/All.eat

# Нативные бинарники (LLVM → build/<Имя>)
build_all_examples:
	@for f in $(EXAMPLES); do $(EATC) build $$f || exit 1; done

# Сверка: вывод бинарника == вывод интерпретатора на каждом примере
verify: build_all_examples
	@for f in $(EXAMPLES); do \
		name=$$(basename $$f .eat); \
		case $$name in Elif) input="42"; ;; *) input=""; ;; esac; \
		echo "$$input" | $(EATC) run $$f > /tmp/eat_interp.txt; \
		echo "$$input" | ./build/$$name > /tmp/eat_native.txt; \
		diff /tmp/eat_interp.txt /tmp/eat_native.txt \
			&& echo "VERIFIED $$name" || exit 1; \
	done
	@$(EATC) build $(MODULES_EXAMPLE) -o build/Modules > /dev/null
	@$(EATC) run $(MODULES_EXAMPLE) > /tmp/eat_interp.txt
	@./build/Modules > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED Modules" || exit 1
	@$(EATC) build $(LEXER_PROBE) -o build/Lexer > /dev/null
	@cat examples/lexer/LexMain.eat | $(EATC) run $(LEXER_PROBE) > /tmp/eat_interp.txt
	@cat examples/lexer/LexMain.eat | ./build/Lexer > /tmp/eat_native.txt
	@diff /tmp/eat_interp.txt /tmp/eat_native.txt \
		&& echo "VERIFIED LexerProbe" || exit 1
