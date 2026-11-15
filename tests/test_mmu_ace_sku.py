"""The ACE RFID SKU format: parsing, vendor prefixes and the spool ID a tag claims.

mmu_ace_sku is pure (stdlib only), so it is loaded here by file path with no
Moonraker shims; the controller and matcher tests that go through it live in
test_mmu_ace.py.
"""

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "files/4-apps/home/rinkhals/apps/40-moonraker/mmu_ace_sku.py"
)


def load_sku_module():
    spec = importlib.util.spec_from_file_location("mmu_ace_sku_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SKU = load_sku_module()


class MmuAceSkuParserTests(unittest.TestCase):
    """SkuFormat.parse and the sku_vendor_prefixes setting (SkuFormat.parse_prefixes)."""

    def parse(self, sku, prefixes=None):
        return SKU.SkuFormat(prefixes).parse(sku)

    def test_a_configured_vendor_letter_is_stripped_and_named(self):
        info = self.parse("THPLBR-1", {"A": "Anycubic", "T": "Tinmorry"})

        self.assertEqual(
            (info["vendor"], info["material_type"], info["series"],
             info["color_name"], info["serial"]),
            ("Tinmorry", "PLA", "Basic", "Brown", "1"))

    def test_an_unconfigured_letter_is_not_a_vendor(self):
        self.assertEqual(self.parse("THPLBR-1")["vendor"], "")

    def test_high_speed_pla(self):
        info = self.parse("AHHSBK-102")

        self.assertEqual((info["vendor"], info["material_type"], info["series"],
                          info["color_name"]),
                         ("Anycubic", "PLA", "High Speed", "Black"))

    def test_pla_plus_wins_over_plain_pla(self):
        info = self.parse("AHPLPBK-102")

        self.assertEqual((info["material_type"], info["series"], info["color_name"]),
                         ("PLA", "Plus", "Black"))

    def test_a_sku_without_a_vendor_letter_is_still_anycubic(self):
        # Anycubic sometimes omits the A: an empty vendor code before the H.
        info = self.parse("HPL18-105")

        self.assertEqual((info["vendor"], info["material_type"], info["series"], info["serial"]),
                         ("Anycubic", "PLA", "Basic", "105"))

    def test_a_multi_letter_vendor_code(self):
        info = self.parse("ATHPLBK-4", {"A": "Anycubic", "AT": "Atomic"})

        self.assertEqual((info["vendor"], info["material_type"], info["series"],
                          info["color_name"], info["serial"]),
                         ("Atomic", "PLA", "Basic", "Black", "4"))

    def test_an_unconfigured_multi_letter_vendor_still_parses_the_filament(self):
        info = self.parse("ATHPLBK-4")

        self.assertEqual((info["vendor"], info["material_type"], info["color_name"]),
                         ("", "PLA", "Black"))

    def test_the_vendor_ends_at_the_first_h(self):
        # Everything after the first H is the filament, even a later H.
        info = self.parse("AHHSBK-102")

        self.assertEqual((info["vendor"], info["series"]), ("Anycubic", "High Speed"))

    def test_purple_pla_basic_is_not_pla_plus(self):
        # PLPO could be PLP + O or PL + PO; only the second leaves a colour code.
        info = self.parse("AHPLPO-105")

        self.assertEqual((info["material_type"], info["series"], info["color_name"]),
                         ("PLA", "Basic", "Purple"))

    def test_petg_translucent_codes(self):
        for sku in ("AHPETG-101", "AHPETK-102"):
            with self.subTest(sku=sku):
                info = self.parse(sku)
                self.assertEqual((info["material_type"], info["series"]),
                                 ("PETG", "Translucent"))

    def test_the_other_store_product_lines(self):
        for sku, expected in [
            ("AHPEBK-101", ("PETG", "Basic", "Black")),
            ("AHPETK-101", ("PETG", "Translucent", "")),
            ("AHASRR-101", ("ASA", "Basic", "Red")),
            ("AHYGBW-101", ("PLA", "Matte", "White")),
            ("AHSCGD-102", ("PLA", "Silk", "Gold")),
            ("AHTPDB-101", ("TPU", "Basic", "Blue")),
        ]:
            with self.subTest(sku=sku):
                info = self.parse(sku)
                self.assertEqual((info["material_type"], info["series"], info["color_name"]),
                                 expected)

    def test_codes_that_were_never_on_a_store_sku_no_longer_parse(self):
        # PLA, PETG, HPETG, HABS, ABS and TPU were guesses, not store codes, and
        # HPETG actively misread AHPETG-101. Without them these have no material.
        for sku in ("AHABSRD-1", "ATPUBK-1"):
            with self.subTest(sku=sku):
                self.assertEqual(self.parse(sku)["material_type"], "")

    def test_new_colour_codes(self):
        self.assertEqual(self.parse("AHPLOG-101")["color_name"], "Olive Green")
        self.assertEqual(self.parse("AHPLBY-101")["color_name"], "Blue Grey")

    def test_a_sku_without_an_h_is_not_this_format(self):
        # OpenSpool's OS-24 and the hand-typed ATPLBK-25 have no H to split at.
        empty = self.parse("")
        for sku in ("OS-24", "ATPLBK-25"):
            with self.subTest(sku=sku):
                self.assertEqual(self.parse(sku, {"A": "Anycubic", "O": "Overture"}), empty)

    def test_input_is_stripped_and_upper_cased(self):
        self.assertEqual(self.parse(" ahplbk-107 ")["vendor"], "Anycubic")

    def test_malformed_input_gives_the_empty_result(self):
        empty = {"vendor": "", "material_type": "", "series": "", "color_code": "",
                 "color_name": "", "serial": ""}
        for sku in ("", None, "OPENSPOOL", "AHPLBK", "-107", "AHPLBK-", "A-B-C",
                    "AH-1", "H-1", "AHPLBK-1-2"):
            with self.subTest(sku=sku):
                self.assertEqual(self.parse(sku), empty)

    def test_vendor_prefix_setting_is_parsed(self):
        prefixes = SKU.SkuFormat.parse_prefixes("T=Tinmorry, V=Verbantin")

        self.assertEqual(prefixes, {"A": "Anycubic", "T": "Tinmorry", "V": "Verbantin"})

    def test_an_empty_vendor_prefix_setting_is_just_anycubic(self):
        self.assertEqual(SKU.SkuFormat.parse_prefixes(""), {"A": "Anycubic"})

    def test_a_multi_letter_vendor_code_is_accepted(self):
        prefixes = SKU.SkuFormat.parse_prefixes("AT=Atomic, T=Tinmorry, V=Verbantin")

        self.assertEqual(prefixes, {"A": "Anycubic", "AT": "Atomic", "T": "Tinmorry",
                                    "V": "Verbantin"})

    def test_unusable_vendor_codes_are_rejected_with_a_warning(self):
        # A is built-in Anycubic; a code with an H would be cut short by the first
        # H of the SKU; more than three letters or lower case is not a code.
        for entry in ("A=Mine", "HB=Mine", "BH=Mine", "H=Mine", "ABCD=Mine", "a=Mine"):
            with self.subTest(entry=entry), self.assertLogs(level="WARNING"):
                prefixes = SKU.SkuFormat.parse_prefixes(f"{entry}, T=Tinmorry")

                self.assertEqual(prefixes, {"A": "Anycubic", "T": "Tinmorry"},
                                 "the rest of the line still works")

    def test_o_can_be_claimed_as_a_vendor_code(self):
        prefixes = SKU.SkuFormat.parse_prefixes("O=Overture")

        self.assertEqual(prefixes, {"A": "Anycubic", "O": "Overture"})
        info = self.parse("OHPLBK-25", prefixes)
        self.assertEqual((info["vendor"], info["material_type"], info["color_name"]),
                         ("Overture", "PLA", "Black"))

    def test_an_openspool_sku_is_not_shown_under_vendor_o(self):
        # OS-24 has no H, so it is not a vendor-O product however O is configured.
        info = self.parse("OS-24", {"A": "Anycubic", "O": "Overture"})

        self.assertEqual(info["vendor"], "")

    def test_a_lower_case_vendor_code_is_accepted(self):
        # SKUs are upper-cased before matching, so the setting is too.
        prefixes = SKU.SkuFormat.parse_prefixes("t=Tinmorry, at=Atomic")

        self.assertEqual(prefixes, {"A": "Anycubic", "T": "Tinmorry", "AT": "Atomic"})

    def test_malformed_entries_are_skipped_with_a_warning(self):
        for entry in ("T", "T=", "=Name", "1=Digit"):
            with self.subTest(entry=entry), self.assertLogs(level="WARNING"):
                prefixes = SKU.SkuFormat.parse_prefixes(f"{entry}, V=Verbantin")

                self.assertEqual(prefixes, {"A": "Anycubic", "V": "Verbantin"})


class MmuAceSkuSpoolIdTests(unittest.TestCase):
    """SkuFormat.spool_id: the purely syntactic read of a tag's claimed spool ID.

    Whether that spool exists and fits the gate is the matcher's business (see
    MmuAceSkuSpoolIdTests in test_mmu_ace.py); this only covers what a SKU says.
    """

    def test_spool_id_edge_cases(self):
        sku_format = SKU.SkuFormat()
        for sku, expected in [
            ("OS-24", 24), ("os-24", 24), (" OS-24 ", 24), ("OS-0", None),
            ("OS-2-4", None), ("OS-", None), ("OS-A1", None), ("", None),
            ("THPLBR-14", 14), ("THPLBR-", None), ("THPLBR-1A", None),
            ("HPL18-105", None), ("AHPLBK-A106", None), ("OHPLBK-25", 25),
            # <vendor>H<filament>: any vendor but "" and "A" is read, configured
            # or not, and it ends at the FIRST H.
            ("ATHPLBK-4", 4), ("XHPLBK-7", 7), ("THPLBK-25", 25),
            ("AHPETK-102", None), ("AHHSBK-102", None), ("HHSBK-102", None),
            # No H, so not this format.
            ("ATPLBK-25", None), ("OS-24X", None), ("THPLBK-", None),
            # Nothing after the H.
            ("AH-25", None), ("XH-25", None),
            # An all-digit chip UID fits the pattern but is no spool ID.
            ("OS-04123456789012", None), ("OS-2147483647", 2147483647),
            ("OS-2147483648", None),
        ]:
            with self.subTest(sku=sku):
                self.assertEqual(sku_format.spool_id(sku, "serial"), expected)

    def test_an_unknown_mode_reads_nothing(self):
        for mode in ("bogus", "", None, "SERIAL"):
            with self.subTest(mode=mode):
                self.assertIsNone(SKU.SkuFormat().spool_id("OS-24", mode))

    def test_off_reads_nothing(self):
        for sku in ("OS-24", "THPLBR-14"):
            with self.subTest(sku=sku):
                self.assertIsNone(SKU.SkuFormat().spool_id(sku, "off"))

    def test_openspool_reads_only_os_skus(self):
        sku_format = SKU.SkuFormat()

        self.assertEqual(sku_format.spool_id("OS-24", "openspool"), 24)
        self.assertIsNone(sku_format.spool_id("THPLBR-14", "openspool"))

    def test_the_literal_openspool_carries_no_id_in_any_mode(self):
        for mode in SKU.SKU_SPOOL_ID_MODES:
            with self.subTest(mode=mode):
                self.assertIsNone(SKU.SkuFormat().spool_id("OPENSPOOL", mode))

    def test_the_vendor_prefix_setting_does_not_change_what_is_read(self):
        # The vendor code only names the tag; it is not needed to read the ID.
        configured = SKU.SkuFormat(SKU.SkuFormat.parse_prefixes("AT=Atomic"))

        self.assertEqual(configured.spool_id("ATHPLBK-4", "serial"), 4)
        self.assertEqual(SKU.SkuFormat().spool_id("ATHPLBK-4", "serial"), 4)

    def test_split_sku_code(self):
        self.assertEqual(SKU.split_sku_code("ATHPLBK"), ("AT", "PLBK"))
        self.assertEqual(SKU.split_sku_code("HPL18"), ("", "PL18"))
        for code in ("ATPLBK", "AH", "", None):
            with self.subTest(code=code):
                self.assertIsNone(SKU.split_sku_code(code))


class MmuAceSkuStoreDataTests(unittest.TestCase):
    """Every SKU on Anycubic's store parses to the product line it is sold under.

    The table was authored from the store's SKU, product line and colour listing
    (168 distinct SKUs). Expected values are written out here rather than derived
    from the parser, so a wrong material code or a prefix collision between two
    codes shows up as a failure rather than as a changed answer.
    """

    # (material, series) -> the store SKUs sold under that product line.
    # AHPECL-101 is listed under both PETG and PETG Translucent; it is PETG Basic.
    STORE_SKUS = {
        ('PLA', 'Basic'): """
            AHPLBK-105 AHPLBW-105 AHPLRR-105 AHPLGY-105 AHPLDB-105 AHPLVY-105 AHPLGE-106
            AHPLLB-105 AHPLCG-105 AHPLVO-105 AHPLBR-105 AHPLMG-105 AHPLCY-105 AHPLCL-105
            AHPLPO-105 AHPLSP-105 AHPLBZ-105 AHPLOG-107 AHPLSL-105 AHPLTE-107 AHPLGD-107
            HPL18-105 HPL19-105 HPL16-105 HPL17-105 AHPLMH-107 AHPLMP-107 AHPLLE-107
            AHPLBY-107 AHPLBK-A106 AHPLGY-A106 AHPLBW-A106 AHPLRR-A106 AHPLDB-A106
            AHPLVY-A106 AHPLLB-A107 AHPLCG-A106 AHPLVO-A106 AHPLPO-A106 HPL19-A107
            AHPLMG-A107 AHPLBR-A107 AHPLSP-A106 HPL16-A108 HPL18-A107 HPL17-A107
            AHPLSL-A107 AHPLGE-A107 AHPLCL-A107 AHPLCY-A107
        """,
        ('PLA', 'High Speed'): """
            AHHSBK-102 AHHSGY-102 AHHSBW-102 AHHSDB-102 AHHSBR-102 AHHSCG-102 AHHSVY-102
            AHHSVO-102 AHHSSP-102 AHHSPO-102
        """,
        ('PLA', 'Plus'): """
            AHPLPBK-102 AHPLPBW-102 AHPLPGY-102 AHPLPLB-108 AHPLPDB-102 AHPLPBE-108
            AHPLPBR-107 AHPLPRR-107 AHPLPVY-102 AHPLPVO-102 AHPLPGF-102 AHPLP18-107
            AHPLPGE-107 AHPLPSL-102 AHPLPCG-107 AHPLPPO-103 AHPLP16-107 AHPLP17-107
            AHPLP19-107 AHPLPSP-107 AHPLPBK-A108 AHPLPBW-A108 AHPLPGY-A108 AHPLPRR-A108
            AHPLPDB-A108 AHPLPCG-A108 AHPLPVY-A108 AHPLPVO-A108 AHPLPPO-A108
            AHPLPSP-A108
        """,
        ('PETG', 'Basic'): """
            AHPEBK-101 AHPEBW-101 AHPERR-101 AHPEGY-101 AHPEGE-101 AHPEDB-101 AHPELB-101
            AHPEVY-101 AHPEVO-101 AHPEFG-101 AHPECL-101 AHPECG-101 AHPEAB-101 AHPELG-101
            AHPEDG-101 AHPECR-101 AHPEBR-101 AHPEPB-101 AHPESL-101 AHPEPO-101 AHPESP-101
        """,
        ('ASA', 'Basic'): """
            AHASBK-101 AHASGE-101 AHASIV-101 AHASRR-101 AHASDS-101 AHASOG-101
        """,
        ('PLA', 'Matte'): """
            AHYGBW-101 AHYGBK-101 AHYGKP-101 AHYGIB-101 AHYGDG-101 AHYGDT-101 AHYGCA-101
            AHYGAB-101 AHYGOW-101 AHYGPO-101 AHYGGE-101 AHYGRR-101 AHYGVO-101 AHYGCG-101
            AHYGVY-101 AHYGAG-101 AHYGNG-101 AHYGBC-101 AHYGSB-101 AHYGRB-101 AHYGRO-101
            AHYGDB-101
        """,
        ('PETG', 'Translucent'): """
            AHPETB-101 AHPETR-101 AHPETO-101 AHPETP-101 AHPETL-101 AHPETK-101 AHPETG-101
            AHPETW-101
        """,
        ('PLA', 'Silk'): """
            AHSCRB1-102 AHSCSG-102 AHSCGD-102 AHSCSL-102 AHSCCO-102 AHSCCR-102
            AHSCWH-102 AHSCBL-102 AHSCPK-102 AHSCCG-102 AHSCGR-102 AHSCPU-102
        """,
        ('TPU', 'Basic'): """
            AHTPBK-101 HTPMW-101 HTPGY-101 HTPCL-101 HTPCB-101 HTPCR-101 AHTPDB-101
            AHTPRR-101 AHTPVY-101
        """,
    }

    def test_every_store_sku_parses_to_its_product_line(self):
        checked = 0
        for (material, series), skus in self.STORE_SKUS.items():
            for sku in skus.split():
                checked += 1
                with self.subTest(sku=sku):
                    info = SKU.SkuFormat().parse(sku)
                    self.assertEqual((info["material_type"], info["series"]),
                                     (material, series))
                    self.assertEqual(info["vendor"], "Anycubic")
        self.assertEqual(checked, 168)


if __name__ == "__main__":
    unittest.main()
