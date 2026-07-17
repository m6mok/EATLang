// Порт tests/bench/programs/SortBench.eat 1:1 — сортировка вставками,
// unsafe-вариант: `get_unchecked`/`get_unchecked_mut` вместо проверенной
// индексации в горячем цикле (ось «налог на безопасность» Rust).
// Семантика идентична sort.rs; вывод обязан совпасть байт-в-байт.

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
                unsafe {
                    *a.get_unchecked_mut(i as usize) = acc;
                }
            }
            for i in 1..32u32 {
                let v: u32 = unsafe { *a.get_unchecked(i as usize) };
                let mut j: u32 = i;
                for _ in 0..32u32 {
                    let mut do_move: bool = false;
                    if j > 0 {
                        if unsafe { *a.get_unchecked((j - 1) as usize) } > v {
                            do_move = true;
                        }
                    }
                    if do_move {
                        unsafe {
                            let prev = *a.get_unchecked((j - 1) as usize);
                            *a.get_unchecked_mut(j as usize) = prev;
                        }
                        j = j - 1;
                    } else {
                        break;
                    }
                }
                unsafe {
                    *a.get_unchecked_mut(j as usize) = v;
                }
            }
            for i in 0..32u32 {
                acc = (acc * 3 + unsafe { *a.get_unchecked(i as usize) }) % 65536;
            }
        }
    }
    println!("checksum {}", acc);
}
