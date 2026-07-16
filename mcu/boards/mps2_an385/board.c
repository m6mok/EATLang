/* Плата QEMU mps2-an385 (ARM Cortex-M3): CMSDK APB UART0. */

#include <stdbool.h>
#include <stdint.h>

#define UART0_BASE 0x40004000u
#define UART_DATA (*(volatile uint32_t *)(UART0_BASE + 0x00))
#define UART_STATE (*(volatile uint32_t *)(UART0_BASE + 0x04))
#define UART_CTRL (*(volatile uint32_t *)(UART0_BASE + 0x08))

#define UART_STATE_TX_FULL 1u
#define UART_STATE_RX_FULL 2u
#define UART_CTRL_TX_EN 1u
#define UART_CTRL_RX_EN 2u

void board_init(void) {
    UART_CTRL = UART_CTRL_TX_EN | UART_CTRL_RX_EN;
}

void board_putc(uint8_t b) {
    while (UART_STATE & UART_STATE_TX_FULL) {
    }
    UART_DATA = b;
}

/* --- хуки периферийного шима (mcu/common/shim.c) -------------------- */

const uint32_t board_clock_hz = 25000000; /* AN385: 25 МГц */

/* GPIO платы QEMU не моделирует — зеркало в статике: линии ведут
 * себя как у хостового эталона (кнопка не нажата). Настоящие пины —
 * в прошивочных портах (pico, bluepill, f4discovery, nrf52840dk). */
static bool gpio_lines[2];

void board_gpio_set(uint32_t line, bool on) {
    gpio_lines[line & 1u] = on;
}

bool board_gpio_get(uint32_t line) {
    return gpio_lines[line & 1u];
}

/* RX без прерывания: QEMU придерживает байты, пока RXFULL занят. */
int32_t board_uart_poll(void) {
    if ((UART_STATE & UART_STATE_RX_FULL) == 0) {
        return -1;
    }
    return (int32_t)(UART_DATA & 0xFFu);
}
