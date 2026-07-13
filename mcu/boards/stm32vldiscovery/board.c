/* STM32VLDISCOVERY (STM32F100RB, Cortex-M3): USART1.
 * QEMU включает USART без настройки клоков; на железе перед этим
 * нужны RCC-клоки и GPIO (см. reference manual RM0041). */

#include <stdint.h>

#define USART1_BASE 0x40013800u
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
