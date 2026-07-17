# Порт tests/bench/programs/StrCmpBench.eat 1:1 — сборка строки
# f-строкой (префикс + десятичное число) и посимвольное сравнение ==
# с общим префиксом 40+ байт. Вывод обязан совпасть байт-в-байт
# с EATLang-оригиналом при том же REPEAT.

REPEAT = 1


def main():
    t = "common-prefix-the-quick-brown-fox-jumps-tail-00000"
    acc = 0
    for _ in range(REPEAT):
        for k in range(20):
            for i in range(1000):
                acc = (acc * 31 + i + k) % 65536
                s = f"common-prefix-the-quick-brown-fox-jumps-tail-{acc}"
                if s == t:
                    acc += 7
    print(f"checksum {acc}")


main()
