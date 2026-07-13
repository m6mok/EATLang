/* BBC micro:bit v1 (nRF51822, Cortex-M0): UART nRF51. */

#include <stdint.h>

#define UART_BASE 0x40002000u
#define UART_STARTTX (*(volatile uint32_t *)(UART_BASE + 0x008))
#define UART_TXDRDY (*(volatile uint32_t *)(UART_BASE + 0x11C))
#define UART_ENABLE (*(volatile uint32_t *)(UART_BASE + 0x500))
#define UART_TXD (*(volatile uint32_t *)(UART_BASE + 0x51C))

void board_init(void) {
    UART_ENABLE = 4; /* включить UART */
    UART_STARTTX = 1;
}

void board_putc(uint8_t b) {
    UART_TXDRDY = 0;
    UART_TXD = b;
    while (UART_TXDRDY == 0) {
    }
}
