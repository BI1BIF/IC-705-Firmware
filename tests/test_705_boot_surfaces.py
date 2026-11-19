import unittest
from struct import pack

from tools.replay_705_boot_surfaces import BootClears, draw_outline, first_outline


class Memory:
    start = 0x20800000

    def __init__(self):
        self.data = bytearray(b"\xef\xbe"*24)

    def mem_read(self, address, size):
        offset = address-self.start
        return self.data[offset:offset+size]

    def mem_write(self, address, data):
        offset = address-self.start
        self.data[offset:offset+len(data)] = data


class BootSurfaceTest(unittest.TestCase):
    def test_colored_outline_uses_paint_and_preserves_neighbors(self):
        memory = Memory()
        memory.data = bytearray(970)
        target = memory.start+960
        memory.mem_write(target, pack("<3H", 0x1F, 0x1F, 0xBEEF))
        changed = draw_outline(memory, target, -960, [0, 0, 2, 1],
                               [[(0, 0), (1, 0), (1, 1), (0, 1)]], (0.5, 1, 0, 0), True)
        self.assertEqual(changed, 1)
        self.assertEqual(memory.mem_read(target, 6), pack("<3H", 0x8010, 0x001F, 0xBEEF))

    def test_alpha_fill_uses_two_word_target_format_and_preserves_row_padding(self):
        memory = Memory()
        model = BootClears(memory)
        for word in (0xA0020010, memory.start+36, 0xFFFFFFF4, 3,
                     0xA0010010, memory.start+36, 0xFFFFFFF4, 0xA0000208, 0x0B,
                     0xA0000110, 0x80001000, 0xA001080C, 0x37, 0x400CC,
                     0xA0010814, 0x60001, 0x30001, 0xDA000000):
            model.word(word)
        redrawn = b"\xef\xbe\xef" + b"\x37"*7 + b"\xef\xbe"
        self.assertEqual(memory.data, b"\xef\xbe"*6 + redrawn*2 + b"\xef\xbe"*6)
        self.assertEqual(model.draws[0]["alpha8"], "0x37")

    def test_startup_mask_compositor_uses_source_alpha_and_paint(self):
        memory = Memory()
        memory.data = bytearray(0x500)
        source, target = memory.start+4, memory.start+0x400
        memory.mem_write(source, b"\xff\0")
        memory.mem_write(target, pack("<3H", 0xFFFF, 0xFFFF, 0xBEEF))
        model = BootClears(memory)
        model.registers.update({0x10: target, 0x14: 0xFFFFFC40, 0x18: 3, 0x110: 0x80121051,
                                0x200: source, 0x204: 2, 0x208: 0x0B, 0x210: 0x10000,
                                0x21C: 0x3F800000, 0x220: 0, 0x238: 0, 0x23C: 0x3F800000,
                                0xF0: 0x3F800000, 0xF4: 0x3F800000, 0xF8: 0, 0xFC: 0,
                                0x8000: 0xD00201D2})
        model.outline = ([0, 0, 2, 1], [], 0)
        for word in (0xA002080C, 0, 0, 0x3F800000, 0xD8000000, 0, 0x10000):
            model.word(word)
        self.assertEqual(memory.mem_read(target, 6), pack("<3H", 0xF800, 0xFFFF, 0xBEEF))
        self.assertEqual(model.images[0]["changed_pixels"], 1)
        memory.mem_write(source, b"\xff\x80")
        memory.mem_write(target, pack("<3H", 0, 0x001F, 0xBEEF))
        model.registers[0x8000] = 0x61000092
        model.cover_draw = None
        for word in (0xA002080C, 0, 0, 0x3F800000, 0xD8000000, 0, 0x10000):
            model.word(word)
        self.assertEqual(memory.mem_read(target, 6), pack("<3H", 0xFFFF, 0x841F, 0xBEEF))

    def test_copy_flips_row_order_when_source_and_target_strides_differ(self):
        memory = Memory()
        memory.data[:8] = pack("<4H", 1, 2, 3, 4)
        model = BootClears(memory)
        for word in (0xA0020010, memory.start+12, 0xFFFFFFFC, 3,
                     0xA0020200, memory.start, 4, 3,
                     0xA0000110, 0x80001001, 0xA0020814, 0x10001, 0, 0, 0xDA000000):
            model.word(word)
        self.assertEqual(memory.data[:18], pack("<8H", 1, 2, 3, 4, 3, 4, 1, 2)+b"\xef\xbe")
        self.assertTrue(model.copies[0]["changed"])

    def test_packed_color_copy_reads_rom_and_keeps_four_byte_padding(self):
        source = 0x18AF81E0
        rows = bytes(range(64))*59 + bytes(reversed(range(64)))

        class MemoryWithRom(Memory):
            def mem_read(self, address, size):
                if source <= address < source+len(rows):
                    return rows[address-source:address-source+size]
                return super().mem_read(address, size)

        memory = MemoryWithRom()
        memory.data = bytearray(b"\xff"*(60*64))
        model = BootClears(memory)
        target = memory.start+59*64
        model.registers.update({0x10: target, 0x14: 0xFFFFFFC0, 0x18: 0x41, 0x110: 0x80001001,
                                0x200: source, 0x204: 64, 0x208: 0x41, 0x814: 0xE003B, 0x818: 0, 0x81C: 0})
        model.word(0xDA000000)
        self.assertEqual(memory.mem_read(target, 64), rows[:60]+b"\xff"*4)
        self.assertEqual(memory.mem_read(memory.start, 64), rows[-64:-4]+b"\xff"*4)
        model.registers[0x200] = 0x18BEFFC4  # First row in ROM, but later rows go beyond it.
        with self.assertRaisesRegex(ValueError, "outside its surface"):
            model.word(0xDA000000)
        model.registers.update({0x200: source, 0x10: source+59*64})
        with self.assertRaisesRegex(ValueError, "outside its surface"):
            model.word(0xDA000000)

    def test_color_image_on_384_pixel_surface_clips_row_and_reverses_source_y(self):
        memory = Memory()
        memory.data = bytearray(b"\xff"*0x900)
        target, source = memory.start+768, memory.start+0x800
        memory.mem_write(source, pack("<4I", 0xFFFF0000, 0, 0xFF00FF00, 0))
        model = BootClears(memory)
        model.registers.update({0x10: target, 0x14: 0xFFFFFD00, 0x18: 3, 0x110: 0x80121051,
                                0x200: source, 0x204: 8, 0x208: 0x41, 0x210: 0x10001,
                                0x21C: 0x3F800000, 0x220: 0, 0x238: 0, 0x23C: 0xBF800000,
                                0x8000: 0x61000092})
        model.outline = ([383, 0, 385, 2], [], 0)
        for word in (0xA002080C, 0x3F000000, 0x3FC00000, 0x3F800000,
                     0xD8000000, 0x17F0000, 0x1800001):
            model.word(word)
        self.assertEqual(memory.mem_read(target+766, 4), pack("<2H", 0x07E0, 0xFFFF))
        self.assertEqual(memory.mem_read(target-2, 4), pack("<2H", 0xF800, 0xFFFF))

    def test_outline_bounds_include_curve_extrema_and_ignore_lone_move(self):
        data = bytearray(76*4)
        data[32:48] = pack("<I3f", 0x19023110, 1, 0, 10)
        data[48:64] = pack("<I3f", 0x19023120, 0, 1, 20)
        data[74*4:76*4] = pack("<2I", 0x19002020, 0x30)
        data.extend(pack("<I2f", 0x58000002, 0, 0))
        data.extend(pack("<I4f", 0x5800000A, 2, 8, 4, 0))
        data.extend(pack("<I4f", 0x5800000A, 4, 0, 4, 0)*14)
        data.extend(pack("<I2f", 0x58000004, 4, 0)*2)
        data.extend(pack("<I2fI", 0x58000002, -100, -100, 0x14000001))
        bounds, outlines = first_outline(data)
        self.assertEqual(bounds, [10, 20, 14, 24])
        self.assertIn((12, 24), outlines[0])

    def test_partial_rgb565_fill_preserves_padding_and_neighbors(self):
        memory = Memory()
        model = BootClears(memory)
        for word in (0xA0020010, memory.start+36, 0xFFFFFFF4, 3,
                     0xA0000110, 0x80001000, 0xA000080C, 0xA514A514,
                     0xA0010814, 0x20001, 0x10001, 0xDA000000):
            model.word(word)
        row = b"\xef\xbe"*6
        changed = b"\xef\xbe" + b"\x14\xa5"*3 + b"\xef\xbe"*2
        self.assertEqual(memory.data, row + changed*2 + row)
        self.assertEqual(model.draws[0]["origin"], [1, 1])
