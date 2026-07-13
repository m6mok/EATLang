/* QEMU mps2-an385 (Cortex-M3): код — ZBT SSRAM1 с адреса 0,
 * данные и стек — SSRAM2/3 с 0x20000000. */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 4M
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 4M
}

INCLUDE mcu/common/sections.ld
