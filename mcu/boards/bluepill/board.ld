/* Blue Pill (STM32F103C8): 64 КБ флеша, 20 КБ RAM —
 * автосверка §8 отсеивает программы, которым здесь тесно. */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 64K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 20K
}

INCLUDE mcu/common/sections.ld
