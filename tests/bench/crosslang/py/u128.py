# Порт tests/bench/programs/U128Bench.eat 1:1 — 128-битный микс без
# деления: шаг LCG128 (константы PCG64) + точное произведение 64x64.
# EATLang считает лимбами lib/U128.eat, Python — int произвольной
# точности с явной маской 2**128. Вывод обязан совпасть байт-в-байт
# при том же REPEAT.

REPEAT = 1

MASK64 = (1 << 64) - 1
MASK128 = (1 << 128) - 1

MC = (2549297995355413924 << 64) | 4865540595714422341
INC = 1442695040888963407


def work(seed):
    s = (seed << 64) | 11634580027462260723
    acc = 0
    for _ in range(20):
        for _ in range(1000):
            s = (s * MC + INC) & MASK128
            hi = s >> 64
            lo = s & MASK64
            p = (hi ^ acc) * (lo | 1)
            acc = acc ^ (p >> 64) ^ ((p & MASK64) >> 7)
    return acc % 65536


def main():
    acc = 7
    for _ in range(REPEAT):
        acc = work(acc)
    c = acc & 0xFFFFFFFF
    print(f"checksum {c}")


if __name__ == "__main__":
    main()
