#!/usr/bin/env python3
"""RP2040: ELF -> UF2 с контрольной суммой boot2 (MCU_PLAN §5).

Бутром RP2040 исполняет boot2 только при верной CRC-32 в последних
4 байтах первого 256-байтного блока флеша (poly 0x04C11DB7, init
0xFFFFFFFF, без отражений, little-endian) — вписываем её в плоский
образ и заворачиваем в UF2 (family RP2040): файл понимают
BOOTSEL-диск и picotool. Никаких зависимостей — ELF32 разбирается
руками (нужны только PT_LOAD-сегменты).

Использование: elf2uf2.py вход.elf выход.uf2
"""

import struct
import sys

FLASH_BASE = 0x10000000
FAMILY_RP2040 = 0xE48BFF56
UF2_MAGIC0 = 0x0A324655
UF2_MAGIC1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY = 0x00002000


def crc32_boot2(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def flat_image(elf: bytes) -> bytearray:
    if elf[:4] != b"\x7fELF" or elf[4] != 1 or elf[5] != 1:
        raise SystemExit("elf2uf2: ожидался ELF32 little-endian")
    (e_phoff,) = struct.unpack_from("<I", elf, 28)
    e_phentsize, e_phnum = struct.unpack_from("<HH", elf, 42)
    top = FLASH_BASE
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, _, p_paddr, p_filesz = struct.unpack_from(
            "<5I", elf, off
        )
        if p_type != 1 or p_filesz == 0:  # только PT_LOAD с содержимым
            continue
        if p_paddr < FLASH_BASE:
            raise SystemExit(
                f"elf2uf2: сегмент вне флеша: 0x{p_paddr:08x}"
            )
        segs.append((p_paddr, elf[p_offset : p_offset + p_filesz]))
        top = max(top, p_paddr + p_filesz)
    if not segs:
        raise SystemExit("elf2uf2: нет загружаемых сегментов")
    image = bytearray(top - FLASH_BASE)
    for paddr, data in segs:
        image[paddr - FLASH_BASE : paddr - FLASH_BASE + len(data)] = data
    if len(image) < 256:
        raise SystemExit("elf2uf2: образ короче блока boot2")
    image[252:256] = struct.pack("<I", crc32_boot2(bytes(image[:252])))
    return image


def to_uf2(image: bytearray) -> bytes:
    nblocks = (len(image) + 255) // 256
    out = bytearray()
    for i in range(nblocks):
        chunk = bytes(image[i * 256 : (i + 1) * 256]).ljust(256, b"\0")
        out += struct.pack(
            "<8I",
            UF2_MAGIC0,
            UF2_MAGIC1,
            UF2_FLAG_FAMILY,
            FLASH_BASE + i * 256,
            256,
            i,
            nblocks,
            FAMILY_RP2040,
        )
        out += chunk + b"\0" * (476 - 256)
        out += struct.pack("<I", UF2_MAGIC_END)
    return bytes(out)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("использование: elf2uf2.py вход.elf выход.uf2")
    with open(sys.argv[1], "rb") as f:
        elf = f.read()
    image = flat_image(elf)
    with open(sys.argv[2], "wb") as f:
        f.write(to_uf2(image))
    print(
        f"  uf2: {sys.argv[2]} — {len(image)} Б флеша, "
        f"{(len(image) + 255) // 256} блоков, CRC boot2 вписана"
    )


if __name__ == "__main__":
    main()
