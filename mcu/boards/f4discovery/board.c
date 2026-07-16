/* STM32F4DISCOVERY (STM32F407VG, Cortex-M4) — прошивочный порт,
 * QEMU-машины нет: в CI-воротах только сборка + автосверка §8,
 * проверка на железе — у пользователя (RM0090). Ядро на HSI 16 МГц
 * (RCC не разгоняем — меньше точек отказа).
 *
 * Раскладка: USART2 — PA2 (TX) / PA3 (RX), AF7, 115200 8N1;
 * линия 0 (LED) — PD12 (зелёный, активный высокий);
 * линия 1 (кнопка) — PA0 (синяя USER, активный высокий,
 * подтяжка вниз на плате).
 * Приём — по прерыванию USART2 (IRQ 38) в кольцо шима (MCU_PLAN §2). */

#include <stdbool.h>
#include <stdint.h>

#define RCC_AHB1ENR (*(volatile uint32_t *)0x40023830u)
#define RCC_APB1ENR (*(volatile uint32_t *)0x40023840u)

#define GPIOA_MODER (*(volatile uint32_t *)0x40020000u)
#define GPIOA_IDR (*(volatile uint32_t *)0x40020010u)
#define GPIOA_AFRL (*(volatile uint32_t *)0x40020020u)
#define GPIOD_MODER (*(volatile uint32_t *)0x40020C00u)
#define GPIOD_BSRR (*(volatile uint32_t *)0x40020C18u)

#define USART2_SR (*(volatile uint32_t *)0x40004400u)
#define USART2_DR (*(volatile uint32_t *)0x40004404u)
#define USART2_BRR (*(volatile uint32_t *)0x40004408u)
#define USART2_CR1 (*(volatile uint32_t *)0x4000440Cu)

#define USART_SR_RXNE (1u << 5)
#define USART_SR_TXE (1u << 7)
#define USART_CR1_RE (1u << 2)
#define USART_CR1_TE (1u << 3)
#define USART_CR1_RXNEIE (1u << 5)
#define USART_CR1_UE (1u << 13)

#define NVIC_ISER1 (*(volatile uint32_t *)0xE000E104u)
#define USART2_IRQ 38u

void shim_ring_put(uint8_t b);
int32_t shim_ring_get(void);

const uint32_t board_clock_hz = 16000000; /* HSI, RCC по умолчанию */

void board_init(void) {
    /* клоки: GPIOA (бит 0), GPIOD (бит 3); USART2 на APB1 (бит 17) */
    RCC_AHB1ENR |= (1u << 0) | (1u << 3);
    RCC_APB1ENR |= 1u << 17;
    /* PA2/PA3 — альтернативная функция AF7 (USART2), PA0 — вход (00) */
    GPIOA_MODER = (GPIOA_MODER & ~0xF0u) | (0x2u << 4) | (0x2u << 6);
    GPIOA_AFRL = (GPIOA_AFRL & ~0xFF00u) | (0x7u << 8) | (0x7u << 12);
    /* PD12 — LED: выход push-pull, погашен */
    GPIOD_MODER = (GPIOD_MODER & ~(0x3u << 24)) | (0x1u << 24);
    GPIOD_BSRR = 1u << (12u + 16u);
    /* 115200 8N1 от 16 МГц: USARTDIV 8.69 -> BRR 0x8B; RX — прерывание */
    USART2_BRR = 0x8Bu;
    USART2_CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE |
                 USART_CR1_RXNEIE;
    NVIC_ISER1 = 1u << (USART2_IRQ - 32u);
}

void board_putc(uint8_t b) {
    while ((USART2_SR & USART_SR_TXE) == 0) {
    }
    USART2_DR = b;
}

/* --- хуки периферийного шима (mcu/common/shim.c) -------------------- */

/* ISR -> кольцо -> uart_poll (MCU_PLAN §2) */
void board_irq(uint32_t irq) {
    if (irq == USART2_IRQ && (USART2_SR & USART_SR_RXNE) != 0) {
        shim_ring_put((uint8_t)(USART2_DR & 0xFFu));
    }
}

int32_t board_uart_poll(void) {
    return shim_ring_get();
}

static bool led_state; /* зеркало состояния PD12 */

void board_gpio_set(uint32_t line, bool on) {
    if (line == 0u) {
        led_state = on;
        GPIOD_BSRR = on ? (1u << 12u) : (1u << (12u + 16u));
    }
}

bool board_gpio_get(uint32_t line) {
    if (line == 1u) {
        return (GPIOA_IDR & 1u) != 0; /* активный высокий */
    }
    return led_state;
}
