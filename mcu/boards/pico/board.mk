# Raspberry Pi Pico: RP2040, Cortex-M0+ (thumbv6m), 264 КБ RAM.
# QEMU-машины нет — прошивочная цель: picotool (или скопировать .uf2
# на BOOTSEL-диск RPI-RP2 руками).
ARCH_FLAGS = --target=thumbv6m-none-eabi -mcpu=cortex-m0plus
RAM_SIZE = 270336
BOARD_EXTRA = mcu/boards/pico/boot2.S
MCU_POST = uv run python mcu/boards/pico/elf2uf2.py \
	$(MCU_DIR)/$(MCU_PROG).elf $(MCU_DIR)/$(MCU_PROG).uf2
FLASH_CMD = picotool load -x $(MCU_DIR)/$(MCU_PROG).uf2
