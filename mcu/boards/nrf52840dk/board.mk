# nRF52840 DK: Cortex-M4 (thumbv7em), 256 КБ RAM.
# QEMU-машины нет — прошивочная цель: nrfjprog (J-Link DK) или OpenOCD;
# для nRF52840 Dongle — nrfutil dfu поверх того же .hex.
ARCH_FLAGS = --target=thumbv7em-none-eabi -mcpu=cortex-m4
RAM_SIZE = 262144
MCU_POST = $(MCU_OBJCOPY) -O ihex $(MCU_DIR)/$(MCU_PROG).elf \
	$(MCU_DIR)/$(MCU_PROG).hex
FLASH_CMD = nrfjprog -f nrf52 --program $(MCU_DIR)/$(MCU_PROG).hex \
	--sectorerase --reset
