import struct
import unittest

from tools.probe_705_a import a32_vectors, periodic_spans, shifted_markers, stable_spans


class GroupAProbeTests(unittest.TestCase):
    def test_periodic_span_exact_boundaries(self):
        data = b"start" + bytes(range(256)) * 17 + b"end"
        span, = periodic_spans(data)
        self.assertEqual((span["start"], span["end_exclusive"], span["distinct_bytes_in_motif"]),
                         (5, 5 + 17 * 256, 256))
        self.assertEqual(list(a32_vectors(data)), [])

    def test_vectors_allow_unaligned_file_offset_and_ignore_reserved_slot(self):
        branch_to_self, load_local_literal = 0xEAFFFFFE, 0xE59FF014
        data = b"\x00" + struct.pack("<10I", branch_to_self, load_local_literal,
                                    branch_to_self, branch_to_self, branch_to_self, 0,
                                    branch_to_self, branch_to_self, 0, 0xE12FFF1E)
        hit, = a32_vectors(data)
        self.assertEqual(hit["offset"], 1)
        self.assertEqual(hit["slots"][1], {"offset": 5, "kind": "literal", "target": 33})
        self.assertEqual(list(a32_vectors(data[:21])), [])

    def test_stability_requires_every_version_and_merges_complete_blocks(self):
        first = b"a" * 4096 + b"b" * 8192 + b"partial"
        second = b"x" + first[1:]
        self.assertEqual(list(stable_spans([first, first, second])),
                         [{"start": 4096, "end_exclusive": 12288}])

    def test_marker_alignment_excludes_marker_bytes(self):
        def span(offset, motif):
            return {"start": offset, "end_exclusive": offset + 1, "bytes": 1, "motif_sha256": motif}

        result, = shifted_markers(b"aXZb..", b".aXYb.", [span(0, "a"), span(3, "b")],
                                  [span(1, "a"), span(4, "b")])
        self.assertEqual((result["shift_bytes"], result["gap_bytes"], result["equal_gap_bytes_shifted"]), (1, 2, 1))
