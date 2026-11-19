from struct import pack_into
import unittest

from tools.probe_cs705_menu import MENUS, data_range, find_menu_references


class CS705MenuProbeTests(unittest.TestCase):
    def test_pe_section_uses_raw_bounds(self):
        image = bytearray(256)
        image[:2] = b"MZ"
        pack_into("<I", image, 0x3C, 0x40)
        image[0x40:0x44] = b"PE\0\0"
        pack_into("<H", image, 0x46, 1)
        image[0x58:0x60] = b".data\0\0\0"
        pack_into("<II", image, 0x68, 16, 144)
        self.assertEqual(data_range(image), (144, 160))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            data_range(image[:150])

    def test_menu_link_is_in_the_same_record_and_resolves_to_a_topic(self):
        key = "CL_Common_DispLang"
        jp, en = (label.encode(encoding) for label, encoding in zip(MENUS[key], ("cp932", "ascii")))
        raw_key = key.encode()
        section = en + b"\0(%" + raw_key + b")\0" + jp + b"\t(%" + raw_key + b")\0"
        section += raw_key + b"\t54960.htm\0"
        entry = find_menu_references(section, base=0x200)[key]
        self.assertEqual(entry["label_file_offsets"], {"ascii": [], "cp932": [0x200 + section.index(jp)]})
        self.assertEqual(entry["help_links"], [{"file_offset": 0x200 + section.rindex(raw_key), "topic": "54960.htm"}])


if __name__ == "__main__":
    unittest.main()
