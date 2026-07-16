/* nRF52840 DK (Cortex-M4) — прошивочный порт, QEMU-машины нет:
 * в CI-воротах только сборка + автосверка §8, проверка на железе —
 * у пользователя. UART — legacy-регистры (как nRF51, без EasyDMA):
 * шину VCOM отладчика DK слушает через P0.06 (TX) / P0.08 (RX).
 *
 * Раскладка: линия 0 (LED) — P0.13 (LED1, активный низкий);
 * линия 1 (кнопка) — P0.11 (Button1, активный низкий, подтяжка вверх).
 * Приём — по прерыванию UARTE0_UART0 (IRQ 2) в кольцо шима (§2). */

#include <stdbool.h>
#include <stdint.h>

#define UART_BASE 0x40002000u
#define UART_STARTRX (*(volatile uint32_t *)(UART_BASE + 0x000))
#define UART_STARTTX (*(volatile uint32_t *)(UART_BASE + 0x008))
#define UART_RXDRDY (*(volatile uint32_t *)(UART_BASE + 0x108))
#define UART_TXDRDY (*(volatile uint32_t *)(UART_BASE + 0x11C))
#define UART_INTENSET (*(volatile uint32_t *)(UART_BASE + 0x304))
#define UART_ENABLE (*(volatile uint32_t *)(UART_BASE + 0x500))
#define UART_PSELTXD (*(volatile uint32_t *)(UART_BASE + 0x50C))
#define UART_PSELRXD (*(volatile uint32_t *)(UART_BASE + 0x514))
#define UART_RXD (*(volatile uint32_t *)(UART_BASE + 0x518))
#define UART_TXD (*(volatile uint32_t *)(UART_BASE + 0x51C))
#define UART_BAUDRATE (*(volatile uint32_t *)(UART_BASE + 0x524))

#define GPIO_BASE 0x50000000u
#define GPIO_OUTSET (*(volatile uint32_t *)(GPIO_BASE + 0x508))
#define GPIO_OUTCLR (*(volatile uint32_t *)(GPIO_BASE + 0x50C))
#define GPIO_IN (*(volatile uint32_t *)(GPIO_BASE + 0x510))
#define GPIO_DIRSET (*(volatile uint32_t *)(GPIO_BASE + 0x518))
#define GPIO_PIN_CNF(n) (*(volatile uint32_t *)(GPIO_BASE + 0x700 + 4u * (n)))

#define PIN_TX 6u
#define PIN_RX 8u
#define PIN_LED 13u
#define PIN_BTN 11u

#define NVIC_ISER0 (*(volatile uint32_t *)0xE000E100u)
#define UART0_IRQ 2u

void shim_ring_put(uint8_t b);
int32_t shim_ring_get(void);

const uint32_t board_clock_hz = 64000000; /* ядро nRF52: 64 МГц */

void board_init(void) {
    /* TX — выход в покое высокий; RX — вход; LED1 погашен (высокий);
     * Button1 — вход с подтяжкой вверх (PULL=3) */
    GPIO_OUTSET = 1u << PIN_TX;
    GPIO_DIRSET = (1u << PIN_TX) | (1u << PIN_LED);
    GPIO_OUTSET = 1u << PIN_LED;
    GPIO_PIN_CNF(PIN_BTN) = 3u << 2;
    UART_PSELTXD = PIN_TX;
    UART_PSELRXD = PIN_RX;
    UART_BAUDRATE = 0x01D7E000u; /* 115200 */
    UART_ENABLE = 4u;            /* legacy UART */
    UART_STARTTX = 1u;
    UART_STARTRX = 1u;
    UART_INTENSET = 1u << 2; /* RXDRDY -> IRQ 2 */
    NVIC_ISER0 = 1u << UART0_IRQ;
}

void board_putc(uint8_t b) {
    UART_TXDRDY = 0;
    UART_TXD = b;
    while (UART_TXDRDY == 0) {
    }
}

/* --- хуки периферийного шима (mcu/common/shim.c) -------------------- */

/* ISR -> кольцо -> uart_poll (MCU_PLAN §2) */
void board_irq(uint32_t irq) {
    if (irq == UART0_IRQ && UART_RXDRDY != 0) {
        UART_RXDRDY = 0;
        shim_ring_put((uint8_t)(UART_RXD & 0xFFu));
    }
}

int32_t board_uart_poll(void) {
    return shim_ring_get();
}

static bool led_state; /* зеркало состояния LED1 */

void board_gpio_set(uint32_t line, bool on) {
    if (line == 0u) {
        led_state = on;
        if (on) {
            GPIO_OUTCLR = 1u << PIN_LED; /* активный низкий */
        } else {
            GPIO_OUTSET = 1u << PIN_LED;
        }
    }
}

bool board_gpio_get(uint32_t line) {
    if (line == 1u) {
        return (GPIO_IN & (1u << PIN_BTN)) == 0; /* активный низкий */
    }
    return led_state;
}
