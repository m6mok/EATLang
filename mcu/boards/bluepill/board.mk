# Blue Pill: STM32F103C8, Cortex-M3 (thumbv7m), 20 КБ RAM.
# QEMU-машины нет — прошивочная цель: st-flash (stlink) или OpenOCD.
ARCH_FLAGS = --target=thumbv7m-none-eabi -mcpu=cortex-m3
RAM_SIZE = 20480
MCU_POST = $(MCU_OBJCOPY) -O binary $(MCU_DIR)/$(MCU_PROG).elf \
	$(MCU_DIR)/$(MCU_PROG).bin
FLASH_CMD = st-flash --reset write $(MCU_DIR)/$(MCU_PROG).bin 0x08000000
