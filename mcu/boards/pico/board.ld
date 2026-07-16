/* Raspberry Pi Pico (RP2040): 2 МБ QSPI-флеша (XIP по 0x10000000),
 * 264 КБ SRAM. Первые 256 Б флеша — boot2 (boot2.S + CRC от
 * elf2uf2.py), таблица векторов образа — сразу за ним. */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x10000000, LENGTH = 2048K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 264K
}

SECTIONS
{
    .boot2 : {
        KEEP(*(.boot2))
        /* добить блок boot2 до 256 Б — CRC впишет elf2uf2 */
        . = ORIGIN(FLASH) + 0x100;
    } > FLASH
}

INCLUDE mcu/common/sections.ld
