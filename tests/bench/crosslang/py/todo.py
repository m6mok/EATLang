# Порт tests/bench/programs/TodoBench.eat 1:1 — ядро RESTful TODO-list:
# bounded-пул из 64 слотов под потоком create/toggle/serialize/remove.
# Вывод обязан совпасть байт-в-байт с EATLang-оригиналом при том же
# REPEAT.

REPEAT = 1
CAP = 64
TLEN = 16


class Store:
    def __init__(self):
        self.id = [0] * 64
        self.title = [0] * 1024
        self.done = [0] * 64
        self.used = [0] * 64
        self.next_id = 1

    def create(self, k, seed):
        slot = k % CAP
        base = slot * TLEN
        id_ = self.next_id
        self.id[slot] = id_
        for j in range(16):
            self.title[base + j] = (65 + (seed + k + j * 7) % 26) & 0xFF
        self.done[slot] = k % 2
        self.used[slot] = 1
        self.next_id += 1
        return id_

    def toggle(self, idx):
        self.done[idx] = 1 if self.done[idx] == 0 else 0

    def remove(self, idx):
        self.used[idx] = 0

    def serialize(self):
        sum_ = 0
        for slot in range(64):
            if self.used[slot] == 1:
                m = self.id[slot]
                for _ in range(10):
                    if m == 0:
                        break
                    sum_ = (sum_ * 31 + m % 10) % 65536
                    m //= 10
                base = slot * TLEN
                for j in range(16):
                    sum_ = (sum_ * 31 + self.title[base + j]) % 65536
                sum_ = (sum_ * 31 + self.done[slot]) % 65536
        return sum_


def main():
    s = Store()
    acc = 0
    for _ in range(REPEAT):
        for k in range(2048):
            seed = acc
            id_ = s.create(k, seed)
            acc = (acc * 31 + id_) % 65536
            t = (k * 3) % CAP
            s.toggle(t)
            if k % 8 == 0:
                acc = (acc * 31 + s.serialize()) % 65536
            if k % 16 == 0:
                r = (k * 5) % CAP
                s.remove(r)
    print(f"checksum {acc}")


main()
