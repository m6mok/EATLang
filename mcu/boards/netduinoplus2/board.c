/* Netduino Plus 2 (STM32F405, Cortex-M4): USART1 (как у F1,
 * другой базовый адрес). На железе нужны RCC/GPIO (RM0090). */

#include <stdbool.h>
#include <stdint.h>

#define USART1_BASE 0x40011000u
#define USART_SR (*(volatile uint32_t *)(USART1_BASE + 0x00))
#define USART_DR (*(volatile uint32_t *)(USART1_BASE + 0x04))
#define USART_CR1 (*(volatile uint32_t *)(USART1_BASE + 0x0C))

#define USART_SR_RXNE (1u << 5)
#define USART_SR_TXE (1u << 7)
#define USART_CR1_RE (1u << 2)
#define USART_CR1_TE (1u << 3)
#define USART_CR1_UE (1u << 13)

void board_init(void) {
    USART_CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
}

void board_putc(uint8_t b) {
    while ((USART_SR & USART_SR_TXE) == 0) {
    }
    USART_DR = b;
}

/* --- хуки периферийного шима (mcu/common/shim.c) -------------------- */

const uint32_t board_clock_hz = 16000000; /* HSI F405 без RCC: 16 МГц */

/* GPIO F4 QEMU не моделирует — зеркало в статике (настоящие пины —
 * в прошивочном порте f4discovery). */
static bool gpio_lines[2];

void board_gpio_set(uint32_t line, bool on) {
    gpio_lines[line & 1u] = on;
}

bool board_gpio_get(uint32_t line) {
    return gpio_lines[line & 1u];
}

/* RX без прерывания: QEMU придерживает байты, пока RXNE взведён. */
int32_t board_uart_poll(void) {
    if ((USART_SR & USART_SR_RXNE) == 0) {
        return -1;
    }
    return (int32_t)(USART_DR & 0xFFu);
}
