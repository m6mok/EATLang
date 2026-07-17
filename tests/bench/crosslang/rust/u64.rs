// Порт tests/bench/programs/U64Bench.eat 1:1 — 64-битная беззнаковая
// арифметика, деление, широкие сдвиги. Вывод обязан совпасть байт-в-байт
// с EATLang-оригиналом при том же REPEAT.

const REPEAT: u32 = 1;

fn work(seed: u64) -> u64 {
    let mut acc: u64 = seed;
    for _ in 0..200u32 {
        for i in 0..1000u64 {
            acc = (acc * 31 + i) % 281474976710656;
            acc = acc ^ (acc >> 33);
            acc = acc + acc / ((i & 7) + 2);
        }
    }
    acc % 65536
}

fn main() {
    let mut acc: u64 = 7;
    for _ in 0..REPEAT {
        acc = work(acc);
    }
    let c: u32 = acc as u32;
    println!("checksum {}", c);
}
