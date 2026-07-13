/* Общая раскладка секций всех плат: память (MEMORY) задаёт board.ld.
 * Таблицы раскрутки ARM EHABI отброшены: исключений нет, trap
 * завершает программу через полухостинг. */

SECTIONS
{
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
