// Порт tests/bench/programs/U128DivBench.eat 1:1 — деление 128 бит:
// EATLang — полный сдвиговый divrem (128 итераций) и divrem_32 по
// лимбам, Rust — нативное деление u128 (__udivti3). Вывод обязан
// совпасть байт-в-байт при том же REPEAT.

const REPEAT: u32 = 1;

fn lcg(x: u64) -> u64 {
    (x * 31 + 7) % 281474976710656
}

fn work(seed: u64) -> u64 {
    let mut x: u64 = seed + 3;
    let mut acc: u64 = 0;
    for _ in 0..400u32 {
        x = lcg(x);
        let hi = x;
        x = lcg(x);
        let lo = x;
        x = lcg(x);
        let d = x | 1;
        let a: u128 = ((hi as u128) << 64) | (lo as u128);
        let q = a / (d as u128);
        let r = a % (d as u128);
        acc = acc ^ (q as u64) ^ ((q >> 64) as u64) ^ (r as u64);
    }
    for _ in 0..4000u32 {
        x = lcg(x);
        let hi = x;
        x = lcg(x);
        let lo = x;
        x = lcg(x);
        let d32 = (x & 4294967295) | 1;
        let a: u128 = ((hi as u128) << 64) | (lo as u128);
        let q = a / (d32 as u128);
        let r = a % (d32 as u128);
        acc = acc ^ (q as u64) ^ ((q >> 64) as u64) ^ (r as u64);
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
