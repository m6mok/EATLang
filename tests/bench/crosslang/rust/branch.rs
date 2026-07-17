// Порт tests/bench/programs/BranchBench.eat 1:1 — непредсказуемые
// ветвления, if/elif-диспетчер по битам loop-carried acc. Вывод обязан
// совпасть байт-в-байт с EATLang-оригиналом при том же REPEAT.

const REPEAT: u32 = 1;

fn work(seed: u32) -> u32 {
    let mut acc: u32 = seed + 1;
    for _ in 0..500u32 {
        for i in 0..1000u32 {
            let t: u32 = (acc >> (i & 7)) & 3;
            if t == 0 {
                acc = (acc + i + 1) % 65536;
            } else if t == 1 {
                acc = (acc * 5 + 3) % 65536;
            } else if t == 2 {
                acc = (acc ^ (i & 4095)) % 65536;
            } else {
                acc = ((acc >> 1) | 1) % 65536;
            }
        }
    }
    acc
}

fn main() {
    let mut acc: u32 = 7;
    for _ in 0..REPEAT {
        acc = work(acc);
    }
    println!("checksum {}", acc);
}
