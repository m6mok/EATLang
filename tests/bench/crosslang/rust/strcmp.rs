// Порт tests/bench/programs/StrCmpBench.eat 1:1 — сборка String
// через format! (префикс + десятичное число) и посимвольное
// сравнение == с общим префиксом 40+ байт. Вывод обязан совпасть
// байт-в-байт с EATLang-оригиналом при том же REPEAT.

const REPEAT: u32 = 1;

fn main() {
    let t = String::from("common-prefix-the-quick-brown-fox-jumps-tail-00000");
    let mut acc: u32 = 0;
    for _ in 0..REPEAT {
        for k in 0..20u32 {
            for i in 0..1000u32 {
                acc = (acc * 31 + i + k) % 65536;
                let s = format!(
                    "common-prefix-the-quick-brown-fox-jumps-tail-{}", acc);
                if s == t {
                    acc = acc + 7;
                }
            }
        }
    }
    println!("checksum {}", acc);
}
