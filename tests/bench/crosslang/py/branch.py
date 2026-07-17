# Порт tests/bench/programs/BranchBench.eat 1:1 — непредсказуемые
# ветвления, if/elif-диспетчер по битам loop-carried acc. Вывод обязан
# совпасть байт-в-байт с EATLang-оригиналом при том же REPEAT.

REPEAT = 1


def work(seed):
    acc = seed + 1
    for _ in range(500):
        for i in range(1000):
            t = (acc >> (i & 7)) & 3
            if t == 0:
                acc = (acc + i + 1) % 65536
            elif t == 1:
                acc = (acc * 5 + 3) % 65536
            elif t == 2:
                acc = (acc ^ (i & 4095)) % 65536
            else:
                acc = ((acc >> 1) | 1) % 65536
    return acc


def main():
    acc = 7
    for _ in range(REPEAT):
        acc = work(acc)
    print(f"checksum {acc}")


main()
