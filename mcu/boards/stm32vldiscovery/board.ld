/* STM32VLDISCOVERY (STM32F100RB): 128 КБ флеша с 0x08000000,
 * 8 КБ RAM — самая тесная плата набора. */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 128K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 8K
}

INCLUDE mcu/common/sections.ld
