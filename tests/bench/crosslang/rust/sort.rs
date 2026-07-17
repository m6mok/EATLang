// Порт tests/bench/programs/SortBench.eat 1:1 — сортировка вставками
// с data-dependent ветвлениями и взвешенной свёрткой результата.
// Вывод обязан совпасть байт-в-байт с EATLang-оригиналом при том же
// REPEAT.

const REPEAT: u32 = 1;

fn fill(seed: u32, k: u32) -> u32 {
    (seed * 31 + k + 1) % 65536
}

fn main() {
    let mut a: [u32; 32] = [0; 32];
    let mut acc: u32 = 7;
    for _ in 0..REPEAT {
        for _ in 0..500u32 {
            for i in 0..32u32 {
                acc = fill(acc, i);
                a[i as usize] = acc;
            }
            for i in 1..32u32 {
                let v: u32 = a[i as usize];
                let mut j: u32 = i;
                for _ in 0..32u32 {
                    let mut do_move: bool = false;
                    if j > 0 {
                        if a[(j - 1) as usize] > v {
                            do_move = true;
                        }
                    }
                    if do_move {
                        a[j as usize] = a[(j - 1) as usize];
                        j = j - 1;
                    } else {
                        break;
                    }
                }
                a[j as usize] = v;
            }
            for i in 0..32u32 {
                acc = (acc * 3 + a[i as usize]) % 65536;
            }
        }
    }
    println!("checksum {}", acc);
}
