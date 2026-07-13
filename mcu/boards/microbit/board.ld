/* BBC micro:bit v1 (nRF51822): 256 КБ флеша, 16 КБ RAM —
 * автосверка §8 отсеивает программы, которым здесь тесно. */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 256K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 16K
}

INCLUDE mcu/common/sections.ld
