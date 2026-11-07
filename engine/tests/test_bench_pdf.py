import hashlib
import unittest
import zlib

from engine.tests import bench_pdf
from kb import scan_tool


def streams(data):
    reader = {"incomplete": False, "steps": scan_tool.MAX_READ_STEPS, "objects": 0, "unfinished": 0}
    found = list(scan_tool._streams(data, reader))
    return found, reader


class LargeImagesTest(unittest.TestCase):
    def test_the_same_arguments_give_the_same_bytes_and_another_seed_gives_other_bytes(self):
        a = bench_pdf.large_images(3_000_000, 4, seed=7)
        self.assertEqual(hashlib.sha256(a).digest(), hashlib.sha256(bench_pdf.large_images(3_000_000, 4, seed=7)).digest())
        self.assertNotEqual(a, bench_pdf.large_images(3_000_000, 4, seed=8))

    def test_the_file_is_the_stated_size_within_one_percent_and_holds_the_stated_number_of_images(self):
        for total, count in ((3_000_000, 4), (6_000_000, 30), (4_000_000, 1), (8_000_000, 100)):
            data = bench_pdf.large_images(total, count, seed=1)
            self.assertLess(abs(len(data) - total), total * 0.001, (total, count, len(data)))  # within a tenth of a percent: compression adds a little to noise
            found, reader = streams(data)
            self.assertEqual((len(found), reader["incomplete"]), (count, False), (total, count))

    def test_each_stream_is_an_image_of_the_scans_own_rule_that_decodes_past_the_per_stream_limit(self):
        data = bench_pdf.large_images(3_000_000, 3, seed=2, zeros=3_000_000)
        found, _ = streams(data)
        for located, blob in found:
            self.assertTrue(scan_tool._is_image(located[2]), located[2])
            self.assertEqual(scan_tool._FILTER_VALUE.search(located[2]).group(1), b"/FlateDecode")
            out = zlib.decompressobj().decompress(blob, 10_000_000)
            self.assertGreaterEqual(len(out), 3_000_000)
            self.assertTrue(out.endswith(bytes(1000)))

    def test_the_scan_calls_every_one_of_them_a_large_image_when_the_budget_allows(self):
        data = bench_pdf.large_images(2_000_000, 5, seed=3)
        kinds = {c["kind"]: c["count"] for c in scan_tool.scan_pdf(data)}
        self.assertEqual(kinds, {"large_image_streams": 5})

    def test_the_arguments_are_checked(self):
        for bad in ((0, 1), (1_000_000, 0), (1_000, 5), (3_000_000, -1), (1_000_000, 500)):  # the last: 500 images cannot fit in a megabyte
            with self.assertRaises(ValueError):
                bench_pdf.large_images(*bad)


class ExpandingStreamsTest(unittest.TestCase):
    def test_the_same_arguments_give_the_same_bytes(self):
        a = bench_pdf.expanding_streams(300_000)
        self.assertEqual(hashlib.sha256(a).digest(), hashlib.sha256(bench_pdf.expanding_streams(300_000)).digest())

    def test_the_file_is_the_stated_size_within_one_percent_and_each_stream_expands_about_a_thousandfold(self):
        total = 400_000
        data = bench_pdf.expanding_streams(total)
        self.assertLess(abs(len(data) - total), total * 0.01, len(data))
        found, reader = streams(data)
        self.assertGreater(len(found), 100)
        self.assertFalse(reader["incomplete"])
        for located, blob in found[:20]:
            out = zlib.decompressobj().decompress(blob, 10_000_000)
            self.assertGreaterEqual(len(out) / len(blob), 900, (len(out), len(blob)))
            self.assertNotIn(b"/Subtype", located[2])  # not an image: a plain flate stream

    def test_the_arguments_are_checked(self):
        for bad in (0, 100, -5):
            with self.assertRaises(ValueError):
                bench_pdf.expanding_streams(bad)


class TinyStreamsTest(unittest.TestCase):
    def test_the_same_arguments_give_the_same_bytes_and_another_seed_gives_other_bytes(self):
        a = bench_pdf.tiny_streams(200_000, seed=3)
        self.assertEqual(hashlib.sha256(a).digest(), hashlib.sha256(bench_pdf.tiny_streams(200_000, seed=3)).digest())
        self.assertNotEqual(a, bench_pdf.tiny_streams(200_000, seed=4))

    def test_the_file_is_the_stated_size_within_one_percent_and_holds_many_small_flate_streams(self):
        total = 300_000
        data = bench_pdf.tiny_streams(total)
        self.assertLess(abs(len(data) - total), total * 0.01, len(data))
        found, reader = streams(data)
        self.assertGreater(len(found), 1000)
        self.assertFalse(reader["incomplete"])
        for located, blob in found[:50]:
            self.assertLess(len(blob), 200)
            self.assertEqual(len(zlib.decompressobj().decompress(blob, 10_000)), 100)
            self.assertNotIn(b"/Subtype", located[2])

    def test_the_streams_differ_from_one_another(self):
        found, _ = streams(bench_pdf.tiny_streams(100_000))
        self.assertGreater(len({blob for _, blob in found}), len(found) * 0.99)

    def test_the_arguments_are_checked(self):
        for bad in ((0,), (100,), (-5,), (100_000, 1, 0)):
            with self.assertRaises(ValueError):
                bench_pdf.tiny_streams(*bad)


if __name__ == "__main__":
    unittest.main()
