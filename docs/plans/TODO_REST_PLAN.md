# План: RESTful TODO-list на EATLang

- **Статус:** ✅ ВЫПОЛНЕН (2026-07-17: этапы 0–5 закрыты. Пример
  `examples/http/todo/Todo.eat` — `Store` bounded-пул 256 в кадре `main`,
  полный CRUD + PATCH над `/todos[/{id}]`, тела/ответы JSON; сверка
  транскриптом `todo_net.txt` (`make run_http_todo`, `VERIFIED HttpTodo`).
  Crosslang-бенч `todo` (5 языков байт-в-байт, EAT/C = 1,13, налог
  отрицательный) + store-профиль `profile_e` в `http` (EAT/C 1,06 → 0,94
  build / 0,86 selfhost -O). Числа — `tests/bench/CROSSLANG.md`, седьмой
  прогон. Решения-дефолты §10 приняты: 507 на полный пул, PUT = полная
  замена, пагинации нет)
- **Роль:** справка — витрина REST + бенч (этапы 0–5 закрыты)
- **Рабочие поверхности:** `examples/http/todo/` (новый),
  `tests/bench/programs/TodoBench.eat` (новый),
  `tests/bench/crosslang/{c,rust,go,py}/todo.*` (новые),
  `tests/bench/programs/HttpBench.eat` (расширение store-профилем),
  `Makefile`, `tests/bench/crosslang/run.py`, README/индекс
- **Правки языка/грамматики:** нет
- **Новые аксиомы ОС (SPEC §7):** нет (сокеты уже есть — [HTTP_PLAN](HTTP_PLAN.md) §9)
- **Зеркало в selfhost:** не требуется — чисто библиотечный/примерный код
  на EATLang наличными средствами (как `Api.eat`/`Router.eat`)
- **Опирается на:** [HTTP_PLAN](HTTP_PLAN.md) ✅ (`lib/Http.eat`, роутер,
  тело CL/chunked, потолки 413/431/400), [JSON_PLAN](JSON_PLAN.md) ✅
  (`lib/Json.eat`, DOM+сериализатор), [MODULES_PLAN](MODULES_PLAN.md) ✅
  (`lib/`, `lib/Parse.eat`), [CROSSLANG_BENCH_PLAN](CROSSLANG_BENCH_PLAN.md) ✅
- **Блокеры:** нет
- **Блокирует:** —

## 1. Итог одной строкой

Витрина «настоящего REST-ресурса» поверх наличного HTTP-стека: `Store` —
bounded-пул задач в кадре `var` в `main`, переживающий соединения через
единственный `loop`; полный CRUD + PATCH над `/todos[/{id}]`, тела и
ответы — JSON через `lib/Json.eat`; сверка транскриптом `EAT_NET` и
кросс-языковой бенч диспетча+store.

## 2. Почему язык к этому приспособлен

REST-ресурс — это состояние (коллекция) + детерминированный диспетч. Оба
ложатся на язык без натяжек:

- **Состояние без кучи и глобалов.** Коллекция задач — фиксированный
  массив `[Todo; TODO_CAP]` в структуре `Store`, живущей как `var store`
  в кадре `main`. Мутация — только через `var self`-методы `Store`
  (правило: единственный писатель в чужую память — `var self`,
  [GUIDE.md](../GUIDE.md)). Никаких глобалов (правило 8), никакой кучи
  (правило 3). Переполнение пула — штатный `507`/`400`, не рост.
- **Диспетч статичен.** Маршрут → метод `Store` виден компилятору (граф
  вызовов — DAG, правило 9: указателей на функции нет). Метод+путь →
  один `match`/цепочка `if` с ранним возвратом.
- **Тело и ответ bounded.** Разбор тела — `lib/Http.Body` (CL/chunked,
  потолок `HTTP_MAX_BODY` → 413). JSON — `lib/Json.eat` (пул узлов +
  арена + явный стек, глубже лимита → 400). Печать списка — `JOut`
  (буфер `[u8; 65536]`, переполнение → флаг `over`, не рост).
