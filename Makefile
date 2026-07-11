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
