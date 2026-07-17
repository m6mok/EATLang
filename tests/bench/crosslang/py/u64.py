# Порт tests/bench/programs/U64Bench.eat 1:1 — 64-битная беззнаковая
# арифметика, деление, широкие сдвиги. Вывод обязан совпасть байт-в-байт
# с EATLang-оригиналом при том же REPEAT. Python: int неограничен —
# результаты, семантически являющиеся u64 (сдвиги, xor), маскируем по
# модулю 2**64 (в этом бенче acc и так остаётся < 2**48 из-за деления
# по модулю, но маска — явная страховка семантики, а не расчёт на неё).

REPEAT = 1

MASK64 = (1 << 64) - 1


def work(seed):
    acc = seed
    for _ in range(200):
        for i in range(1000):
            acc = (acc * 31 + i) % 281474976710656
            acc = (acc ^ (acc >> 33)) & MASK64
            acc = (acc + acc // ((i & 7) + 2)) & MASK64
    return acc % 65536


def main():
    acc = 7
    for _ in range(REPEAT):
        acc = work(acc)
    c = acc & 0xFFFFFFFF
    print(f"checksum {c}")


main()