- **Один `loop` в `main`.** accept-loop уже узаконен HTTP_PLAN; `Store`
  создаётся **до** цикла и переживает соединения (как `req.reset()` в
  `Router.eat`, но без сброса — состояние копится).

## 3. Рамка: свойство → правило → потолок

| Свойство REST | Правило Power of 10 | Потолок (§6) |
| --- | --- | --- |
| Коллекция задач | 3 (нет кучи) · 8 (нет глобалов) | `TODO_CAP = 256` задач |
| Длина заголовка задачи | 3 · 1 (нет роста) | `title: str<128>` |
| Тело запроса | 3 | `HTTP_MAX_BODY = 65536` → 413 |
| Глубина JSON | 2 (граница цикла) | лимит `lib/Json.eat` → 400 |
| Ответ-список | 3 | `JOut.buf = 65536` → `over` |
| Матчинг маршрута | 2 | `for` со статической границей, 1 `break` |
| id из пути | 1 | `path_param(skip)` ≤ 64 байт → 404 |

Переполнение любого потолка — **штатный HTTP-код** (413/400/404/507),
никогда не trap и не рост структуры.

## 4. Числа (пределы)

- `TODO_CAP: u32 = 256` — максимум одновременно живущих задач; при полном
  пуле `POST /todos` → `507 Insufficient Storage` (или `503` — §10).
- `title: str<128>` — заголовок; длиннее в теле → усечение? нет: → `400`.
- id — монотонный счётчик `next_id: u32`, стартует с 1; удалённые id не
  переиспользуются (слот освобождается, id — нет).
- `SERVE_CONNS` — детерминированный останов для транскрипта (число
  соединений в `todo_net.txt`).

## 5. Аксиомы ОС

Новых нет. Используются сокет-аксиомы HTTP_PLAN §9 (`socket_listen`,
`socket_accept`, `socket_read_byte`, `socket_avail`, `socket_write_span`,
`socket_close`) и транскрипт `EAT_NET` для сверки.

## 6. Архитектура / механизм

```
struct Todo   { id: u32, title: str<128>, done: bool, used: bool }
struct Store  { items: [Todo; 256], next_id: u32, count: u32
                # var self: create/update/remove/toggle
                # self:     find(id)->idx|NONE, serialize_list(JOut),
                #           serialize_one(JOut, idx)
}
```

- **Store в кадре `main`.** `var store: Store = store_new()` до `loop`;
  диспетч соединения вызывает методы store. Мутация — `var self`.
- **Маршруты (метод + путь):**

  | Метод | Путь | Действие | Коды |
  | --- | --- | --- | --- |
  | GET | `/todos` | список всех | 200 |
  | POST | `/todos` | создать `{title, done?}` | 201 / 400 / 507 |
  | GET | `/todos/{id}` | одна задача | 200 / 404 |
  | PUT | `/todos/{id}` | заменить title+done | 200 / 400 / 404 |
  | PATCH | `/todos/{id}` | переключить `done` | 200 / 404 |
  | DELETE | `/todos/{id}` | удалить | 204 / 404 |

- **id из пути** — `Req.path_param(len("/todos/"))` → `parse_i32` →
  `u32`; мимо диапазона/кривой → 404.
- **Тело** — `lib/Http.Body` (CL/chunked), затем `JDoc.parse`; `title` —
  `as_str`, `done` — `as_bool`.
- **Ответ-список** — `JOut`: `[` + объекты через запятую + `]`, длина
  произвольная (bounded 64 КБ). Одна задача — `Resp.body` интерполяцией.

## 7. Что реализуем НЕ

- **Персистентность на диск / БД** — нет (нет файловых аксиом в рамках
  плана; store — только в памяти, гибнет с процессом). Это витрина REST,
  не хранилища.
- **Конкурентные соединения / потоки** — нет (один `loop`, одно
  соединение за раз; правило кооперативного исполнителя ASYNC_PLAN).
- **Пагинация/фильтры/сортировка query-string** — нет в первой версии
  (можно как хвост §10).
