# Порт tests/bench/programs/ArithBench.eat 1:1 — целочисленная
# арифметика в горячем цикле. Вывод обязан совпасть байт-в-байт
# с EATLang-оригиналом при том же REPEAT.

REPEAT = 1


def work(seed):
    acc = seed
    for _ in range(1000):
        for i in range(1000):
            acc = (acc * 31 + i) % 65536
    return acc


def main():
    acc = 7
    for _ in range(REPEAT):
        acc = work(acc) % 65536
    print(f"checksum {acc}")


main()
