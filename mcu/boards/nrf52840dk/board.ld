/* nRF52840 DK: 1 МБ флеша, 256 КБ RAM. */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 1024K
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 256K
}

INCLUDE mcu/common/sections.ld
