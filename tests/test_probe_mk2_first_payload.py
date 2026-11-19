import unittest
import zlib

from tools.probe_mk2_first_payload import probe_standard


class MK2FirstPayloadTests(unittest.TestCase):
    def test_stream_requires_expected_output_and_no_unknown_tail(self):
        body = b"example payload"
        member = zlib.compress(body)
        self.assertTrue(probe_standard(member, len(body), "zlib")["matches_full_lengths"])
        trailing = probe_standard(member + b"another record", len(body), "zlib")
        self.assertFalse(trailing["matches_full_lengths"])
        self.assertEqual(trailing["consumed_bytes"], len(member))
        self.assertFalse(probe_standard(member, len(body) + 1, "zlib")["matches_full_lengths"])
