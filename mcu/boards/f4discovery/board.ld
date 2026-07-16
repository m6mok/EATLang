/* STM32F4DISCOVERY (STM32F407VG): 1 МБ флеша, 128 КБ RAM
 * (64 КБ CCM по 0x10000000 не используем: раскладка §8 едина). */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 1024K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 128K
}

INCLUDE mcu/common/sections.ld
