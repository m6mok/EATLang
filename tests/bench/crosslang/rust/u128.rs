// Порт tests/bench/programs/U128Bench.eat 1:1 — 128-битный микс без
// деления: шаг LCG128 (константы PCG64) + точное произведение 64x64.
// EATLang считает лимбами lib/U128.eat, Rust — нативным u128. Вывод
// обязан совпасть байт-в-байт при том же REPEAT.

const REPEAT: u32 = 1;

fn work(seed: u64) -> u64 {
    let mc: u128 = ((2549297995355413924u128) << 64) | 4865540595714422341;
    let inc: u128 = 1442695040888963407;
    let mut s: u128 = ((seed as u128) << 64) | 11634580027462260723;
    let mut acc: u64 = 0;
    for _ in 0..20u32 {
        for _ in 0..1000u32 {
            s = s.wrapping_mul(mc).wrapping_add(inc);
            let hi = (s >> 64) as u64;
            let lo = s as u64;
            let p: u128 = ((hi ^ acc) as u128) * ((lo | 1) as u128);
            acc = acc ^ ((p >> 64) as u64) ^ ((p as u64) >> 7);
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
