"""Golden Test Set registration (T057, FR-020/026; T059 re-eval trigger).

Manifest validation is the FR-020 seam: a conforming manifest is all it takes
to add a domain — no harness code change. `is_public=true` is rejected
outright (never-public invariant, Constitution IV); every safety-critical
class MUST carry a recall floor (FR-026).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.schemas import GoldenSetManifestIn, GoldenSetOut
from app.db.models import GoldenTestSet
from app.db.repositories import get_session
from app.services import audit
from app.services.orchestrator import reevaluate_for_golden_set
from engine.datasets import Dataset, validate_dataset

router = APIRouter(tags=["golden-sets"])

PERMISSIVE_LICENSES = {"owned", "cc-by", "cc-by-4.0", "cc0", "mit", "apache-2.0", "bsd"}


@router.post("/golden-sets", status_code=201, response_model=GoldenSetOut)
def register_golden_set(
    manifest: GoldenSetManifestIn, session: Session = Depends(get_session)
) -> GoldenSetOut:
    if manifest.is_public:
        raise HTTPException(
            422, "golden test sets are never public (is_public must be false, Constitution IV)"
        )
    if manifest.license.lower() not in PERMISSIVE_LICENSES:
        raise HTTPException(
            422,
            f"license '{manifest.license}' is not owned/permissive; the harness only "
            f"registers license-clean data (Constitution II). Accepted: {sorted(PERMISSIVE_LICENSES)}",
        )
    missing_floors = [c for c in manifest.safety_critical if c not in manifest.recall_floors]
    if missing_floors:
        raise HTTPException(
            422,
            f"every safety-critical class needs a recall floor (FR-026); missing: {missing_floors}",
        )
    bad_floors = {c: f for c, f in manifest.recall_floors.items() if not 0.0 <= f <= 1.0}
    if bad_floors:
        # a floor outside [0,1] silently disarms (or hard-wires) the safety
        # gate — e.g. floor=-1 makes recall 0.0 "pass" (FR-026/FR-012a)
        raise HTTPException(
            422, f"recall floors must be within [0, 1] (they are recalls): {bad_floors}"
        )
    dup = session.exec(
        select(GoldenTestSet).where(
            GoldenTestSet.name == manifest.name, GoldenTestSet.version == manifest.version
        )
    ).first()
    if dup:
        raise HTTPException(422, f"golden set '{manifest.name}' {manifest.version} already registered")

    if not manifest.data_ref:
        # Tier 2 reads the set from data_ref at evaluation time; registering
        # without one would turn every run for this class into an infra
        # failure. Require it until a remote data source exists.
        raise HTTPException(
            422,
            "data_ref is required: fetch the dataset locally (scripts/fetch_*) and register "
            "the path the API/worker can read",
        )
    # POC trust boundary: data_ref is a server-side path supplied by the
    # governance operator (the API has no auth yet — spec assumption OQ-5).
    # Before production: authenticate this endpoint and confine data_ref
    # to a configured dataset root so callers can't probe arbitrary paths.
    data_path = Path(manifest.data_ref)
    problems = validate_dataset(data_path)
    if problems:
        raise HTTPException(
            422, f"data_ref '{manifest.data_ref}' is not a conforming dataset: {problems}"
        )
    computed = Dataset(root=data_path).checksum()
    checksum = manifest.checksum
    if checksum == "auto":
        checksum = computed
    elif checksum != computed:
        raise HTTPException(
            422,
            "manifest checksum does not match the data content (contamination guard, FR-018)",
        )

    gs = GoldenTestSet(
        name=manifest.name,
        domain=manifest.domain,
        model_class=manifest.model_class,
        version=manifest.version,
        manifest_ref="",
        checksum=checksum,
        conditions=[c.value for c in manifest.conditions],
        safety_critical_classes=manifest.safety_critical,
        recall_floors=manifest.recall_floors,
        label_map=manifest.label_map,
        license=manifest.license,
        is_public=False,
        data_ref=manifest.data_ref,
    )
    session.add(gs)
    audit.record(
        session,
        actor="governance",
        action="golden-set-registered",
        target_ref=f"golden_set:{gs.id}",
        checksum=checksum,
    )
    try:
        session.commit()
    except IntegrityError:
        # concurrent registration lost the race on the (name, version) constraint
        session.rollback()
        raise HTTPException(
            422, f"golden set '{manifest.name}' {manifest.version} already registered"
        ) from None
    session.refresh(gs)

    flagged = reevaluate_for_golden_set(gs)  # FR-004
    return GoldenSetOut(
        id=gs.id,
        name=gs.name,
        model_class=gs.model_class,
        version=gs.version,
        checksum=gs.checksum,
        conditions=gs.conditions,
        safety_critical_classes=gs.safety_critical_classes,
        recall_floors=gs.recall_floors,
        reevaluation_flagged=flagged,
    )
