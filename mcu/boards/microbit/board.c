/* BBC micro:bit v1 (nRF51822, Cortex-M0): UART nRF51. */

#include <stdbool.h>
#include <stdint.h>

#define UART_BASE 0x40002000u
#define UART_STARTRX (*(volatile uint32_t *)(UART_BASE + 0x000))
#define UART_STARTTX (*(volatile uint32_t *)(UART_BASE + 0x008))
#define UART_RXDRDY (*(volatile uint32_t *)(UART_BASE + 0x108))
#define UART_TXDRDY (*(volatile uint32_t *)(UART_BASE + 0x11C))
#define UART_ENABLE (*(volatile uint32_t *)(UART_BASE + 0x500))
#define UART_RXD (*(volatile uint32_t *)(UART_BASE + 0x518))
#define UART_TXD (*(volatile uint32_t *)(UART_BASE + 0x51C))

void board_init(void) {
    UART_ENABLE = 4; /* включить UART */
    UART_STARTTX = 1;
    UART_STARTRX = 1;
}

void board_putc(uint8_t b) {
    UART_TXDRDY = 0;
    UART_TXD = b;
    while (UART_TXDRDY == 0) {
    }
}

/* --- хуки периферийного шима (mcu/common/shim.c) -------------------- */

const uint32_t board_clock_hz = 16000000; /* nRF51: ядро 16 МГц */

/* Плата QEMU-часть автосверки: GPIO — зеркало в статике, чтобы вывод
 * совпадал с хостовым эталоном байт-в-байт (LED-матрице micro:bit
 * нужны row+col — это пример для прошивочных портов). */
static bool gpio_lines[2];

void board_gpio_set(uint32_t line, bool on) {
    gpio_lines[line & 1u] = on;
}

bool board_gpio_get(uint32_t line) {
    return gpio_lines[line & 1u];
}

/* RX без прерывания: QEMU придерживает байты, пока RXDRDY взведён. */
int32_t board_uart_poll(void) {
    if (UART_RXDRDY == 0) {
        return -1;
    }
    UART_RXDRDY = 0;
    return (int32_t)(UART_RXD & 0xFFu);
}
