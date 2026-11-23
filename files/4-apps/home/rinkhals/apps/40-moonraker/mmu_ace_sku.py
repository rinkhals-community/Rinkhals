"""The ACE RFID SKU format, in one place.

A tag's SKU reads <vendor>H<material><colour>-<serial> (AHPLBW-107, ATHPLBK-25).
Split out of mmu_ace.py and mmu_ace_spool_matcher.py because the rules for it -
where the vendor code ends, which codes mean what, which SKUs carry a Spoolman
spool ID - were spread over both and had to agree. Pure stdlib with no Moonraker
imports, so it is testable on its own (tests/test_mmu_ace_sku.py).
"""

import logging
import re

from typing import Optional


# Vendor codes a SKU carries in front of its first "H" (see split_sku_code). Only
# Anycubic's is built in, and it is handled apart from this map (an empty code is
# Anycubic too); the others are opt-in via sku_vendor_prefixes, because a code
# means nothing outside the tags its owner wrote themselves.
ANYCUBIC_VENDOR = "Anycubic"
DEFAULT_VENDOR_PREFIXES = {"A": ANYCUBIC_VENDOR}

# Vendor codes of stock Anycubic SKUs: "A" normally, empty when the A is omitted
# (HPL18-105). The number after their dash is a product/batch code (101-108), not
# a per-roll serial, so reading it as a spool ID would bind an unrelated spool.
STOCK_ANYCUBIC_VENDOR_CODES = ("", "A")

# What a sku_vendor_prefixes key looks like: the first "H" ends the vendor code, so
# it cannot contain one; and 1-3 letters leaves room for e.g. "AT" while keeping
# the code a short, typeable prefix.
_VENDOR_CODE_PATTERN = re.compile(r"[A-Z]{1,3}")

# Material code (the part after the H, before the colour) -> (Spoolman material,
# series). These are the codes on Anycubic's store listings; every one was checked
# against all 168 distinct store SKUs (see MmuAceSkuStoreDataTests (tests/test_mmu_ace_sku.py)).
_SKU_MATERIAL_MAP = {
    "PL": ("PLA", "Basic"),
    "HS": ("PLA", "High Speed"),
    "PLP": ("PLA", "Plus"),
    "PE": ("PETG", "Basic"),
    "PET": ("PETG", "Translucent"),
    "AS": ("ASA", "Basic"),
    "YG": ("PLA", "Matte"),
    "SC": ("PLA", "Silk"),
    "TP": ("TPU", "Basic"),
}

# Colour codes. Only codes that mean the same colour across the store's product
# lines are listed: AB, DG and CR are left out on purpose because they name
# different colours in different lines, and a wrong name is worse than none.
_SKU_COLOR_MAP = {
    "BW": "White",
    "BK": "Black",
    "RD": "Red",
    "BL": "Blue",
    "GR": "Green",
    "YL": "Yellow",
    "OR": "Orange",
    "PK": "Pink",
    "GY": "Grey",
    "PR": "Purple",
    "BR": "Brown",
    # Codes from Anycubic's store listings.
    "RR": "Red",
    "DB": "Blue",
    "VY": "Yellow",
    "VO": "Orange",
    "CG": "Green",
    "SP": "Pink",
    "PO": "Purple",
    "GE": "Grey",
    "LB": "Beige",
    "CL": "Clear",
    "MG": "Magenta",
    "CY": "Cyan",
    "BZ": "Bronze",
    "GD": "Gold",
    "SL": "Silver",
    "OG": "Olive Green",
    "TE": "Textured Red",
    "LE": "Light Grey",
    "BY": "Blue Grey",
    "AG": "Apple Green",
    "BC": "Chocolate Brown",
    "CA": "Caramel",
    "CO": "Copper",
    "DS": "Deep Sea Blue",
    "DT": "Desert Sand",
    "FG": "Forest Green",
    "GF": "Green Flash",
    "IB": "Ice Blue",
    "IV": "Ivory",
    "KP": "Sakura Pink",
    "LG": "Lime Green",
    "MH": "Mia White",
    "MP": "Mia Pink",
    "MW": "Milk White",
    "NG": "Nardo Grey",
    "OW": "Bone White",
    "PB": "Peanut Brown",
    "PU": "Purple",
    "RO": "Dark Brown",
    "SB": "Sky Blue",
    "SG": "Shiny Gold",
    "WH": "White",
    "BE": "Bright Red",
}

