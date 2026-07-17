// Порт tests/bench/programs/ArithBench.eat 1:1 — целочисленная
// арифметика в горячем цикле. Вывод обязан совпасть байт-в-байт
// с EATLang-оригиналом при том же REPEAT.

const REPEAT: u32 = 1;

fn work(seed: u32) -> u32 {
    let mut acc: u32 = seed;
    for _ in 0..1000u32 {
        for i in 0..1000u32 {
            acc = (acc * 31 + i) % 65536;
        }
    }
    acc
}

fn main() {
    let mut acc: u32 = 7;
    for _ in 0..REPEAT {
        acc = work(acc) % 65536;
    }
    println!("checksum {}", acc);
}
