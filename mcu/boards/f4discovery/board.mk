# STM32F4DISCOVERY: STM32F407VG, Cortex-M4 (thumbv7em), 128 КБ RAM.
# QEMU-машины нет — прошивочная цель: st-flash (stlink) или OpenOCD.
ARCH_FLAGS = --target=thumbv7em-none-eabi -mcpu=cortex-m4
RAM_SIZE = 131072
MCU_POST = $(MCU_OBJCOPY) -O binary $(MCU_DIR)/$(MCU_PROG).elf \
	$(MCU_DIR)/$(MCU_PROG).bin
FLASH_CMD = st-flash --reset write $(MCU_DIR)/$(MCU_PROG).bin 0x08000000