# sku_spool_id: which SKU formats are read as "this is the Spoolman spool ID".
# The setting is a comma-separated list of these names, or "all" (every format
# here, including ones added in later releases) or "off" (none, the default).
# The formats cannot overlap - OS- then digits, SM then digits, and a SKU with an
# H and a dash - so at most one of them reads any SKU.
SKU_ID_FORMATS = ("openspool", "spoolkid_ac", "anycubic_style")

# Older ACE firmware reports the payload's "protocol" field as the SKU, so
# this is what an OpenSpool tag looks like there: the same for every roll.
# Newer OpenCubic firmware reports "OS-<spool_id>" or "OS-<chip UID>" instead,
# which do identify one roll.
NON_IDENTIFYING_SKUS = frozenset({"OPENSPOOL"})

# Every SKU format that carries a spool ID, in one pattern: the named group that
# holds the digits is the format's name, so one match says both which format a
# SKU is and what its ID is.
# - openspool: OS-<digits>, an OpenSpool spool_id. Tried first, so any OS- SKU is
#   decided here: OS-A1 (a chip UID) or OS-2-4 matches nothing at all.
# - spoolkid_ac: SM<digits>, SpoolKid's Anycubic ACE tag format (SM8 is spool 8).
# - anycubic_style: <vendor>H<filament>-<digits> on tags written by hand; the H
#   format is checked apart, by split_sku_code, so the code part is captured whole.
_SPOOL_ID_SKU = re.compile(
    r"OS-(?P<openspool>[0-9]+)"
    r"|SM(?P<spoolkid_ac>[0-9]+)"
    r"|(?P<code>[^-]+)-(?P<anycubic_style>[0-9]+)")
# Largest ID read from a SKU; beyond a 32-bit row ID it is a UID, not a spool.
MAX_SPOOL_ID = 2**31 - 1


def parse_sku_id_formats(setting) -> frozenset:
    """The SKU formats a sku_spool_id setting enables, as a set of SKU_ID_FORMATS names.

    The setting is comma-separated format names, case-insensitive: "openspool,
    spoolkid_ac". "all" enables every format and "off" (the default) none. An
    unknown name is skipped with a warning rather than failing the whole line:
    this runs while Moonraker loads its config, and one typo should not cost the
    names that work. A collection of names is accepted too, read the same way
    (case-insensitive) but filtered without warnings.
    """
    if setting is None:
        return frozenset()
    if not isinstance(setting, str):
        names = (str(name).strip().lower() for name in setting)
        return frozenset(name for name in names if name in SKU_ID_FORMATS)
    formats = set()
    for name in setting.split(","):
        name = name.strip().lower()
        if not name or name == "off":
            continue
        if name == "all":
            formats.update(SKU_ID_FORMATS)
        elif name in SKU_ID_FORMATS:
            formats.add(name)
        elif name == "serial":
            # The old single value: say what it became rather than just "unknown".
            logging.warning("[mmu_ace] sku_spool_id 'serial' was split into named formats "
                            "and is ignored; use 'openspool, anycubic_style' for what it read")
        else:
            logging.warning(f"[mmu_ace] Ignoring sku_spool_id format '{name}'. "
                            f"Valid: off, all, {', '.join(SKU_ID_FORMATS)}")
    return frozenset(formats)


def split_sku_code(code: str) -> Optional[tuple]:
    """Split the part of a SKU before its dash into (vendor code, filament code).

    The format is <vendor>H<filament>: the first H ends the vendor code, so
    "ATHPLBK" is ("AT", "PLBK") and "HPL18" is ("", "PL18"). None when there is
    no H or nothing after it, i.e. the SKU is not in this format. Shared by
    SkuFormat.parse and SkuFormat.identify so the two cannot disagree on
    where the vendor ends.
    """
    vendor, found, filament = (code or "").partition("H")
    if not found or not filament:
        return None
    return vendor, filament


