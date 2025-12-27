# EATLang

## Требования к запуску

1. `protobuf`

    ```sh
    apt install -y protobuf-compiler
    ```

2. `uv`

    ```sh
    wget -qO- https://astral.sh/uv/install.sh | sh
    ```

3. *`make`

    ```sh
    apt install build-essential
    ```

## Запуск

1. Установка виртуального окружения

    ```sh
    uv sync
    ```

2. Кодген proto файла

    ```sh
    make gen
    ```

3. Запуск программы

    ```sh
    make run_hello_world
    ```

4. *Для простой проверки парсинга файла

    ```sh
    uv run src/test_proto.py examples/hello_world/HelloWorld.eat
    ```

## Порядок вызовов

1. `commence`

2. `set`

3. `while`, `if`, `until`, `call`

4. `else`

5. `ret`, `alias`

6. `conclude`
