"""Per-gate Spoolman assignments, remembered across restarts.

Split out of mmu_ace.py because it is self-contained: it owns one namespace in
Moonraker's database and answers questions about gates and SKUs, with no
knowledge of the ACE protocol or of Moonraker's request plumbing.
"""

import logging
import time

from typing import Optional


class MmuAceSpoolStore:
    """Remembers which Spoolman spool the user assigned to each ACE gate, across
    Moonraker restarts and reboots.

    Backed by Moonraker's own database component rather than a file of our own:
    no path or permissions to guess, and no need for a server:klippy_ready handler,
    which issue #141 reports silently breaks ACE RFID detection on the next boot.

    Nothing here raises. A missing, unavailable or corrupt store only means
    persistence is off for this session - the ACE status rebuild calls into this on
    every poll and must never depend on it.
    """

    NAMESPACE = "mmu_ace"
    KEY = "spool_assignments"
    # Off by default. Dropping an assignment on a timer is a guess about a physical
    # spool, and a wrong guess is silent: the next print debits nothing. Users who
    # want it opt in with spool_forget_after in [mmu_ace].
    DEFAULT_FORGET_AFTER_S = 0.0
    # How long a previously-readable SKU must stay unreadable before we believe
    # the spool was actually swapped rather than the RFID read having glitched.
    SKU_LOST_GRACE_S = 30.0

    def __init__(self, server, forget_after: float = DEFAULT_FORGET_AFTER_S):
        self.entries: dict[int, dict] = {}   # gate index -> {"spool_id": int, "sku": str}
        # 0 or negative means "never forget", which is the sane setting when gates
        # hold untagged spools: there is no SKU to notice a swap with, so an expiry
        # timer only ever drops assignments the user still wanted.
        self.forget_after = forget_after
        self.time_fn = time.monotonic
        self._empty_since: dict[int, float] = {}
        self._sku_lost_since: dict[int, float] = {}
        self._database = None
        # load() runs as a task, so an assignment can be made before it completes.
        # Saving in that window would overwrite the stored record with a partial one
        # and the not-yet-read entries would be gone for good - merging at load time
        # cannot recover what the save already destroyed. Hold writes until then.
        self._loaded = False
        self._save_pending = False
        # Gates cleared before load() finished, so it does not put them back.
        self._dropped_before_load: set = set()

        try:
            database = server.lookup_component("database", None)
            if database is None:
                logging.info("[mmu_ace] No database component; Spoolman assignments will not persist")
                return
            try:
                database.register_local_namespace(self.NAMESPACE)
            except Exception:
                # Already registered - a reloaded component, not a failure. The
                # namespace is usable either way; only registering it twice is an error.
                logging.debug(f"[mmu_ace] Namespace '{self.NAMESPACE}' already registered")
            self._database = database
        except Exception as e:
            logging.warning(f"[mmu_ace] Spoolman assignment persistence disabled: {e}")

    async def load(self):
        """Read remembered assignments back. Awaited from a task, not __init__."""
        if self._database is None:
            self._finish_load()
            return
        try:
            stored = await self._database.get_item(self.NAMESPACE, self.KEY, {})
        except Exception as e:
            logging.warning(f"[mmu_ace] Could not read Spoolman assignments: {e}")
            self._finish_load()
            return

        entries: dict[int, dict] = {}
        if isinstance(stored, dict):
            for key, value in stored.items():
                try:
                    spool_id = int(value["spool_id"])
                    # 0 is a deliberate clear (see suppress); only nonsense is dropped.
                    if spool_id >= 0:
                        entries[int(key)] = {"spool_id": spool_id, "sku": str(value.get("sku", ""))}
                except Exception as e:
                    logging.warning(f"[mmu_ace] Skipping invalid stored assignment {key!r}: {e}")

        # Merged, not assigned: this runs as a task from __init__, so a pick can
        # land before it completes and replacing the dict would drop it.
        for gate_index, entry in entries.items():
            if gate_index in self._dropped_before_load:
                continue
            self.entries.setdefault(gate_index, entry)
        logging.info(f"[mmu_ace] Loaded {len(entries)} remembered Spoolman assignment(s)")
        self._finish_load()

    def _finish_load(self):
        """Open the write path, flushing anything that arrived while it was shut."""
        self._loaded = True
        if self._save_pending:
            self._save_pending = False
            self._save()

    def _save(self):
        if self._database is None:
            return
        if not self._loaded:
            self._save_pending = True
            return
        try:
            # insert_item returns a Future; deliberately not awaited, so callers on
            # the synchronous status path stay synchronous.
            self._database.insert_item(
                self.NAMESPACE, self.KEY,
                {str(gate): entry for gate, entry in sorted(self.entries.items())}
            )
        except Exception as e:
            logging.warning(f"[mmu_ace] Could not save Spoolman assignments: {e}")

    def remember(self, gate_index: int, spool_id: int, sku: str):
        entry = {"spool_id": int(spool_id), "sku": sku or ""}
        if self.entries.get(gate_index) != entry:
            self.entries[gate_index] = entry
            self._save()

    def suppress(self, gate_index: int, sku: str):
        """Record that the user deliberately left this gate unassigned.

        Stored as an assignment with no spool, so it persists like any other and
        is dropped by the same evidence - see cleared_by_user.
        """
        entry = {"spool_id": 0, "sku": sku or ""}
        if self.entries.get(gate_index) != entry:
            self.entries[gate_index] = entry
            self._save()

    def cleared_by_user(self, gate_index: int, sku: str) -> bool:
        """True while a deliberate clear still refers to the spool in the gate.

        Auto-match must not undo a clear, or a wrong match could not be corrected
        short of switching the feature off. A different spool makes the clear
        stale, so it is dropped on the same evidence as a real assignment.
        """
        entry = self.entries.get(gate_index)
        if not entry or entry.get("spool_id"):
            return False
        if self.spool_swapped(gate_index, sku):
            self.forget(gate_index)
            return False
        return True

    def forget(self, gate_index: int):
        if not self._loaded:
            # load() merges rather than assigns, so without this the stored row
            # would come straight back and undo a clear made while the read was
            # still in flight.
            self._dropped_before_load.add(gate_index)
        self._empty_since.pop(gate_index, None)
        self._sku_lost_since.pop(gate_index, None)
        if self.entries.pop(gate_index, None) is not None:
            self._save()

    def restorable(self, gate_index: int, sku: str) -> Optional[int]:
        """The remembered ID for this gate, if it still holds the same product.

        Matched on the RFID SKU. Untagged gates report no SKU, so they all match
        each other - an assignment there follows the gate, not the physical spool.
        Nothing the ACE reports can tell two untagged spools apart, so this is a
        documented limitation rather than something fixable here.
        """
        entry = self.entries.get(gate_index)
        if entry and entry["sku"] == (sku or ""):
            return entry["spool_id"]
        return None

    def spool_swapped(self, gate_index: int, sku: str) -> bool:
        """True once the evidence says this gate holds a different spool.

        Deliberately asymmetric, because the three transitions carry different
        amounts of certainty:

        - SKU changed to another SKU, or appeared where there was none: certain.
          The gate cannot be holding the same spool, so drop the mapping at once.
          The "appeared" case is a real one - an untagged spool replaced by a
          tagged one - and was previously missed entirely.
        - SKU disappeared: ambiguous. Either an untagged spool went in, or the
          RFID read failed this poll. Wait SKU_LOST_GRACE_S of it staying gone
          before believing it, so a momentary misread does not drop a good
          mapping.
        - Neither side has a SKU: nothing to compare. Two untagged spools are
          indistinguishable to the ACE; the assignment follows the gate.
        """
        entry = self.entries.get(gate_index)
        if entry is None:
            self._sku_lost_since.pop(gate_index, None)
            return False

        saved_sku = entry.get("sku", "")
        sku = sku or ""

        if saved_sku == sku:
            self._sku_lost_since.pop(gate_index, None)
            return False

        if sku:
            # A readable SKU that differs from the stored one. No doubt possible.
            self._sku_lost_since.pop(gate_index, None)
            return True

        # Had a SKU, now reads none - debounce before acting.
        now = self.time_fn()
        return now - self._sku_lost_since.setdefault(gate_index, now) >= self.SKU_LOST_GRACE_S

    def empty_too_long(self, gate_index: int, present: bool) -> bool:
        """True once a gate has read empty for forget_after seconds straight."""
        if present:
            self._empty_since.pop(gate_index, None)
            return False
        if not self.forget_after or self.forget_after <= 0:
            return False
        now = self.time_fn()
        return now - self._empty_since.setdefault(gate_index, now) >= self.forget_after
