"""Choosing a Spoolman spool for an ACE gate.

Split out of mmu_ace.py because it answers a question about the Spoolman
inventory rather than about the ACE: the controller decides *when* to ask, this
decides the answer and hands it back rather than applying it.
"""

import logging
import time

from collections import OrderedDict

from typing import Optional
from urllib.parse import quote


class SpoolmanUnavailable(Exception):
    """Spoolman could not be reached or answered unusably.

    Distinct from "nothing matched": the caller must retry a gate that hit this,
    or one outage - most likely at boot, before Spoolman is up - would leave the
    gate marked as already considered and never matched again.
    """


class MmuAceSpoolMatcher:
    """Matches an unmapped gate against the Spoolman inventory.

    Two tiers: the RFID SKU against ``article_number``, then material and colour.
    The SKU goes first because a hit is the right product by construction, but it
    is absent or uninformative more often than not - untagged gates have none,
    every OpenSpool tag reports the literal "OPENSPOOL", and a stock Anycubic SKU
    is a product code shared by every roll of that product.

    Ambiguity is refused rather than guessed: "unique" returns nothing and the
    user picks, "latest" breaks the tie by last_used. Rolls of one product are
    interchangeable, so that guess is a contained one.

    Three things about Spoolman's API shape every query below, measured against
    0.26.1 rather than assumed:

    - text filters match partially and case-insensitively (material=PET returns
      every PETG; article_number=AHPETK-102 also returns AHPETK-1024);
    - an unrecognised filter is answered with 200 and the *unfiltered* list;
    - colour matching defaults to fuzzy, so it asks for threshold 0.

    Nothing a query returns is therefore trusted - every field is re-checked
    here - which also means an older Spoolman that ignores a filter costs extra
    rows rather than a wrong spool.
    """

    MODES = ("off", "unique", "latest")
    CACHE_S = 60.0
    # Spools per request. Bounds the JSON held at once: a library of any size is
    # walked a page at a time and only the matches are kept.
    PAGE_SIZE = 200
    # Refuse rather than page forever if Spoolman ignores limit/offset.
    MAX_PAGES = 200
    # Cached query responses kept at once; bounds memory as well as staleness.
    CACHE_ENTRIES = 16
    # The hub reports the payload's "protocol" field as the SKU, so this is what
    # every OpenSpool tag looks like.
    NON_IDENTIFYING_SKUS = frozenset({"OPENSPOOL"})

    def __init__(self, server, mode: str = "off"):
        self.server = server
        self.mode = mode if mode in self.MODES else "off"
        # Short-lived per-query cache. Four gates rebuilt together usually ask
        # overlapping questions, and the answers cannot change that fast.
        self._cache: "OrderedDict[tuple, tuple]" = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    async def match(self, gate, gate_index: int) -> Optional[int]:
        """The Spoolman spool this gate should be assigned, or None.

        Returns rather than assigns, so that refusing to guess and finding
        nothing are the same answer to the caller.
        """
        sku = (getattr(gate, "sku", "") or "").strip()
        fingerprint = self.fingerprint(gate)
        if not sku and fingerprint is None:
            return None

        # SKU first: a hit is the right product by construction, so colour is
        # never consulted.
        described = ""
        candidates = await self._candidates_by_sku(sku)
        if candidates:
            described = f"SKU {sku}"
        elif fingerprint is not None:
            material, colour = fingerprint
            candidates = await self._candidates_by_fingerprint(material, colour)
            described = f"{material} #{colour}"

        if not candidates:
            # Info, not debug: Moonraker runs at INFO, so a debug line is never
            # written and the documented grep finds nothing. Affordable now that
            # matching only runs when the spool in a gate changes.
            logging.info(f"Gate {gate_index}: auto-match found no Spoolman spool "
                         f"for {described or 'this filament'}")
            return None

        if len(candidates) > 1:
            ids = sorted(s.get("id") for s in candidates if isinstance(s.get("id"), int))
            if self.mode != "latest":
                logging.info(f"Gate {gate_index}: auto-match found several spools {ids} "
                             f"for {described}, leaving it unassigned - pick one yourself")
                return None
            candidates.sort(key=lambda s: (s.get("last_used") or "", s.get("id") or 0))
            logging.info(f"Gate {gate_index}: auto-match found several spools {ids} "
                         f"for {described}, choosing the most recently used")

        spool_id = candidates[-1].get("id")
        if not isinstance(spool_id, int) or spool_id <= 0:
            return None

        logging.info(f"Gate {gate_index}: auto-matched to Spoolman spool {spool_id} "
                     f"by {described}")
        return spool_id

    async def _get(self, path: str, params: dict) -> list:
        """One GET against Spoolman.

        Raises SpoolmanUnavailable rather than returning empty, so a failed
        lookup is never mistaken for an empty inventory.

        Moonraker's spoolman component keeps no catalogue of its own and exposes
        no fetch, so this goes over its configured URL with its http client -
        which also means no second place to configure the Spoolman address.
        """
        spoolman = self.server.lookup_component("spoolman", None)
        if spoolman is None:
            raise SpoolmanUnavailable("no spoolman component")

        key = (path, tuple(sorted(params.items())))
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self.CACHE_S:
            return cached[1]

        # Commas are legal unencoded in a query value and Spoolman takes id
        # lists that way, so leave them readable in the logs.
        query = "&".join(f"{k}={quote(str(v), safe=',')}" for k, v in params.items())
        url = f"{spoolman.spoolman_url}{path}" + (f"?{query}" if query else "")
        try:
            response = await spoolman.http_client.get(
                url, connect_timeout=2., request_timeout=4.
            )
            if response.has_error():
                raise SpoolmanUnavailable(f"error response from {path}")
            rows = response.json()
        except SpoolmanUnavailable:
            raise
        except Exception as e:
            raise SpoolmanUnavailable(f"{path}: {e}") from e
        if not isinstance(rows, list):
            raise SpoolmanUnavailable(f"{path} did not return a list")
        self._cache[key] = (now, rows)
        while len(self._cache) > self.CACHE_ENTRIES:
            self._cache.popitem(last=False)
        return rows

    async def _collect(self, params: dict, keep) -> list:
        """Page through /v1/spool, keeping only what `keep` accepts.

        Whatever the library holds, one page is the most JSON alive at once and
        only candidates are retained.
        """
        found: list = []
        for page in range(self.MAX_PAGES):
            rows = await self._get("/v1/spool", dict(
                params, limit=self.PAGE_SIZE, offset=page * self.PAGE_SIZE))
            found.extend(spool for spool in rows if keep(spool))
            if len(rows) < self.PAGE_SIZE:
                return found
        logging.warning("[mmu_ace] auto-match stopped reading the Spoolman catalogue after "
                        f"{self.MAX_PAGES} pages")
        return found

    @staticmethod
    def identity(gate, sku: str) -> tuple:
        """Everything a match depends on, for telling one spool from the next.

        Two gates reading the same tuple would get the same answer, so there is
        no point asking twice - see the caller in mmu_ace.py.
        """
        return (
            (sku or "").strip(),
            (getattr(gate, "material", "") or "").strip().upper(),
            tuple((getattr(gate, "color", None) or [])[:3]),
        )

    @staticmethod
    def fingerprint(gate) -> Optional[tuple]:
        """(material, RRGGBB) for a gate, or None when there is nothing to match on.

        A gate with no material is not yet described - an untagged slot reads that
        way until it is set on the ACE screen, and its colour defaults to black,
        which would collide with every real black spool. Refuse rather than guess.
        """
        material = (getattr(gate, "material", "") or "").strip()
        if not material or material.lower() == "unknown":
            return None
        colour = gate.color
        if not colour or len(colour) < 3 or not any(colour[:3]):
            return None
        return material.upper(), "{:02X}{:02X}{:02X}".format(*colour[:3])

    async def _get_filaments(self, params: dict) -> list:
        """Filaments matching a query, capped so one request stays bounded.

        A backstop rather than a paging scheme: these queries are narrow enough
        that hitting the cap means something unexpected, and stopping short can
        only cost a match, never cause a wrong one.
        """
        rows = await self._get("/v1/filament", dict(params, limit=self.PAGE_SIZE))
        if len(rows) >= self.PAGE_SIZE:
            logging.warning(f"[mmu_ace] auto-match: Spoolman returned {len(rows)} filaments for "
                            f"{params}; only the first {self.PAGE_SIZE} were considered")
        return rows

    async def _spools_of(self, filaments: list) -> list:
        """Every spool belonging to these filaments, in one query where possible.

        filament.id takes a comma-separated list, so N filaments cost one request
        rather than N. Archived spools are retired on purpose, so they are left out.
        """
        ids = [f.get("id") for f in filaments if f.get("id")]
        if not ids:
            return []
        wanted = {str(i) for i in ids}
        return await self._collect(
            {"filament.id": ",".join(str(i) for i in ids), "allow_archived": "false"},
            lambda s: str((s.get("filament") or {}).get("id")) in wanted
            and not s.get("archived"))

    async def _candidates_by_sku(self, sku: str) -> list:
        """Spools whose filament carries this exact product code.

        article_number is on the filament, not the spool, so this narrows to a
        product; picking between its rolls is the ambiguity match() handles.
        """
        if not sku or sku.upper() in self.NON_IDENTIFYING_SKUS:
            return []
        rows = await self._get_filaments({"article_number": sku})
        exact = [f for f in rows if (f.get("article_number") or "").strip() == sku]
        return await self._spools_of(exact)

    async def _candidates_by_fingerprint(self, material: str, colour: str) -> list:
        """Spools of this material and this exact colour.

        Both narrow server-side, because colour is filterable on /filament even
        though it is not on /spool. Asking for threshold 0 keeps the result
        small; the exact re-check below is what makes it right.
        """
        rows = await self._get_filaments({
            "material": material,
            "color_hex": colour,
            "color_similarity_threshold": 0,
        })
        exact = [f for f in rows
                 if (f.get("material") or "").strip().upper() == material
                 and (f.get("color_hex") or "").strip().upper()[:6] == colour]
        return await self._spools_of(exact)

    @staticmethod
    def _matches_fingerprint(spool: dict, material: str, colour: str) -> bool:
        filament = spool.get("filament") or {}
        return ((filament.get("material") or "").strip().upper() == material
                and (filament.get("color_hex") or "").strip().upper()[:6] == colour)
