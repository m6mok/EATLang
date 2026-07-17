# Порт tests/bench/programs/BankBench.eat 1:1 — банкованная память
# pool[a/4096][a%4096], адрес зависит от loop-carried acc. Вывод
# обязан совпасть байт-в-байт с EATLang-оригиналом при том же REPEAT.

REPEAT = 1


def work(seed):
    pool = [[0] * 4096 for _ in range(8)]
    acc = seed
    for _ in range(200):
        for i in range(1000):
            a = (acc + i * 37) % 32768
            pool[a // 4096][a % 4096] = (acc + i) % 65536
            b = (a * 17 + 5) % 32768
            acc = (acc + pool[b // 4096][b % 4096]) % 65536
    return acc


def main():
    acc = 7
    for _ in range(REPEAT):
        acc = work(acc)
    print(f"checksum {acc}")


main()
