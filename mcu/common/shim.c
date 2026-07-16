/* Периферийный шим §6 (docs/plans/MCU_PLAN.md): реализация
 * extern-границы mcu/Mcu.eat — gpio_set/gpio_get/systick_ms/uart_poll —
 * поверх трёх хуков платы (mcu/boards/<плата>/board.c):
 *   const uint32_t board_clock_hz;            — клок ядра для SysTick
 *   void board_gpio_set(uint32_t line, bool on);
 *   bool board_gpio_get(uint32_t line);
 *   int32_t board_uart_poll(void);            — байт RX или -1
 * Линии GPIO логические (0 — LED, 1 — кнопка): плата отображает их
 * на свои пины — один исходник собирается на все порты.
 * Символы слабые: плата может заменить любую функцию целиком. */

#include <stdbool.h>
#include <stdint.h>

extern const uint32_t board_clock_hz;
void board_gpio_set(uint32_t line, bool on);
bool board_gpio_get(uint32_t line);
int32_t board_uart_poll(void);

__attribute__((weak)) void gpio_set(uint32_t line, bool on) {
    board_gpio_set(line, on);
}

__attribute__((weak)) bool gpio_get(uint32_t line) {
    return board_gpio_get(line);
}

/* Сентинел «байта нет» — 256 (контракт mcu/Mcu.eat: result <= 256). */
__attribute__((weak)) uint32_t uart_poll(void) {
    int32_t b = board_uart_poll();
    if (b < 0) {
        return 256u;
    }
    return (uint32_t)b;
}

/* --- systick_ms: миллисекунды от старта --------------------------------
 * 24-битный SysTick ядра считает вниз на board_clock_hz; накапливаем
 * прошедшие такты в u64 (заворота нет: 2^64 тактов — века) и делим на
 * такты-в-миллисекунду. Опрашивать надо чаще периода счётчика
 * (16.7 M тактов ≈ секунда) — суперцикл опрашивает каждый такт цикла. */

#define SYST_CSR (*(volatile uint32_t *)0xE000E010u)
#define SYST_RVR (*(volatile uint32_t *)0xE000E014u)
#define SYST_CVR (*(volatile uint32_t *)0xE000E018u)
#define SYST_MASK 0x00FFFFFFu
/* CLKSOURCE=клок ядра, ENABLE; без прерывания (TICKINT=0) */
#define SYST_RUN 0x5u

static uint64_t systick_cycles; /* накопленные такты */
static uint32_t systick_prev;   /* CVR прошлого опроса */

__attribute__((weak)) uint64_t systick_ms(void) {
    if ((SYST_CSR & SYST_RUN) != SYST_RUN) {
        SYST_RVR = SYST_MASK;
        SYST_CVR = 0;
        SYST_CSR = SYST_RUN;
        systick_prev = SYST_CVR & SYST_MASK;
    }
    uint32_t cur = SYST_CVR & SYST_MASK;
    systick_cycles += (systick_prev - cur) & SYST_MASK;
    systick_prev = cur;
    return systick_cycles / (board_clock_hz / 1000u);
}

/* --- кольцо байтов UART -------------------------------------------------
 * single-producer (ISR платы) / single-consumer (uart_poll): индексы —
 * по одному слову на сторону, атомарность записи слова есть и на M0,
 * блокировок не нужно (MCU_PLAN §2: ISR → кольцо → extern).
 * Переполнение молча роняет байт — граница явная, как у UART FIFO. */

#define SHIM_RING_N 64u

static volatile uint8_t shim_ring[SHIM_RING_N];
static volatile uint32_t shim_ring_w;
static volatile uint32_t shim_ring_r;

void shim_ring_put(uint8_t b) {
    uint32_t w = shim_ring_w;
    if (w - shim_ring_r < SHIM_RING_N) {
        shim_ring[w % SHIM_RING_N] = b;
        shim_ring_w = w + 1;
    }
}

int32_t shim_ring_get(void) {
    uint32_t r = shim_ring_r;
    if (r == shim_ring_w) {
        return -1;
    }
    uint8_t b = shim_ring[r % SHIM_RING_N];
    shim_ring_r = r + 1;
    return b;
}
