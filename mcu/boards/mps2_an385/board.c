/* Плата QEMU mps2-an385 (ARM Cortex-M3): CMSDK APB UART0. */

#include <stdint.h>

#define UART0_BASE 0x40004000u
#define UART_DATA (*(volatile uint32_t *)(UART0_BASE + 0x00))
#define UART_STATE (*(volatile uint32_t *)(UART0_BASE + 0x04))
#define UART_CTRL (*(volatile uint32_t *)(UART0_BASE + 0x08))

#define UART_STATE_TX_FULL 1u
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
