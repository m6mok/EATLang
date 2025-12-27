gen:
	protoc --proto_path=proto --python_out=src/proto --pyi_out=src/proto proto/*.proto

check_program:
	uv run test_proto.py examples/functions/Functions.eat
	uv run test_proto.py examples/hello_world/HelloWorld.eat
	uv run test_proto.py examples/if_statement/IfStatement.eat
	uv run test_proto.py examples/iterator/Iterator.eat
	uv run test_proto.py examples/math/Math.eat
	uv run test_proto.py examples/struct/Struct.eat

run_hello_world:
	uv run src/run.py --log-level=3 examples/hello_world/HelloWorld.eat

run_if_statement:
	uv run src/run.py --log-level=3 examples/if_statement/IfStatement.eat

run_elif:
	uv run src/run.py --log-level=3 examples/if_statement/Elif.eat
