/* Netduino Plus 2 (STM32F405, Cortex-M4): USART1 (как у F1,
 * другой базовый адрес). На железе нужны RCC/GPIO (RM0090). */

#include <stdint.h>

#define USART1_BASE 0x40011000u
#define USART_SR (*(volatile uint32_t *)(USART1_BASE + 0x00))
#define USART_DR (*(volatile uint32_t *)(USART1_BASE + 0x04))
#define USART_CR1 (*(volatile uint32_t *)(USART1_BASE + 0x0C))

#define USART_SR_TXE (1u << 7)
#define USART_CR1_UE (1u << 13)
#define USART_CR1_TE (1u << 3)

void board_init(void) {
    USART_CR1 = USART_CR1_UE | USART_CR1_TE;
}

void board_putc(uint8_t b) {
    while ((USART_SR & USART_SR_TXE) == 0) {
    }
    USART_DR = b;
}
