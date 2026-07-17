// Порт tests/bench/programs/BankBench.eat 1:1 — банкованная память
// pool[a/4096][a%4096], адрес зависит от loop-carried acc. Вывод
// обязан совпасть байт-в-байт с EATLang-оригиналом при том же REPEAT.
// Банк — Box (128 КБ, не на стеке), как var pool в EATLang (кадр).

const REPEAT: u32 = 1;

fn work(seed: u32) -> u32 {
    let mut pool: Box<[[u32; 4096]; 8]> = Box::new([[0u32; 4096]; 8]);
    let mut acc: u32 = seed;
    for _ in 0..200u32 {
        for i in 0..1000u32 {
            let a: u32 = (acc + i * 37) % 32768;
            pool[(a / 4096) as usize][(a % 4096) as usize] = (acc + i) % 65536;
            let b: u32 = (a * 17 + 5) % 32768;
            acc = (acc + pool[(b / 4096) as usize][(b % 4096) as usize]) % 65536;
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
