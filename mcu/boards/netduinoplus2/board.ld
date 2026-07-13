/* Netduino Plus 2 (STM32F405): 1 МБ флеша с 0x08000000, 128 КБ RAM
 * (CCM 64K на 0x10000000 не используем — DMA его не видит). */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 1M
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}

INCLUDE mcu/common/sections.ld
