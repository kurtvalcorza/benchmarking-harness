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

from app.api.auth import get_principal, get_request_id, require_roles
from app.api.schemas import GoldenSetManifestIn, GoldenSetOut, GoldenSetStatusOut
from app.db.enums import ModelClass, Role
from app.db.models import EvaluationRun, GoldenTestSet, ReevaluationClaim
from app.db.repositories import get_session
from app.services import audit
from app.services.auth import Principal
from app.services.config import load_config, resolves_beneath
from app.services.orchestrator import reevaluate_for_golden_set
from engine.datasets import Dataset, validate_dataset

router = APIRouter(tags=["golden-sets"])

PERMISSIVE_LICENSES = {"owned", "cc-by", "cc-by-4.0", "cc0", "mit", "apache-2.0", "bsd"}


@router.post("/golden-sets", status_code=201, response_model=GoldenSetOut)
def register_golden_set(
    manifest: GoldenSetManifestIn,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles(Role.governance)),
    request_id: str = Depends(get_request_id),
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
    # segmentation reports IoU, not recall → a segmentation golden set declares
    # per-class IoU floors; detection/classification keep recall floors (FR-214).
    is_segmentation = manifest.model_class is ModelClass.segmentation
    # segmentation declares per-class IoU floors, but the published contract
    # still exposes `recall_floors` as the floor field — accept it as a fallback
    # so a client following that contract isn't rejected with a missing-floor 422.
    floors = (manifest.iou_floors or manifest.recall_floors) if is_segmentation else manifest.recall_floors
    floor_metric = "IoU" if is_segmentation else "recall"

    missing_floors = [c for c in manifest.safety_critical if c not in floors]
    if missing_floors:
        raise HTTPException(
            422,
            f"every safety-critical class needs a {floor_metric} floor (FR-026/FR-214); "
            f"missing: {missing_floors}",
        )
    bad_floors = {c: f for c, f in floors.items() if not 0.0 <= f <= 1.0}
    if bad_floors:
        # a floor outside [0,1] silently disarms (or hard-wires) the safety
        # gate — e.g. floor=-1 makes a 0.0 metric "pass" (FR-026/FR-012a)
        raise HTTPException(
            422, f"{floor_metric} floors must be within [0, 1]: {bad_floors}"
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
    # T020a: confine data_ref beneath the configured data/sample roots (after
    # symlink resolution) so an authenticated governance caller still cannot
    # point the harness at arbitrary host paths. Enforced here at registration,
    # not only in the runner (T072).
    data_path = Path(manifest.data_ref)
    cfg = load_config()
    if not resolves_beneath(data_path, cfg.data_roots):
        raise HTTPException(
            422,
            f"data_ref '{manifest.data_ref}' does not resolve beneath a configured data "
            f"root {[str(p) for p in cfg.data_roots]} (path containment, T020a)",
        )
    # a segmentation golden set MUST carry masks (FR-219): a detection/
    # classification-shaped dataset (label + optional bbox, no rle) cannot
    # register as segmentation — bbox IoU can't stand in for mask IoU.
    problems = validate_dataset(data_path, require_masks=is_segmentation)
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
        # the recall_floors column is the GENERIC per-class safety-floor store:
        # recall floors for detection/classification, IoU floors for segmentation
        # (interpreted by Tier 2 against the class metric; no migration, FR-214)
        recall_floors=floors,
        label_map=manifest.label_map,
        license=manifest.license,
        is_public=False,
        data_ref=manifest.data_ref,
        registered_by=principal.principal_key,
    )
    session.add(gs)
    audit.record(
        session,
        actor=principal.principal_key,
        action="golden-set-registered",
        target_ref=f"golden_set:{gs.id}",
        checksum=checksum,
        request_id=request_id,
        principal_issuer=principal.issuer,
        outcome="success",
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
        floor_metric="iou" if is_segmentation else "recall",
        reevaluation_flagged=flagged,
    )


@router.get("/golden-sets/{id}", response_model=GoldenSetStatusOut)
def get_golden_set(
    id: str,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> GoldenSetStatusOut:
    """T020b: governance reads its OWN registrations' re-evaluation status;
    auditor reads any. Object-scoped per security-boundary.md."""
    gs = session.get(GoldenTestSet, id)
    if gs is None:
        raise HTTPException(404, "golden set not found")
    is_auditor = principal.has_any(Role.auditor)
    is_owner = principal.has_any(Role.governance) and gs.registered_by == principal.principal_key
    if not (is_auditor or is_owner):
        raise HTTPException(
            403, "not authorized to read this golden set's status (object scope)"
        )
    # runs evaluated against this set + versions with an open re-evaluation claim
    runs = session.exec(
        select(EvaluationRun).where(EvaluationRun.golden_set_id == gs.id)
    ).all()
    claims = session.exec(
        select(ReevaluationClaim).where(ReevaluationClaim.golden_set_id == gs.id)
    ).all()
    return GoldenSetStatusOut(
        id=gs.id,
        name=gs.name,
        model_class=gs.model_class,
        version=gs.version,
        checksum=gs.checksum,
        evaluated_run_ids=[r.id for r in runs],
        reevaluation_intents=[c.model_version_id for c in claims],
    )