- **HTTP/2, TLS** — нет (отвергнуто HTTP_PLAN §7).
- **Рост коллекции** — нет: полный пул → 507, не реаллокация.
- **Переиспользование id** — нет: id монотонны, слот освобождается.

## 8. Этапы

0. **План + решения** (этот документ). ✅ по написании.
1. **Store + пример** — `examples/http/todo/Todo.eat`: `Store`, CRUD+PATCH,
   диспетч, `main` с accept-loop. Готово: `make check` компилирует,
   `$(EATC) run` на транскрипте даёт ожидаемый вывод.
2. **Транскрипт + verify** — `todo_net.txt` (полный жизненный цикл: create
   → list → get → put → patch → delete → 404), `make run_http_todo`,
   бинарник == интерпретатор (`verify`-цель). Готово: `make verify`
   зелёный с новой целью.
3. **Crosslang-бенч** — `tests/bench/programs/TodoBench.eat` + порты
   `c/rust/go/py/todo.*` байт-в-байт, регистрация в `run.py` (`BENCHES`).
   Нагрузка: N операций CRUD над store + сериализация. Готово:
   `make bench_crosslang` считает `todo`, checksum сходится у 5 языков.
4. **Расширение `http`-профиля** — добавить store-микрооперацию в
   `HttpBench.eat` и одноимённые порты (выбор пользователя «оба»). Готово:
   профиль `http` пересчитан, checksum сходится.
5. **Числа + документы** — метрики в `tests/bench/FINDINGS.md` и
   `CROSSLANG.md`, статус плана → ✅, строка индекса, README/памяти.

## 9. Паритет

Зеркало в `selfhost/*.eat` **не требуется**: план не меняет язык,
грамматику, встроенные, дампы, тексты ошибок и IR. Весь код — на EATLang
поверх `lib/` (как `examples/http/Api.eat`, `Router.eat`). Порты бенча
(C/Rust/Go/Python) — байт-в-байт по checksum, как остальной crosslang.

## 10. Открытые вопросы (решения пользователя)

- **Код полного пула** — `507 Insufficient Storage` или `503 Service
  Unavailable`? (по умолчанию 507). — *не блокер, дефолт 507*
- **Пагинация/query** — вводить `?done=true`/`?limit` хвостом? — *нет в
  v1, backlog*
- **Тело PUT неполное** (нет `title`) — 400 или частичное обновление? —
  *по умолчанию 400 (PUT = полная замена; частичное — это PATCH)*

## 11. Инварианты

План **не открывает** ни одного обхода Power of 10: коллекция — массив
фиксированного размера (нет кучи, нет роста), диспетч — статический граф
(нет указателей на функции), циклы — с явными границами и ≤ 1 `break`,
состояние — `var` в кадре `main` (нет мутабельных глобалов), результаты
парсинга/сериализации — не отбрасываются молча (`discard`/`match`).
Переполнение любого потолка — HTTP-код-значение, не trap.

## 12. Затронутые поверхности

- `examples/http/todo/` — новый пример + транскрипт (+ мини-README).
- `Makefile` — `run_http_todo`, `serve_todo`, цель `verify`, список
  `make check`-компиляции, `CROSSLANG`-подключение бенча.
- `tests/bench/` — `programs/TodoBench.eat`, `crosslang/{c,rust,go,py}`,
  `run.py` (`BENCHES`), `FINDINGS.md`, `CROSSLANG.md`.
- `docs/plans/README.md` — строка индекса; `HTTP_PLAN.md` — ссылка
  «витрина REST» (справка). README корня — при желании в витрину.
- Память проекта — итог этапа.

## 13. Определение готовности

Полный гейт AGENTS.md §3 зелёный целиком: `make check verify
verify_suite verify_selfhost verify_bootstrap verify_trapcodes
verify_selfhost_opt verify_sig verify_selfhost_verify
verify_selfhost_verify_all`, плюс `make bench_crosslang` считает `todo`
и `http` со сходящимися checksum у всех языков.
