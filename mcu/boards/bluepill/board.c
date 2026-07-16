/* Blue Pill (STM32F103C8, Cortex-M3) — прошивочный порт, QEMU-машины
 * нет: в CI-воротах только сборка + автосверка §8, проверка на железе —
 * у пользователя (RM0008). Ядро на HSI 8 МГц (RCC не разгоняем: для
 * суперцикла и 115200 бод хватает, и меньше точек отказа).
 *
 * Раскладка: USART1 — PA9 (TX) / PA10 (RX), 115200 8N1;
 * линия 0 (LED) — PC13 (штатный светодиод, активный низкий);
 * линия 1 (кнопка) — PA0 на землю, подтяжка вверх (на плате кнопки
 * нет — подпаяйте свою или оставьте: «отпущена»).
 * Приём — по прерыванию USART1 (IRQ 37) в кольцо шима (MCU_PLAN §2). */

#include <stdbool.h>
#include <stdint.h>

#define RCC_APB2ENR (*(volatile uint32_t *)0x40021018u)

#define GPIOA_CRL (*(volatile uint32_t *)0x40010800u)
#define GPIOA_CRH (*(volatile uint32_t *)0x40010804u)
#define GPIOA_IDR (*(volatile uint32_t *)0x40010808u)
#define GPIOA_ODR (*(volatile uint32_t *)0x4001080Cu)
#define GPIOC_CRH (*(volatile uint32_t *)0x40011004u)
#define GPIOC_BSRR (*(volatile uint32_t *)0x40011010u)

#define USART1_SR (*(volatile uint32_t *)0x40013800u)
#define USART1_DR (*(volatile uint32_t *)0x40013804u)
#define USART1_BRR (*(volatile uint32_t *)0x40013808u)
#define USART1_CR1 (*(volatile uint32_t *)0x4001380Cu)

#define USART_SR_RXNE (1u << 5)
#define USART_SR_TXE (1u << 7)
#define USART_CR1_RE (1u << 2)
#define USART_CR1_TE (1u << 3)
#define USART_CR1_RXNEIE (1u << 5)
#define USART_CR1_UE (1u << 13)

#define NVIC_ISER1 (*(volatile uint32_t *)0xE000E104u)
#define USART1_IRQ 37u

void shim_ring_put(uint8_t b);
int32_t shim_ring_get(void);

const uint32_t board_clock_hz = 8000000; /* HSI, RCC по умолчанию */

void board_init(void) {
    /* клоки APB2: GPIOA (бит 2), GPIOC (бит 4), USART1 (бит 14) */
    RCC_APB2ENR |= (1u << 2) | (1u << 4) | (1u << 14);
    /* PA9 — TX (AF push-pull, 50 МГц), PA10 — RX (вход floating) */
    GPIOA_CRH = (GPIOA_CRH & ~0xFF0u) | (0xBu << 4) | (0x4u << 8);
    /* PC13 — LED: выход push-pull 2 МГц, погашен (активный низкий) */
    GPIOC_CRH = (GPIOC_CRH & ~(0xFu << 20)) | (0x2u << 20);
    GPIOC_BSRR = 1u << 13;
    /* PA0 — кнопка: вход с подтяжкой (CNF=10), подтяжка вверх (ODR=1) */
    GPIOA_CRL = (GPIOA_CRL & ~0xFu) | 0x8u;
    GPIOA_ODR |= 1u;
    /* 115200 8N1 от 8 МГц: USARTDIV 4.34 -> BRR 0x45; RX — прерывание */
    USART1_BRR = 0x45u;
    USART1_CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE |
                 USART_CR1_RXNEIE;
    NVIC_ISER1 = 1u << (USART1_IRQ - 32u);
}

void board_putc(uint8_t b) {
    while ((USART1_SR & USART_SR_TXE) == 0) {
    }
    USART1_DR = b;
}

/* --- хуки периферийного шима (mcu/common/shim.c) -------------------- */

/* ISR -> кольцо -> uart_poll (MCU_PLAN §2) */
void board_irq(uint32_t irq) {
    if (irq == USART1_IRQ && (USART1_SR & USART_SR_RXNE) != 0) {
        shim_ring_put((uint8_t)(USART1_DR & 0xFFu));
    }
}

int32_t board_uart_poll(void) {
    return shim_ring_get();
}

static bool led_state; /* PC13 обратной связи не даёт — зеркало */

void board_gpio_set(uint32_t line, bool on) {
    if (line == 0u) {
        led_state = on;
        GPIOC_BSRR = on ? (1u << (13u + 16u)) : (1u << 13u);
    }
}

bool board_gpio_get(uint32_t line) {
    if (line == 1u) {
        return (GPIOA_IDR & 1u) == 0; /* активный низкий */
    }
    return led_state;
}
