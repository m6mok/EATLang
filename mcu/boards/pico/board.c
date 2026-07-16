/* Raspberry Pi Pico (RP2040, Cortex-M0+) — прошивочный порт,
 * QEMU-машины нет: в CI-воротах только сборка + автосверка §8,
 * проверка на железе — у пользователя (даташит RP2040). Старт —
 * через boot2.S (XIP), клоки — минимум: XOSC 12 МГц напрямую в
 * clk_ref/clk_sys/clk_peri, без PLL (для суперцикла и 115200 бод
 * хватает, и меньше точек отказа).
 *
 * Раскладка: UART0 — GP0 (TX) / GP1 (RX), 115200 8N1;
 * линия 0 (LED) — GP25 (штатный светодиод, активный высокий);
 * линия 1 (кнопка) — GP14 на землю, подтяжка вверх (на плате кнопки
 * нет — подпаяйте свою или оставьте: «отпущена»).
 * Приём — по прерыванию UART0 (IRQ 20) в кольцо шима (MCU_PLAN §2). */

#include <stdbool.h>
#include <stdint.h>

/* атомарный сброс битов у периферии RP2040: адрес регистра | 0x3000 */
#define RESETS_RESET_CLR (*(volatile uint32_t *)0x4000F000u)
#define RESETS_RESET_DONE (*(volatile uint32_t *)0x4000C008u)
#define RESET_IO_BANK0 (1u << 5)
#define RESET_PADS_BANK0 (1u << 8)
#define RESET_UART0 (1u << 22)

#define XOSC_CTRL (*(volatile uint32_t *)0x40024000u)
#define XOSC_STATUS (*(volatile uint32_t *)0x40024004u)
#define XOSC_STARTUP (*(volatile uint32_t *)0x4002400Cu)

#define CLK_REF_CTRL (*(volatile uint32_t *)0x40008030u)
#define CLK_REF_SELECTED (*(volatile uint32_t *)0x40008038u)
#define CLK_PERI_CTRL (*(volatile uint32_t *)0x40008048u)

#define IO_GPIO_CTRL(n) \
    (*(volatile uint32_t *)(0x40014004u + 8u * (n)))
#define PADS_GPIO(n) (*(volatile uint32_t *)(0x4001C004u + 4u * (n)))

#define SIO_GPIO_IN (*(volatile uint32_t *)0xD0000004u)
#define SIO_GPIO_OUT_SET (*(volatile uint32_t *)0xD0000014u)
#define SIO_GPIO_OUT_CLR (*(volatile uint32_t *)0xD0000018u)
#define SIO_GPIO_OE_SET (*(volatile uint32_t *)0xD0000024u)

#define UART0_DR (*(volatile uint32_t *)0x40034000u)
#define UART0_FR (*(volatile uint32_t *)0x40034018u)
#define UART0_IBRD (*(volatile uint32_t *)0x40034024u)
#define UART0_FBRD (*(volatile uint32_t *)0x40034028u)
#define UART0_LCR_H (*(volatile uint32_t *)0x4003402Cu)
#define UART0_CR (*(volatile uint32_t *)0x40034030u)
#define UART0_IMSC (*(volatile uint32_t *)0x40034038u)

#define UART_FR_RXFE (1u << 4)
#define UART_FR_TXFF (1u << 5)

#define PIN_TX 0u
#define PIN_RX 1u
#define PIN_LED 25u
#define PIN_BTN 14u

#define NVIC_ISER0 (*(volatile uint32_t *)0xE000E100u)
#define UART0_IRQ 20u

void shim_ring_put(uint8_t b);
int32_t shim_ring_get(void);

const uint32_t board_clock_hz = 12000000; /* clk_sys = XOSC 12 МГц */

void board_init(void) {
    /* XOSC 12 МГц: задержка старта в блоках по 256 тактов, затем
     * магия ENABLE и ожидание стабилизации */
    XOSC_STARTUP = 47u;
    XOSC_CTRL = (0xFABu << 12) | 0xAA0u;
    while ((XOSC_STATUS & (1u << 31)) == 0) {
    }
    /* clk_ref <- xosc (clk_sys идёт от clk_ref); clk_peri <- clk_sys */
    CLK_REF_CTRL = 2u;
    while ((CLK_REF_SELECTED & (1u << 2)) == 0) {
    }
    CLK_PERI_CTRL = 1u << 11;
    /* вывести из сброса IO/PADS/UART0 */
    RESETS_RESET_CLR = RESET_IO_BANK0 | RESET_PADS_BANK0 | RESET_UART0;
    while ((RESETS_RESET_DONE &
            (RESET_IO_BANK0 | RESET_PADS_BANK0 | RESET_UART0)) !=
           (RESET_IO_BANK0 | RESET_PADS_BANK0 | RESET_UART0)) {
    }
    /* пины: GP0/GP1 — UART0 (funcsel 2), GP25/GP14 — SIO (funcsel 5);
     * GP14 — вход с подтяжкой вверх (IE|DRIVE|PUE|SCHMITT) */
    IO_GPIO_CTRL(PIN_TX) = 2u;
    IO_GPIO_CTRL(PIN_RX) = 2u;
    IO_GPIO_CTRL(PIN_LED) = 5u;
    IO_GPIO_CTRL(PIN_BTN) = 5u;
    PADS_GPIO(PIN_BTN) = (1u << 6) | (1u << 4) | (1u << 3) | (1u << 1);
    SIO_GPIO_OUT_CLR = 1u << PIN_LED;
    SIO_GPIO_OE_SET = 1u << PIN_LED;
    /* UART0: 115200 8N1 от clk_peri 12 МГц (делитель 6 + 33/64);
     * FIFO выключен — RX-прерывание на каждый байт */
    UART0_IBRD = 6u;
    UART0_FBRD = 33u;
    UART0_LCR_H = 0x60u;
    UART0_CR = (1u << 9) | (1u << 8) | 1u;
    UART0_IMSC = 1u << 4;
    NVIC_ISER0 = 1u << UART0_IRQ;
    /* VTOR уже указывает на 0x10000100 — выставил boot2.S */
}

void board_putc(uint8_t b) {
    while ((UART0_FR & UART_FR_TXFF) != 0) {
    }
    UART0_DR = b;
}

/* --- хуки периферийного шима (mcu/common/shim.c) -------------------- */

/* ISR -> кольцо -> uart_poll (MCU_PLAN §2) */
void board_irq(uint32_t irq) {
    if (irq == UART0_IRQ) {
        while ((UART0_FR & UART_FR_RXFE) == 0) {
            shim_ring_put((uint8_t)(UART0_DR & 0xFFu));
        }
    }
}

int32_t board_uart_poll(void) {
    return shim_ring_get();
}

void board_gpio_set(uint32_t line, bool on) {
    if (line == 0u) {
        if (on) {
            SIO_GPIO_OUT_SET = 1u << PIN_LED;
        } else {
            SIO_GPIO_OUT_CLR = 1u << PIN_LED;
        }
    }
}

bool board_gpio_get(uint32_t line) {
    if (line == 1u) {
        return (SIO_GPIO_IN & (1u << PIN_BTN)) == 0; /* активный низкий */
    }
    return (SIO_GPIO_IN & (1u << PIN_LED)) != 0;
}
