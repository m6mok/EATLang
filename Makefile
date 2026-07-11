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
# Фаза 1 — лексер (`eatc lex`), фаза 2 — парсер (`eatc parse`).
SELFHOST_LEXER = selfhost/Tok.eat selfhost/Lexer.eat selfhost/LexMain.eat
SELFHOST_PARSER = selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/ParseMain.eat
SELFHOST_SIG = selfhost/Tok.eat selfhost/Lexer.eat selfhost/Ast.eat \
	selfhost/Parser.eat selfhost/Check.eat selfhost/SigMain.eat

run_selfhost_lexer:
	cat $(SELFHOST_LEXER) | $(EATC) run $(SELFHOST_LEXER)

run_selfhost_parser:
	cat $(SELFHOST_PARSER) | $(EATC) run $(SELFHOST_PARSER)

run_selfhost_sig:
	cat $(SELFHOST_SIG) | $(EATC) run $(SELFHOST_SIG)

verify_selfhost:
	@$(EATC) build $(SELFHOST_LEXER) -o build/SelfLex > /dev/null
	@$(EATC) build $(SELFHOST_PARSER) -o build/SelfParse > /dev/null
	@$(EATC) build $(SELFHOST_SIG) -o build/SelfSig > /dev/null
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
	done
	@cat $(SELFHOST_SIG) > /tmp/eat_sig_all.eat
	@$(EATC) sig /tmp/eat_sig_all.eat > /tmp/eat_sig_ref.txt
	@./build/SelfSig < /tmp/eat_sig_all.eat > /tmp/eat_sig_self.txt
	@diff /tmp/eat_sig_ref.txt /tmp/eat_sig_self.txt > /dev/null \
		&& echo "SIG OK (конкатенация собственных исходников)" || exit 1
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
