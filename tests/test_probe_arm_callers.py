import unittest

from tools.probe_arm_callers import probe


class ArmCallerTests(unittest.TestCase):
    def test_arm_and_unaligned_thumb_branch_to_same_arm_function(self):
        # Linked with Arm GNU as/ld, checked against objdump. Thumb is at PC mod 4 = 2.
        data = bytes.fromhex("1eff2fe1 fdffffeb fcffffea 00bf fff7f8ef 00bf 00500020")
        self.assertEqual(probe(data, 0x20005000, [0x20005000]), {
            "0x20005000": {"a32_bl": ["0x20005004"], "a32_b": ["0x20005008"],
                           "t32_blx": ["0x2000500e"], "aligned_literals": ["0x20005014"]},
        })
