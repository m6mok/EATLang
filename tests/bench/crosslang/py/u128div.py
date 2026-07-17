# Порт tests/bench/programs/U128DivBench.eat 1:1 — деление 128 бит:
# EATLang — полный сдвиговый divrem (128 итераций) и divrem_32 по
# лимбам, Python — divmod над int произвольной точности. Вывод обязан
# совпасть байт-в-байт при том же REPEAT.

REPEAT = 1

MASK64 = (1 << 64) - 1


def lcg(x):
    return (x * 31 + 7) % 281474976710656


def work(seed):
    x = seed + 3
    acc = 0
    for _ in range(400):
        x = lcg(x)
        hi = x
        x = lcg(x)
        lo = x
        x = lcg(x)
        d = x | 1
        q, r = divmod((hi << 64) | lo, d)
        acc = acc ^ (q & MASK64) ^ (q >> 64) ^ r
    for _ in range(4000):
        x = lcg(x)
        hi = x
        x = lcg(x)
        lo = x
        x = lcg(x)
        d32 = (x & 4294967295) | 1
        q, r = divmod((hi << 64) | lo, d32)
        acc = acc ^ (q & MASK64) ^ (q >> 64) ^ r
    return acc % 65536


def main():
    acc = 7
    for _ in range(REPEAT):
        acc = work(acc)
    c = acc & 0xFFFFFFFF
    print(f"checksum {c}")


if __name__ == "__main__":
    main()
