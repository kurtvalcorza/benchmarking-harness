# Requirements Quality Checklist: Computer-Vision Capability Benchmarks

Gate for `specs/003-cv-benchmarks/` before US4 implementation. `[x]` = satisfied
by the current spec set; `[ ]` = to confirm during/at implementation.

## Specification quality

- [x] Retro (US1–US3) vs build (US4) split is explicit; retro stories carry their delivering PRs
- [x] US3/FR-104 marked "in review" with the PR #11 → `main` dependency (not claimed done ahead of `main`)
- [x] Each US4 requirement is testable and traceable to a task (FR-201..219 ↔ tasks.md)
- [x] Out-of-scope is explicit (instance mask-AP, ONNX `-seg`, pose/lane/face, threshold ratification)

## Segmentation metric and masks

- [x] The standard metric is named (semantic `miou`) with a precise definition (dataset-wide pixel IoU)
- [x] Mask representation is decided (COCO RLE) and justified for reproducibility (research R3)
- [x] The instance→semantic reduction is deterministic and documented (research R4, contract)
- [x] Malformed-mask cases are enumerated as typed coverage errors (FR-216, contract)
- [ ] mIoU agrees with a reference computation on valid fixtures (to verify in tests — T020)

## Data and licensing

- [x] The ground-truth source is a permissive fetch into gitignored `data/`; an owned synthetic sample ships (FR-205, research R2)
- [x] No dataset is committed; masks embed no raw image pixels (Constitution II)
- [ ] The concrete Open Images `-seg` slice + its license line are confirmed at fetch-script landing (T050)

## Gate, floors, and evidence

- [x] Unratified `miou` → `pending_adjudication`, never a silent pass (FR-207)
- [x] Per-class IoU floors generalize the recall-only floor path, incl. downstream flag/card wording (FR-214)
- [x] Mask evidence is content-addressed + reproducible; coverage + evaluator provenance travel with results (FR-208/218)
- [x] The submission allowlist (`SCORED_CLASSES`) admits segmentation so uploads are not 422'd pre-scoring (FR-213)

## Constitution compliance

- [x] I Human-in-loop — adjudication routing on unratified/floor breach
- [x] II Licensing-clean — fetch-not-redistribute; owned synthetic sample
- [x] III Benchmark-per-class — the registry `miou` slot gets a real scorer + threshold
- [x] IV No-egress / append-only — masks run in the sandbox; evidence/results append-only
- [x] VI Test-first — Phase-1 tests precede implementation (FR-209)

## Cross-artifact readiness

- [x] plan.md, research.md, data-model.md, contracts/, quickstart.md present (parity with 002)
- [x] tasks.md phases map to FRs; Phase-0 (plan/research) is now complete
- [ ] validation.md authored on landing with the live `yolov8n-seg` record (T061)
- [ ] No detection/classification regression — full suite + gates green (FR-212, verified at implementation)

## Notes

- The one genuinely new concept is the mask channel + deterministic reduction (research R4); all other pieces reuse detection/classification seams.
- Two implementation-time confirmations remain: the reference-mIoU agreement test and the exact Open Images `-seg` license line — both flagged above, neither blocks the design.
