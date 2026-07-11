# EATLang — собственный синтаксис, см. SPEC.md
# Компилятор в разработке: src/eatc/ (Python bootstrap → llvmlite → LLVM IR)

EXAMPLES = \
	examples/hello_world/HelloWorld.eat \
	examples/math/Math.eat \
	examples/functions/Functions.eat \
	examples/if_statement/IfStatement.eat \
	examples/if_statement/Elif.eat \
	examples/iterator/Iterator.eat \
	examples/struct/Struct.eat \
	examples/all/All.eat

# Приёмочная проверка: все эталонные примеры парсятся и проходят
# структурные проверки Power of 10
check:
	PYTHONPATH=src uv run python -m eatc check $(EXAMPLES)
