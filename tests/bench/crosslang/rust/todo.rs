// Порт tests/bench/programs/TodoBench.eat 1:1 — ядро RESTful TODO-list:
// bounded-пул из 64 слотов под потоком create/toggle/serialize/remove.
// safe-вариант: индексация массивов проверяется (тот самый «налог»).
// Вывод обязан совпасть байт-в-байт с EATLang-оригиналом при том же
// REPEAT.

const REPEAT: u32 = 1;
const CAP: u32 = 64;
const TLEN: u32 = 16;

struct Store {
    id: [u32; 64],
    title: [u8; 1024],
    done: [u8; 64],
    used: [u8; 64],
    next_id: u32,
}

impl Store {
    fn create(&mut self, k: u32, seed: u32) -> u32 {
        let slot = k % CAP;
        let base = slot * TLEN;
        let id = self.next_id;
        self.id[slot as usize] = id;
        for j in 0..16u32 {
            self.title[(base + j) as usize] = (65 + (seed + k + j * 7) % 26) as u8;
        }
        self.done[slot as usize] = (k % 2) as u8;
        self.used[slot as usize] = 1;
        self.next_id += 1;
        id
    }

    fn toggle(&mut self, idx: u32) {
        if self.done[idx as usize] == 0 {
            self.done[idx as usize] = 1;
        } else {
            self.done[idx as usize] = 0;
        }
    }

    fn remove(&mut self, idx: u32) {
        self.used[idx as usize] = 0;
    }

    fn serialize(&self) -> u32 {
        let mut sum: u32 = 0;
        for slot in 0..64usize {
            if self.used[slot] == 1 {
                let mut m = self.id[slot];
                for _ in 0..10 {
                    if m == 0 {
                        break;
                    }
                    sum = (sum * 31 + m % 10) % 65536;
                    m /= 10;
                }
                let base = slot * 16;
                for j in 0..16usize {
                    sum = (sum * 31 + self.title[base + j] as u32) % 65536;
                }
                sum = (sum * 31 + self.done[slot] as u32) % 65536;
            }
        }
        sum
    }
}

fn main() {
    let mut s = Store {
        id: [0; 64],
        title: [0; 1024],
        done: [0; 64],
        used: [0; 64],
        next_id: 1,
    };
    let mut acc: u32 = 0;
    for _ in 0..REPEAT {
        for k in 0..2048u32 {
            let seed = acc;
            let id = s.create(k, seed);
            acc = (acc * 31 + id) % 65536;
            let t = (k * 3) % CAP;
            s.toggle(t);
            if k % 8 == 0 {
                acc = (acc * 31 + s.serialize()) % 65536;
            }
            if k % 16 == 0 {
                let r = (k * 5) % CAP;
                s.remove(r);
            }
        }
    }
    println!("checksum {}", acc);
}
