"""Transactional evidence staging (T051, US4).

Tier evidence is written to a temporary staging area and digested BEFORE the
completion transaction, then *published* atomically (``os.replace``) into the
results tree immediately before the commit. If the commit fails the staged
evidence is discarded (compensation), so a rolled-back run leaves no evidence
and — conversely — no committed run is missing the evidence its TierResults
reference.

Order of operations (data-model.md §Successful evaluation completion):

    stage each tier   -> temp files + sha256 digests (outside the txn)
    ... open txn, add run/tiers/status/audit/card/intent ...
    publish()         -> atomically move temp -> final (evidence lands)
    commit()          -> DB lands
    on failure -> discard()  (remove published + staged files)

A crash between ``publish()`` and ``commit()`` can orphan evidence files with no
DB row; that is harmless and swept by ``reconciliation.orphaned_evidence``.
"""

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _Staged:
    tmp_path: Path
    final_path: Path
    digest: str


@dataclass
class EvidenceStage:
    """Collects a run's per-tier evidence, then publishes it atomically."""

    results_root: Path
    run_id: str
    _items: list[_Staged] = field(default_factory=list)
    _published: list[Path] = field(default_factory=list)

    @property
    def _staging_dir(self) -> Path:
        return self.results_root / "staging" / self.run_id

    @property
    def _final_dir(self) -> Path:
        return self.results_root / "runs" / self.run_id

    def stage(self, index: int, name: str, payload: dict) -> tuple[str, str]:
        """Write one evidence artifact to staging, returning (final_ref, digest).

        The returned path is where the artifact WILL live after ``publish()`` —
        the TierResult can reference it and its digest inside the transaction
        even though the bytes are not yet in their final home.
        """
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        # digest the EXACT bytes written to disk: write_bytes avoids the text-mode
        # newline translation (\n -> \r\n on Windows) that would otherwise make
        # the on-disk sha256 diverge from the recorded evidence_digest
        raw = json.dumps(payload, indent=2, default=str).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        filename = f"{index:02d}-{name}.json"
        tmp = self._staging_dir / filename
        tmp.write_bytes(raw)
        final = self._final_dir / filename
        self._items.append(_Staged(tmp_path=tmp, final_path=final, digest=digest))
        return str(final), digest

    def publish(self) -> None:
        """Atomically move every staged artifact into the results tree. Call
        immediately before the DB commit."""
        self._final_dir.mkdir(parents=True, exist_ok=True)
        for item in self._items:
            os.replace(item.tmp_path, item.final_path)
            self._published.append(item.final_path)
        shutil.rmtree(self._staging_dir, ignore_errors=True)

    def discard(self) -> None:
        """Compensation: remove published + staged artifacts after a failed
        commit so a rolled-back run leaves no evidence behind."""
        for path in self._published:
            try:
                path.unlink()
            except OSError:
                pass
        # remove the final dir only if we emptied it (never clobber a sibling run)
        try:
            if self._final_dir.exists() and not any(self._final_dir.iterdir()):
                self._final_dir.rmdir()
        except OSError:
            pass
        shutil.rmtree(self._staging_dir, ignore_errors=True)
