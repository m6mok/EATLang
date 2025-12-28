gen:
	protoc --proto_path=proto --python_out=src/proto --pyi_out=src/proto proto/*.proto

check_program:
	uv run src/test_proto.py examples/functions/Functions.eat
	uv run src/test_proto.py examples/hello_world/HelloWorld.eat
	uv run src/test_proto.py examples/if_statement/IfStatement.eat
	uv run src/test_proto.py examples/iterator/Iterator.eat
	uv run src/test_proto.py examples/math/Math.eat
	uv run src/test_proto.py examples/struct/Struct.eat

run_hello_world:
	uv run src/run.py --log-level=3 examples/hello_world/HelloWorld.eat

run_if_statement:
	uv run src/run.py --log-level=3 examples/if_statement/IfStatement.eat

run_elif:
	uv run src/run.py --log-level=3 examples/if_statement/Elif.eat

run_iterator:
	uv run src/run.py --log-level=3 examples/iterator/Iterator.eat

run_functions:
	uv run src/run.py --log-level=3 examples/functions/Functions.eat

run_all:
	uv run src/run.py --log-level=3 examples/all/All.eat

run_math:
	uv run src/run.py --log-level=3 examples/math/Math.eat
