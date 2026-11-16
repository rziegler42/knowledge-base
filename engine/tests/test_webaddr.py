"""Canonical addresses, hosts and sites (`kb/webaddr.py`, Increment A of the plan `2026-11-16-harden-the-fetch-for-the-unattended-crawl`).

One module canonicalises every address and host the unattended crawl handles, so that identity keys, blacklist and list matches and per-site counters agree. Nothing here touches the network.
Run them with `python3 -W error::ResourceWarning -m unittest engine.tests.test_webaddr`."""
import os
import re
import stat
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR  # noqa: F401  (puts the engine folder on the import path)

from kb import capture_arxiv, identity, webaddr

PSL = """// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// ===BEGIN ICANN DOMAINS===

com
uk
co.uk
de
ck
*.ck
!www.ck
jp
*.kobe.jp
!city.kobe.jp
ac.jp
xn--55qx5d.cn   // a rule with a comment after it
公司.cn
// ===END ICANN DOMAINS===
// ===BEGIN PRIVATE DOMAINS===
github.io
blogspot.com
// ===END PRIVATE DOMAINS===
"""


class CanonHost(unittest.TestCase):
    def test_a_name_is_lower_cased_and_one_trailing_dot_is_stripped(self):
        for given, wanted in (("Example.COM", "example.com"), ("example.com.", "example.com"), ("WWW.Example.Com.", "www.example.com"), ("a.b.c.example.org", "a.b.c.example.org")):
            with self.subTest(given):
                self.assertEqual(webaddr.canon_host(given), wanted)

    def test_more_than_one_trailing_dot_a_leading_dot_and_an_empty_label_are_refused(self):
        for bad in ("example.com..", ".example.com", "a..b.com", ".", "..", ""):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_host(bad)

    def test_an_international_name_becomes_its_ascii_form_in_every_spelling(self):
        self.assertEqual(webaddr.canon_host("bücher.example"), "xn--bcher-kva.example")
        self.assertEqual(webaddr.canon_host("BÜCHER.Example."), "xn--bcher-kva.example")
        self.assertEqual(webaddr.canon_host("xn--bcher-kva.example"), "xn--bcher-kva.example")
        self.assertEqual(webaddr.canon_host("XN--BCHER-KVA.EXAMPLE"), "xn--bcher-kva.example")
        self.assertEqual(webaddr.canon_host("bücher.example"), "xn--bcher-kva.example")   # the same name written with a combining mark

    def test_a_character_where_the_two_standards_differ_is_refused_and_not_mapped(self):
        for bad in ("fa\u00dfe.de", "\u03c2.gr", "a\u200db.example", "a\u200cb.example", "a\u3002b.example"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_host(bad)

    def test_a_name_that_is_not_a_hostname_is_refused(self):
        for bad in ("exa mple.com", "example.com/path", "example.com:80", "user@example.com", "example.com?x", "example.com#x", "-a.example.com", "a-.example.com",
                    "under_score.example.com", "ex\x00ample.com", "ex\nample.com", "evil\u202e.com", "evil\u2028.com", "a" * 64 + ".com", ".".join(["a" * 60] * 5) + ".com", "%65xample.com"):
            with self.subTest(bad[:30]):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_host(bad)

    def test_the_longest_allowed_label_and_name_pass(self):
        self.assertEqual(webaddr.canon_host("a" * 63 + ".com"), "a" * 63 + ".com")
        name = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61])
        self.assertEqual(len(name), 253)
        self.assertEqual(webaddr.canon_host(name), name)
        with self.assertRaises(webaddr.AddressError):
            webaddr.canon_host(name + "e")

    def test_a_punycode_label_that_decodes_to_a_name_that_would_not_be_canonical_is_refused(self):
        for text in ("\u00dcber", "fa\u00dfe", "\u03c2", "bu\u0308cher", "a\u200db"):
            label = "xn--" + text.encode("punycode").decode("ascii")
            with self.subTest(text):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_host(label + ".example")

    def test_a_punycode_label_that_is_not_canonical_or_does_not_decode_to_a_real_name_is_refused(self):
        for bad in ("xn--.example", "xn--a.example", "xn--zz.example", "xn--999999999.example", "xn--abc-.example", "xn--bcher-kva-.example", "xn--0.example"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_host(bad)

    def test_a_bare_number_or_a_legacy_spelling_of_an_ipv4_address_is_refused(self):
        for bad in ("2130706433", "127.1", "0x7f.1", "0177.0.0.1", "1.2.3", "999.1.1.1", "0x7f000001", "127.0.0.1.5", "093.184.216.34", "1.2.3.04", "00.0.0.1"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_host(bad)

    def test_an_address_in_its_canonical_form_is_kept(self):
        self.assertEqual(webaddr.canon_host("93.184.216.34"), "93.184.216.34")
        self.assertEqual(webaddr.canon_host("::1"), "::1")
        self.assertEqual(webaddr.canon_host("[::1]"), "::1")
        self.assertEqual(webaddr.canon_host("2001:DB8:0:0:0:0:0:1"), "2001:db8::1")
        self.assertEqual(webaddr.canon_host("[2001:DB8::1]"), "2001:db8::1")

    def test_an_ipv6_address_with_a_zone_or_an_unbalanced_bracket_is_refused(self):
        for bad in ("fe80::1%eth0", "[::1", "::1]", "[[::1]]", "[example.com]"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_host(bad)

    def test_something_that_is_not_text_is_refused(self):
        for bad in (None, 5, b"example.com", ["example.com"]):
            with self.subTest(repr(bad)):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_host(bad)

    def test_canonicalising_twice_changes_nothing(self):
        for name in ("Example.COM.", "bücher.example", "XN--BCHER-KVA.EXAMPLE", "[2001:DB8::1]", "93.184.216.34"):
            once = webaddr.canon_host(name)
            self.assertEqual(webaddr.canon_host(once), once, name)


class CanonAddress(unittest.TestCase):
    def test_only_http_and_https_are_accepted(self):
        for bad in ("ftp://example.com/x", "file:///etc/passwd", "data:text/html,hi", "javascript:alert(1)", "example.com/x", "//example.com/x", "mailto:a@example.com", "HTTPS:/example.com", ""):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_address(bad)

    def test_the_scheme_and_host_are_lower_cased_and_the_host_is_canonical(self):
        self.assertEqual(webaddr.canon_address("HTTP://EXAMPLE.com./a/B?Q=1"), "http://example.com/a/B?Q=1")
        self.assertEqual(webaddr.canon_address("https://bücher.example/stra\u00dfe"), "https://xn--bcher-kva.example/stra%C3%9Fe")

    def test_credentials_in_the_address_are_refused(self):
        for bad in ("http://user:pass@example.com/", "http://user@example.com/", "http://:pass@example.com/", "https://@example.com/"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_address(bad)

    def test_the_default_port_is_dropped_and_any_other_port_is_refused(self):
        self.assertEqual(webaddr.canon_address("http://example.com:80/x"), "http://example.com/x")
        self.assertEqual(webaddr.canon_address("https://example.com:443/x"), "https://example.com/x")
        self.assertEqual(webaddr.canon_address("http://example.com:/x"), "http://example.com/x")
        for bad in ("http://example.com:8080/", "https://example.com:8443/", "http://example.com:443/", "https://example.com:80/", "http://example.com:0/", "http://example.com:65536/",
                    "http://example.com:abc/", "http://example.com:22/", "http://example.com:-1/"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_address(bad)

    def test_the_fragment_is_dropped_and_an_empty_path_is_a_slash(self):
        self.assertEqual(webaddr.canon_address("http://example.com/a#frag"), "http://example.com/a")
        self.assertEqual(webaddr.canon_address("http://example.com"), "http://example.com/")
        self.assertEqual(webaddr.canon_address("http://example.com?x=1"), "http://example.com/?x=1")
        self.assertEqual(webaddr.canon_address("http://example.com/#x"), "http://example.com/")

    def test_every_utm_and_mc_parameter_and_fbclid_and_gclid_are_removed_and_the_rest_keep_their_order(self):
        given = "http://example.com/p?utm_source=a&x=1&UTM_Medium=b&mc_cid=1&mc_foo=2&fbclid=x&GCLID=y&gclid=z&y=2&x=3&utm_&mc_"
        self.assertEqual(webaddr.canon_address(given), "http://example.com/p?x=1&y=2&x=3")
        self.assertEqual(webaddr.canon_address("http://example.com/p?utm_source&x"), "http://example.com/p?x")
        self.assertEqual(webaddr.canon_address("http://example.com/p?utm_source=a&fbclid=b"), "http://example.com/p")
        self.assertEqual(webaddr.canon_address("http://example.com/p?utm_source=a&"), "http://example.com/p")

    def test_empty_parts_of_a_query_are_dropped_and_a_question_mark_inside_it_is_kept(self):
        self.assertEqual(webaddr.canon_address("http://example.com/p?x=1&&y=2&"), "http://example.com/p?x=1&y=2")
        self.assertEqual(webaddr.canon_address("http://example.com/p?a=b?c=d"), "http://example.com/p?a=b?c=d")
        self.assertEqual(webaddr.canon_address("http://example.com/p?a=b%3Dc"), "http://example.com/p?a=b%3Dc")

    def test_a_parameter_that_only_looks_like_a_tracking_one_is_kept(self):
        self.assertEqual(webaddr.canon_address("http://example.com/p?utm=1&mc=2&xutm_a=3&mcx_1=4&gclid2=5&fbclid_=6"), "http://example.com/p?utm=1&mc=2&xutm_a=3&mcx_1=4&gclid2=5&fbclid_=6")

    def test_dot_segments_are_removed_and_encoded_dots_are_not_decoded(self):
        for given, wanted in (("/a/./b/../c", "/a/c"), ("/../a", "/a"), ("/a/..", "/"), ("/a/b/../../..", "/"), ("/a/./", "/a/"), ("/..", "/"), ("/../..", "/"), ("/a/../..", "/"), ("/a/.", "/a/"), ("/a/b/.", "/a/b/"), ("/./", "/"), ("/a//b", "/a//b"), ("/a/%2e%2e/b", "/a/%2E%2E/b"), ("/a/b%2E", "/a/b%2E")):
            with self.subTest(given):
                self.assertEqual(webaddr.canon_address("http://example.com" + given), "http://example.com" + wanted)

    def test_percent_escapes_are_upper_case_and_non_ascii_is_encoded_and_a_stray_percent_is_refused(self):
        self.assertEqual(webaddr.canon_address("http://example.com/a%2fb%c3%a9"), "http://example.com/a%2Fb%C3%A9")
        self.assertEqual(webaddr.canon_address("http://example.com/é?q=ü"), "http://example.com/%C3%A9?q=%C3%BC")
        for bad in ("http://example.com/100%", "http://example.com/%zz", "http://example.com/a?q=%4"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_address(bad)

    def test_whitespace_control_and_bidirectional_characters_are_refused_not_stripped(self):
        for bad in (" http://example.com/", "http://example.com/ ", "http://exa mple.com/", "http://example.com/a b", "http://example.com/a\nb", "http://example.com/a\x00b", "http://example.com/a\x7fb",
                    "http://example.com/\u202e", "http://example.com/a\u2028b", "http://example.com/a\u200bb", "http://example.com/a\u2066b", "http://example.com/\ufeff"):
            with self.subTest(repr(bad)):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_address(bad)

    def test_an_address_of_2048_characters_passes_and_one_more_is_refused(self):
        base = "http://example.com/"
        ok = base + "a" * (2048 - len(base))
        self.assertEqual(len(webaddr.canon_address(ok)), 2048)
        with self.assertRaises(webaddr.AddressError):
            webaddr.canon_address(ok + "a")

    def test_a_long_fragment_is_refused_though_it_would_be_dropped(self):
        with self.assertRaises(webaddr.AddressError):
            webaddr.canon_address("http://example.com/#" + "a" * 3000)

    def test_an_ipv6_address_without_brackets_is_refused_even_with_a_port(self):
        for bad in ("http://::1:80/", "http://::1:/", "http://::1/", "http://2001:db8::1/", "http://a:b:80/"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_address(bad)

    def test_a_tracking_name_written_with_escapes_is_removed_and_escaped_unreserved_characters_are_decoded(self):
        self.assertEqual(webaddr.canon_address("http://example.com/p?utm%5Fsource=a&%75tm_x=1&%47clid=2&x=1"), "http://example.com/p?x=1")
        self.assertEqual(webaddr.canon_address("http://example.com/a%7Eb%41%2d%5f%30"), "http://example.com/a~bA-_0")
        self.assertEqual(webaddr.canon_address("http://example.com/p?k=%41%7e"), "http://example.com/p?k=A~")
        self.assertEqual(webaddr.canon_address("http://example.com/a%2eb%2F%3D"), "http://example.com/a%2Eb%2F%3D")   # a dot, a slash and an equals sign keep their escapes

    def test_a_very_long_text_is_refused_before_it_is_examined(self):
        with mock.patch.object(webaddr, "_check_text", side_effect=AssertionError("looked at the text first")):
            with self.assertRaises(webaddr.AddressError):
                webaddr.canon_address("http://example.com/" + "a" * 5000)
            with self.assertRaises(webaddr.AddressError):
                webaddr.canon_host("a" * 5000)

    def test_a_port_in_other_digits_or_after_an_ipv6_host_is_refused(self):
        for bad in ("http://example.com:\u0668\u0660/", "http://[::1]:80x/", "http://[::1]x/", "http://[::1]:8080/"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_address(bad)

    def test_an_address_that_grows_past_the_limit_when_canonicalised_is_refused(self):
        with self.assertRaises(webaddr.AddressError):
            webaddr.canon_address("http://example.com/" + "é" * 700)   # each é becomes six characters

    def test_an_ip_literal_is_kept_and_a_bare_number_host_is_refused(self):
        self.assertEqual(webaddr.canon_address("http://[::1]/x"), "http://[::1]/x")
        self.assertEqual(webaddr.canon_address("http://[2001:DB8::1]:80/"), "http://[2001:db8::1]/")
        self.assertEqual(webaddr.canon_address("http://93.184.216.34/"), "http://93.184.216.34/")
        for bad in ("http://2130706433/", "http://0x7f.1/", "http://127.1/", "http://0177.0.0.1/", "http://[fe80::1%25eth0]/", "http://[::1/"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_address(bad)

    def test_a_host_written_with_percent_escapes_is_refused(self):
        with self.assertRaises(webaddr.AddressError):
            webaddr.canon_address("http://%31%32%37.0.0.1/")

    def test_one_address_in_many_spellings_gives_one_result(self):
        spellings = ["http://evil.com/x", "http://evil.com./x", "HTTP://EVIL.com/x", "http://evil.com:80/x", "http://evil.com/x#top", "http://evil.com/a/../x", "http://EVIL.COM.:80/./x#y"]
        self.assertEqual({webaddr.canon_address(s) for s in spellings}, {"http://evil.com/x"})
        self.assertEqual(webaddr.canon_address("http://bücher.example/a"), webaddr.canon_address("http://XN--BCHER-KVA.example./a"))

    def test_canonicalising_twice_changes_nothing_and_the_existing_normaliser_agrees(self):
        samples = ["http://Example.COM./a/./b/../c?utm_source=x&y=1#f", "https://bücher.example/stra\u00dfe?q=ü", "http://example.com", "http://[2001:DB8::1]/a%2fb", "https://example.com:443/p?x=1&x=2",
                   "http://93.184.216.34/a/b/../c", "http://example.com/a%C3%A9"]
        for s in samples:
            with self.subTest(s):
                once = webaddr.canon_address(s)
                self.assertEqual(webaddr.canon_address(once), once)
                self.assertEqual(identity.normalize_address(once), once)

    def test_something_that_is_not_text_is_refused(self):
        for bad in (None, 5, b"http://example.com/", ["http://example.com/"]):
            with self.subTest(repr(bad)):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.canon_address(bad)


class IdentityKey(unittest.TestCase):
    def test_a_page_is_its_canonical_address(self):
        self.assertEqual(webaddr.identity_key("HTTP://Example.com./a/./b?utm_source=x#f"), "http://example.com/a/b")

    def test_every_spelling_of_an_arxiv_paper_is_one_key_without_the_version(self):
        for given in ("2101.00001", "2101.00001v3", "arXiv:2101.00001v2", "ARXIV:2101.00001", "https://arxiv.org/abs/2101.00001v2", "http://export.arxiv.org/abs/2101.00001",
                      "https://arxiv.org/pdf/2101.00001v1.pdf", "https://arxiv.org/pdf/2101.00001", "https://www.arxiv.org/abs/2101.00001", "https://arxiv.org/abs/2101.00001?context=cs"):
            with self.subTest(given):
                self.assertEqual(webaddr.identity_key(given), "arxiv:2101.00001")

    def test_an_old_style_arxiv_id_is_a_key_in_every_spelling(self):
        for given in ("hep-th/9901001", "hep-th/9901001v2", "arXiv:hep-th/9901001", "https://arxiv.org/abs/hep-th/9901001v2", "https://arxiv.org/pdf/hep-th/9901001.pdf"):
            with self.subTest(given):
                self.assertEqual(webaddr.identity_key(given), "arxiv:hep-th/9901001")

    def test_the_arxiv_id_forms_agree_with_the_capture_parser(self):
        accepted = ["2101.00001", "2101.00001v3", "hep-th/9901001", "hep-th/9901001v2", "arXiv:2101.00001", "ARXIV:hep-th/9901001v1"]
        refused = ["2113.00001", "2101.000", "2101.000001", "cs/0112017x", "2101.00001v0", "arxiv:2101.00001v", "HEP-TH/9901001", "2101.00001 ", " 2101.00001", "arXiv: 2101.00001"]
        for given in accepted:
            with self.subTest(given):
                self.assertEqual(webaddr.identity_key(given), "arxiv:" + capture_arxiv.parse_id(given)[0])
        for given in refused:
            with self.subTest(given):
                with self.assertRaises(Exception):
                    capture_arxiv.parse_id(given)
                try:
                    key = webaddr.identity_key(given)
                except webaddr.AddressError:
                    continue
                self.assertFalse(key.startswith("arxiv:"), given)   # an id the capture parser refuses is never turned into an arXiv key

    def test_an_address_that_looks_like_arxiv_on_another_host_is_a_page(self):
        self.assertEqual(webaddr.identity_key("https://example.com/abs/2101.00001"), "https://example.com/abs/2101.00001")
        self.assertEqual(webaddr.identity_key("https://arxiv.org.evil.example/abs/2101.00001"), "https://arxiv.org.evil.example/abs/2101.00001")

    def test_an_arxiv_address_that_is_not_a_paper_is_an_ordinary_page(self):
        self.assertEqual(webaddr.identity_key("https://arxiv.org/list/cs.AI/recent"), "https://arxiv.org/list/cs.AI/recent")

    def test_a_doi_is_never_a_key(self):
        for bad in ("10.1000/xyz123", "doi:10.1000/xyz123", "DOI: 10.1000/xyz", "https://doi.org/10.1000/xyz123", "http://dx.doi.org/10.1000/xyz123", "https://DOI.org/10.1000/x"):
            with self.subTest(bad):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.identity_key(bad)

    def test_something_that_is_neither_an_arxiv_id_nor_an_address_is_refused(self):
        for bad in ("", "just some words", None, 5, "2101.0001x", "arXiv:", "https://"):
            with self.subTest(repr(bad)):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.identity_key(bad)


class SiteOf(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.path = os.path.join(self.dir, "psl.dat")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(PSL)
        self.suffixes = webaddr.load_suffixes(self.path)

    def test_the_registrable_domain_is_the_public_suffix_and_one_more_label(self):
        for host, wanted in (("www.example.com", "example.com"), ("example.com", "example.com"), ("a.b.example.co.uk", "example.co.uk"), ("example.co.uk", "example.co.uk"),
                             ("foo.github.io", "foo.github.io"), ("a.b.foo.github.io", "foo.github.io"), ("x.blogspot.com", "x.blogspot.com"), ("a.b.zzz", "b.zzz")):
            with self.subTest(host):
                self.assertEqual(webaddr.site_of(host, self.suffixes), wanted)

    def test_a_host_that_is_itself_a_public_suffix_is_its_own_site(self):
        for host in ("co.uk", "com", "github.io", "uk"):
            with self.subTest(host):
                self.assertEqual(webaddr.site_of(host, self.suffixes), host)

    def test_wildcard_and_exception_rules(self):
        for host, wanted in (("x.y.ck", "x.y.ck"), ("a.x.y.ck", "x.y.ck"), ("y.ck", "y.ck"), ("www.ck", "www.ck"), ("a.www.ck", "www.ck"), ("city.kobe.jp", "city.kobe.jp"),
                             ("a.city.kobe.jp", "city.kobe.jp"), ("x.other.kobe.jp", "x.other.kobe.jp"), ("a.b.ac.jp", "b.ac.jp")):
            with self.subTest(host):
                self.assertEqual(webaddr.site_of(host, self.suffixes), wanted)

    def test_a_name_is_canonicalised_before_the_lookup_and_an_international_name_works(self):
        self.assertEqual(webaddr.site_of("WWW.Example.COM.", self.suffixes), "example.com")
        self.assertEqual(webaddr.site_of("www.bücher.de", self.suffixes), "xn--bcher-kva.de")
        self.assertEqual(webaddr.site_of("a.b.公司.cn", self.suffixes), "b.xn--55qx5d.cn")

    def test_an_ip_literal_is_its_own_site(self):
        self.assertEqual(webaddr.site_of("93.184.216.34", self.suffixes), "93.184.216.34")
        self.assertEqual(webaddr.site_of("[2001:DB8::1]", self.suffixes), "2001:db8::1")
        self.assertEqual(webaddr.site_of("93.184.216.34"), "93.184.216.34")

    def test_without_a_suffix_list_it_is_the_last_two_labels_and_says_so(self):
        self.assertEqual(webaddr.site_of("www.example.com"), "example.com")
        self.assertEqual(webaddr.site_of("a.b.example.co.uk"), "co.uk")
        self.assertEqual(webaddr.site_info("a.b.example.co.uk"), ("co.uk", False))
        self.assertEqual(webaddr.site_info("www.example.com", None), ("example.com", False))
        self.assertEqual(webaddr.site_info("www.example.com", frozenset()), ("example.com", False))   # an empty list is no list
        self.assertEqual(webaddr.site_info("www.example.com", self.suffixes), ("example.com", True))
        self.assertEqual(webaddr.site_info("93.184.216.34"), ("93.184.216.34", True))
        self.assertEqual(webaddr.site_of("com"), "com")
        self.assertEqual(webaddr.site_of("localhost"), "localhost")

    def test_a_host_that_is_not_a_hostname_is_refused(self):
        for bad in ("", "a..b", "example.com/x", None):
            with self.subTest(repr(bad)):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.site_of(bad, self.suffixes)

    def test_the_rules_are_read_as_data(self):
        self.assertIn("co.uk", self.suffixes)
        self.assertIn("*.ck", self.suffixes)
        self.assertIn("!www.ck", self.suffixes)
        self.assertIn("xn--55qx5d.cn", self.suffixes)   # a rule written in the file in Unicode is kept in its ASCII form
        self.assertIn("github.io", self.suffixes)
        self.assertNotIn("", self.suffixes)
        self.assertFalse([r for r in self.suffixes if "//" in r or " " in r])
        self.assertIsInstance(self.suffixes, frozenset)

    def test_a_missing_file_a_link_a_folder_a_pipe_an_oversize_file_and_bad_text_are_refused(self):
        with self.assertRaises(webaddr.AddressError):
            webaddr.load_suffixes(os.path.join(self.dir, "missing"))
        for odd in ("a\x00b", None, 5):
            with self.subTest(repr(odd)):
                with self.assertRaises(webaddr.AddressError):
                    webaddr.load_suffixes(odd)
        with mock.patch.object(webaddr.os, "read", side_effect=OSError(5, "Input/output error")):
            with self.assertRaises(webaddr.AddressError):
                webaddr.load_suffixes(self.path)
        link = os.path.join(self.dir, "link")
        os.symlink(self.path, link)
        with self.assertRaises(webaddr.AddressError):
            webaddr.load_suffixes(link)
        with self.assertRaises(webaddr.AddressError):
            webaddr.load_suffixes(self.dir)
        fifo = os.path.join(self.dir, "fifo")
        os.mkfifo(fifo)
        with self.assertRaises(webaddr.AddressError):
            webaddr.load_suffixes(fifo)
        big = os.path.join(self.dir, "big")
        with open(big, "w") as f:
            f.write("com\n" * 300)
        with mock.patch.object(webaddr, "MAX_SUFFIX_BYTES", 1000):
            with self.assertRaises(webaddr.AddressError):
                webaddr.load_suffixes(big)
        self.assertEqual(webaddr.load_suffixes(big), frozenset({"com"}))   # the same file is fine under the real limit
        bad = os.path.join(self.dir, "bad")
        with open(bad, "wb") as f:
            f.write(b"com\n\xff\xfe\n")
        with self.assertRaises(webaddr.AddressError):
            webaddr.load_suffixes(bad)
        many = os.path.join(self.dir, "many")
        with open(many, "w") as f:
            f.write("".join("r%d.example\n" % n for n in range(11)))
        with mock.patch.object(webaddr, "MAX_SUFFIX_RULES", 10):
            with self.assertRaises(webaddr.AddressError):
                webaddr.load_suffixes(many)
        self.assertEqual(len(webaddr.load_suffixes(many)), 11)

    def test_a_line_that_is_not_a_rule_is_ignored_and_an_empty_file_is_an_empty_set(self):
        junk = os.path.join(self.dir, "junk")
        with open(junk, "w") as f:
            f.write("// a comment\n\n   \ncom\nnot a rule here\nbad_rule\n*.\n!\n..\n*.*.x\ncom  \t// trailing\n")
        rules = webaddr.load_suffixes(junk)
        self.assertEqual(rules, frozenset({"com", "not"}))
        empty = os.path.join(self.dir, "empty")
        open(empty, "w").close()
        self.assertEqual(webaddr.load_suffixes(empty), frozenset())

    def test_the_file_is_opened_without_following_a_link_and_the_mode_does_not_matter(self):
        os.chmod(self.path, 0o444)
        self.assertTrue(webaddr.load_suffixes(self.path))
        self.assertTrue(stat.S_ISREG(os.stat(self.path).st_mode))


class NoNetwork(unittest.TestCase):
    def test_the_module_makes_no_request_and_imports_no_network_code(self):
        source = open(os.path.join(ENGINE_DIR, "kb", "webaddr.py"), encoding="utf-8").read()
        for word in ("import socket", "urllib.request", "http.client", "import ssl", "urlopen", "subprocess", "import requests"):
            self.assertNotIn(word, source, word)
        self.assertIsNotNone(re.search(r"^from \. import .*KbError", source, re.M))


if __name__ == "__main__":
    unittest.main()
