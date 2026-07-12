# Requirements Quality Checklist: Real-Model Visual Grounding

Gate for `specs/004-real-model-grounding/` before implementation. `[x]` = satisfied by the
current spec set; `[ ]` = to confirm during/at implementation.

## Specification quality

- [x] The problem is stated concretely (real detector emits no attribution → `missing_attribution`), grounded in the code path (`_predict_det`, `tier3_ops`)
- [x] Each requirement is testable and traceable to a task (FR-301..315 ↔ tasks.md)
- [x] Out-of-scope is explicit (classification/segmentation grounding, threshold change, ONNX, the real golden-set data step)
- [x] The clarifications record the four locked decisions (method, default, evidence, class scope)

## Method and evidence

- [x] The attribution method is decided (D-RISE primary, Grad-CAM selectable) and justified against the adapter black-box boundary (research R1)
- [x] The evidence shape is precise (`point` in image pixels + `energy_inside` in `[0,1]`) and reuses the existing `Prediction.attribution` channel + `GroundingEvidence` contract
- [x] Forbidden substitutions are restated — no proxy from confidence/params/latency (contract, FR-301)
- [ ] Reference agreement: the pointing-game score matches a hand computation on a synthetic fixture (to verify in tests — T110/T112)

## Correctness (the F6 fix)

- [x] The canonicalization gap is identified: `canonicalize()` skips `attribution` AND Tier 3 uses raw predictions → foreign-vocabulary false-fail (research R4, FR-305)
- [x] The fix canonicalizes in `run_tier3` via the **benchmark dataset's own `manifest.label_map`** (mirroring Tier 1), **not** the Golden Set's — corrected per @claude review; no `orchestrator.py` change; the stub path is unaffected (identity/absent map)
- [ ] A dedicated guard test asserts hit-with-canon vs miss-without-canon **and** that it uses the Tier-3 benchmark dataset's manifest map, not a Golden Set map (T111)

## Determinism, timing, budget

- [x] D-RISE determinism is specified (seed from `weights_digest + image_id`, independent of global RNG) → reproducible evidence (research R5, FR-302)
- [x] The extractor is bounded to `grounding_min_samples` targets and logs the cap — no silent truncation (research R6, FR-309)

## Explain seam + timing (post-merge review — the two HIGH findings)

- [x] The extractor is scoped to **Tier 3 only** via an `explain: bool = False` seam through `run_inference`; Tier 1/2 never pay the cost (FR-306a, research R8, review #1)
- [x] The seam's **full blast radius** is named (2nd-round review): `runner.py` + `job.py` (predict/timing) + `runner_client.py` (T073 HTTP leg) + `InferenceAdapter.explain()` protocol — not just the tier call-sites
- [x] The timing-split **mechanism** is pinned: a separately-timed `adapter.explain()` step (not a `predict()` return-type change); `predict_s`/`explain_s` in `JobResult.timing`; `run_tier3` uses `predict_s` only; `explain=False` byte-for-byte on every leg (FR-308, research R3, review #2)
- [x] FR-305 mirrors Tier 1's `from_dict → canonicalize` sequence, so `canonicalize()` runs on `list[Prediction]` not `list[dict]` (FR-305, review #4)
- [x] FR-303 reworded — energy is retained evidence; `evaluate_grounding` is first-applicable so `pointing_game` scores under the default (FR-303, review #3)
- [x] `energy_inside_region` vs `pointing_game` `sample_count` divergence documented (FR-316, review #5); `Prediction.attribution` docstring update tasked (T145, review #6)
- [ ] Phase-1 tests T116 (Tier-1/2 non-invocation) + T113 (timing split) assert the two HIGH fixes

## Constitution compliance

- [x] I Human-in-loop — the ratified gate + fail-closed routing are unchanged; a measured pass is only *possible*, never automatic below `0.30`
- [x] II Licensing-clean — evidence holds points/scalars/method, no raw image pixels
- [x] IV No-egress / append-only — the extractor runs the local model on in-memory masks in the sandbox; evidence stays content-addressed + append-only
- [x] V Verify-first — method + evaluator_version + sample_count + resolvable evidence_ref travel with every measured result; determinism makes it reproducible; the US5 provenance surfacing now has a light Phase-1 assertion (T115, per @claude review) so no FR ships untested
- [x] VI Test-first — Phase-1 tests precede implementation (FR-313)

## Cross-artifact readiness

- [x] scoping.md, spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md present (parity with 003)
- [x] tasks.md phases map to FRs; Phase-0 (plan/research/contract) is complete
- [ ] validation.md authored on landing with the live real-checkpoint grounding record
- [ ] No Tier-1/2/3 regression — full suite + gates green (FR-314, verified at implementation)

## Notes

- The one genuinely new concept is the **saliency extractor** (D-RISE seeded masks → peak +
  energy); everything else reuses existing seams (the attribution channel, `GroundingEvidence`,
  the content-addressed evidence store, the ratified gate).
- Two implementation-time confirmations remain: the reference pointing-game agreement test and
  the FR-315 real golden-set data step for a live end-to-end pass — neither blocks the design.
- The highest-risk item is the FR-305 canonicalization fix; it is called out explicitly and
  guarded by a dedicated test so a foreign-vocabulary detector cannot silently false-fail.
