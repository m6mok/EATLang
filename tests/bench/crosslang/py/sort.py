# Порт tests/bench/programs/SortBench.eat 1:1 — сортировка вставками
# с data-dependent ветвлениями и взвешенной свёрткой результата.
# Вывод обязан совпасть байт-в-байт с EATLang-оригиналом при том же
# REPEAT.

REPEAT = 1


def fill(seed, k):
    return (seed * 31 + k + 1) % 65536


def main():
    a = [0] * 32
    acc = 7
    for _ in range(REPEAT):
        for _ in range(500):
            for i in range(32):
                acc = fill(acc, i)
                a[i] = acc
            for i in range(1, 32):
                v = a[i]
                j = i
                for _ in range(32):
                    move = False
                    if j > 0:
                        if a[j - 1] > v:
                            move = True
                    if move:
                        a[j] = a[j - 1]
                        j = j - 1
                    else:
                        break
                a[j] = v
            for i in range(32):
                acc = (acc * 3 + a[i]) % 65536
    print(f"checksum {acc}")


main()
