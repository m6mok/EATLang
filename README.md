# EATLang

## Описание

- Компилируемый

- Статически типизируемый

- Пишется в формате [Protobuf Text Format Language Specification](https://protobuf.dev/reference/protobuf/textformat-spec)

- Использует статически инициализируемые переменные на самом высоком уровне из возможных

- Архитектурно задуманный так, чтобы любое ветвление или цикл вызывали какую-либо функцию. Либо для ветвлений есть возможность вернуть значение из функции

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

## Порядок вызовов блоков

1. `commence` - вывод в stdout до тела блока

2. `set` - операции с переменными

3. `while`, `if`, `until`, `call` - вызов тела блока

4. `else` - вызов исключения после работы тела. Если нет тела, ничего не делает

5. `ret`, `alias` - возвращает значение. `ret` возвращает возвращает значение переменной, `alias` возвращает результат вызываемой ею функции

6. `conclude` - вывод в stdout после тела блока
