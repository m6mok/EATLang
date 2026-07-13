/* Раскладка памяти платы QEMU mps2-an385 (ARM Cortex-M3):
 * код и константы — ZBT SSRAM1 с адреса 0 («флеш» демонстрации),
 * данные и стек — SSRAM2/3 с 0x20000000. Стек растёт вниз от
 * вершины RAM; его размер против отчёта §8 компилятора сверяет
 * цель verify_arm (Makefile). */

ENTRY(reset_handler)

MEMORY
{
    FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 4M
    RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 4M
}

SECTIONS
{
    /* Таблицы раскрутки ARM EHABI не нужны: в EATLang нет исключений,
     * trap завершает программу через полухостинг. */
    /DISCARD/ : {
        *(.ARM.exidx*)
        *(.ARM.extab*)
    }

    .vectors : {
        KEEP(*(.vectors))
    } > FLASH

    .text : {
        *(.text*)
    } > FLASH

    .rodata : {
        *(.rodata*)
        . = ALIGN(4);
    } > FLASH

    .data : ALIGN(4) {
        __data_start = .;
        *(.data*)
        . = ALIGN(4);
        __data_end = .;
    } > RAM AT> FLASH

    __data_load = LOADADDR(.data);

    .bss (NOLOAD) : ALIGN(4) {
        __bss_start = .;
        *(.bss*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > RAM
}

__stack_top = ORIGIN(RAM) + LENGTH(RAM);