class SkuFormat:
    """The ACE RFID SKU format: <vendor>H<material><colour>-<serial>.

    The one thing that varies per install is which vendor codes are named, so
    that is the only state: vendor_prefixes is the effective code -> name map
    (see parse_prefixes), defaulting to the built-in Anycubic one.
    """

    def __init__(self, vendor_prefixes: Optional[dict] = None):
        self.vendor_prefixes = (dict(DEFAULT_VENDOR_PREFIXES) if vendor_prefixes is None
                                else vendor_prefixes)

    @staticmethod
    def parse_prefixes(setting: str) -> dict:
        """The effective vendor code -> vendor name map for a sku_vendor_prefixes setting.

        The setting is comma-separated CODE=Name pairs, e.g. "AT=Atomic, T=Tinmorry".
        A code is 1-3 letters (case-insensitive) with no H (the first H of a SKU ends the
        vendor code) and is not A (built-in Anycubic: claiming it would relabel stock
        SKUs). Anything unusable is skipped with a warning rather than failing the
        whole line: this runs while Moonraker loads its config, and one typo should
        not cost the working entries or the component.
        """
        prefixes = dict(DEFAULT_VENDOR_PREFIXES)
        for entry in (setting or "").split(","):
            entry = entry.strip()
            if not entry:
                continue
            code, sep, name = entry.partition("=")
            # SKUs are upper-cased before they are matched, so the setting is too:
            # "t=Tinmorry" means the same as "T=Tinmorry".
            code, name = code.strip().upper(), name.strip()
            if not sep or not name or not _VENDOR_CODE_PATTERN.fullmatch(code):
                logging.warning(f"[mmu_ace] Ignoring sku_vendor_prefixes entry '{entry}': "
                                "expected 1-3 letters, '=', then a name")
                continue
            if "H" in code:
                logging.warning(f"[mmu_ace] Ignoring sku_vendor_prefixes entry '{entry}': "
                                "the vendor code cannot contain 'H', which ends it in a SKU")
                continue
            if code in STOCK_ANYCUBIC_VENDOR_CODES:
                logging.warning(f"[mmu_ace] Ignoring sku_vendor_prefixes entry '{entry}': "
                                f"'{code}' is reserved (stock Anycubic SKUs already use it)")
                continue
            prefixes[code] = name
        return prefixes

    def parse(self, sku: str) -> dict:
        """Parse an Anycubic-style SKU code like AHPLBW-107

        The layout is <vendor>H<material><colour>-<serial>: everything before the
        first H is the vendor code, everything after it the filament code (see
        split_sku_code). The vendor code is empty or "A" on stock Anycubic SKUs
        (HPL18-105 has none), and a short code of the user's choosing on hand-written
        tags (ATHPLBK-25). The vendor names come from this format's vendor_prefixes
        (see parse_prefixes); a vendor code that is not in it leaves vendor empty
        but the filament still parses.

        Returns dict with:
        - vendor: "Anycubic" (or a configured vendor) or ""
        - material_type: "PLA", "PETG", etc.
        - series: "Basic", "High Speed", etc.
        - color_code: "BW", "BK", etc.
        - color_name: "White", "Black", etc.
        - serial: "107", "106", etc. For stock Anycubic SKUs this is a product or
          batch code, not a per-roll serial.

        Anything that is not exactly <vendor>H<filament>-<serial> yields the empty
        result; in particular a SKU without an H (OS-24, ATPLBK-25) is not this format.
        """
        empty = {"vendor": "", "material_type": "", "series": "", "color_code": "",
                 "color_name": "", "serial": ""}
        sku = (sku or "").strip().upper()
        code_part, sep, serial = sku.partition("-")
        # Exactly one separator between two non-empty parts. partition() splits at the
        # first dash, so a second one lands in the serial and is rejected here.
        if not sep or not code_part or not serial or "-" in serial:
            return empty

        split = split_sku_code(code_part)
        if split is None:
            return empty
        vendor_code, filament = split

        if vendor_code in STOCK_ANYCUBIC_VENDOR_CODES:
            vendor = ANYCUBIC_VENDOR
        else:
            vendor = self.vendor_prefixes.get(vendor_code, "")

        material_type = ""
        series = ""
        color_code = ""
        color_name = ""

        # Material codes are prefixes of one another (PL, PLP; PE, PET), so the filament
        # can start with several. The one that leaves a known colour code is right
        # (PLPO is PL + PO purple, not PLP + O; PLPBK is PLP + BK); with no such code
        # or several, the longest is the most specific.
        candidates = [code for code in _SKU_MATERIAL_MAP if filament.startswith(code)]
        if candidates:
            with_colour = [c for c in candidates if filament[len(c):] in _SKU_COLOR_MAP]
            mat_code = max(with_colour or candidates, key=len)
            material_type, series = _SKU_MATERIAL_MAP[mat_code]
            remaining = filament[len(mat_code):]
            if remaining in _SKU_COLOR_MAP:
                color_code = remaining
                color_name = _SKU_COLOR_MAP[remaining]

        return {
            "vendor": vendor,
            "material_type": material_type,
            "series": series,
            "color_code": color_code,
            "color_name": color_name,
            "serial": serial,
        }

    def spool_id(self, sku: str, formats) -> Optional[int]:
        """The Spoolman spool ID a SKU claims to carry under these formats, or None.

        formats is a frozenset of SKU_ID_FORMATS names, as parse_sku_id_formats
        returns; any other collection or a setting string goes through that parser
        first. A name that is not a format reads nothing. Purely syntactic: whether
        that spool exists and fits the gate is decided by the matcher.

        - openspool reads OS-<digits>. An OS- SKU with any non-digit is a chip
          UID, not an ID, and an OS- SKU is never read by another format.
        - spoolkid_ac reads SM<digits> (SM8, and SM08 as 8).
        - anycubic_style reads <vendor>H<filament>-<digits> for tags written by
          hand (ATHPLBK-25). A SKU with no H (ATPLBK-25) is not that format.

        The SKU's format is worked out once (see identify), and its ID is
        returned only if that format is enabled. Whatever the formats, a stock
        Anycubic SKU (vendor code empty or "A") is never read, since its number is
        a product code (#107), and OPENSPOOL carries nothing.
        """
        # The matcher passes its parsed set on every gate change; parse only what
        # has not been parsed, so a bad setting is warned about once, at load.
        if not isinstance(formats, frozenset):
            formats = parse_sku_id_formats(formats)
        if not formats:
            return None
        identified = self.identify(sku)
        if identified is None or identified[0] not in formats:
            return None
        return identified[1]

    def unread_reason(self, sku: str, formats) -> Optional[str]:
        """Why a tag's SKU gives no spool ID under these formats, or None.

        None when there is nothing to explain: no format is enabled, the gate has
        no tag, or the SKU does carry an enabled format's ID. Otherwise a short
        reason for the log, so a tag that is read but never bound says why
        instead of leaving the log silent.
        """
        if not isinstance(formats, frozenset):
            formats = parse_sku_id_formats(formats)
        sku = (sku or "").strip()
        if not formats or not sku:
            return None
        upper = sku.upper()
        if upper in NON_IDENTIFYING_SKUS:
            return ("this ACE firmware drops the tag's spool_id and reports only "
                    "OPENSPOOL (OpenCubic v1.0.3 or newer reports OS-<spool_id>)")
        identified = self.identify(upper)
        if identified is not None:
            if identified[0] in formats:
                return None
            return (f"{identified[0]} format, which sku_spool_id does not include "
                    f"(enabled: {', '.join(sorted(formats))})")
        if upper.startswith("OS-"):
            return ("not OS-<digits>: the tag has no numeric spool_id, so the hub "
                    "reports the chip UID instead")
        return "not a sku_spool_id format (a stock Anycubic SKU, or a format Rinkhals does not read)"

    @staticmethod
    def identify(sku: str) -> Optional[tuple]:
        """(format name, spool ID) for a SKU in one of SKU_ID_FORMATS, or None.

        Says what the SKU is, whether or not that format is enabled; spool_id
        decides whether to read it. None for anything that carries no usable ID:
        no format fits, a stock Anycubic SKU (vendor code empty or "A": its number
        is a product code, #107), an H-format SKU with nothing after the H, the
        literal OPENSPOOL, or an ID outside 1 to MAX_SPOOL_ID.
        """
        sku = (sku or "").strip().upper()
        if not sku or sku in NON_IDENTIFYING_SKUS:
            return None
        found = _SPOOL_ID_SKU.fullmatch(sku)
        if found is None:
            return None
        sku_format = found.lastgroup
        if sku_format == "anycubic_style":
            split = split_sku_code(found.group("code"))
            if split is None or split[0] in STOCK_ANYCUBIC_VENDOR_CODES:
                return None
        spool_id = int(found.group(sku_format))
        # An all-digit chip UID (OS-04123456789012) also fits the pattern. No
        # Spoolman ID gets that large, and asking for one risks a validation error
        # rather than a 404 - which reads as an outage and is retried every poll.
        if not 0 < spool_id <= MAX_SPOOL_ID:
            return None
        return sku_format, spool_id
