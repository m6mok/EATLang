# QEMU mps2-an385: Cortex-M3, 4 МБ «флеша» (SSRAM1) + 4 МБ RAM
ARCH_FLAGS = --target=thumbv7m-none-eabi -mcpu=cortex-m3
RAM_SIZE = 4194304
QEMU_MACHINE = mps2-an385
