/* RP2040 boot2 — второй загрузчик (даташит RP2040, §2.8.1): бутром
 * копирует первые 256 Б флеша в SRAM и исполняет их, если сошлась
 * CRC-32 в хвосте блока (её вписывает elf2uf2.py). Минимальный
 * вариант: SSI в режим обычного SPI-чтения (команда 03h — работает
 * на любой QSPI-флешке, без выхода на максимум скорости), XIP
 * включается, дальше — таблица векторов образа по 0x10000100. */

.syntax unified
.cpu cortex-m0plus
.thumb

.section .boot2, "ax"

boot2:
    ldr r3, =0x18000000        @ XIP_SSI
    movs r1, #0
    str r1, [r3, #0x08]        @ SSIENR = 0: настройка при выключенном SSI
    movs r1, #4
    str r1, [r3, #0x14]        @ BAUDR = 4 (clk_sys/4 — консервативно)
    ldr r1, =0x001F0300        @ CTRLR0: кадр 32 бита, режим EEPROM-read
    str r1, [r3, #0x00]
    movs r1, #0
    str r1, [r3, #0x04]        @ CTRLR1: NDF = 0 (одно слово на чтение)
    ldr r1, =0x03000218        @ SPI_CTRLR0: XIP_CMD=03h, адрес 24 бита,
    movs r2, #0xF4             @   команда 8 бит, всё по одной линии
    str r1, [r3, r2]
    movs r1, #1
    str r1, [r3, #0x08]        @ SSIENR = 1: XIP готов
    ldr r0, =0x10000100        @ таблица векторов образа (за boot2)
    ldr r1, =0xE000ED08        @ VTOR
    str r0, [r1]
    ldm r0!, {r1, r2}
    msr msp, r1                @ вершина стека из [0]
    bx r2                      @ reset_handler из [1]
.ltorg
