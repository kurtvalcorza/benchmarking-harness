# Contract — InferenceAdapter interface

The evaluation engine depends only on this interface, never on a specific framework. Adding a framework = a new adapter; adding a model class = a registry entry (not an adapter change). This is the seam that keeps the engine framework- and class-agnostic (Constitution III; FR-006, FR-023).

## Interface

```python
class InferenceAdapter(Protocol):
    def load(self, artifact_ref: str, model_class: ModelClass) -> "LoadedModel":
        """Load serialized weights into an in-memory model. MUST NOT access the network."""

    def predict(self, model: "LoadedModel", images: Iterable[Image]) -> list[Prediction]:
        """Run inference. Returns class-appropriate Prediction objects (boxes / labels / masks / keypoints)."""

    def describe(self, model: "LoadedModel") -> ModelDescriptor:
        """Return param count, input spec, and framework/version — feeds Tier 3 resource profile + provenance."""
```

## Prediction shape (per model class)

| Class | Prediction fields |
|---|---|
| detection | `boxes[], scores[], labels[]` |
| classification | `label, scores[]` |
| segmentation | `mask (HxW label map)` |
| pose | `keypoints[], scores[]` |
| lane | `lanes[] (point sets)` |
| face | `landmarks[]` |

## Guarantees the adapter MUST honor

- **No egress**: `load` and `predict` MUST NOT open network connections (enforced at runtime by the `--network none` sandbox; the adapter must not assume connectivity, e.g. no auto-downloading weights).
- **Determinism**: given the same weights, images, and seed, `predict` MUST return identical outputs (Constitution IV / SC-004). Adapters set framework seeds in `load`.
- **No side effects on inputs**: images are read-only; adapters must not write into mounted dataset dirs.
- **Failure typing**: a load/predict error MUST raise `AdapterError` (→ run marked `infra_ok=false`, not a model `fail`) — distinct from a model that runs but scores below threshold.

## POC implementations

- `PyTorchAdapter` — Ultralytics YOLO (detection) + timm (classification).
- `OnnxAdapter` — ONNX Runtime, CPU execution provider for the POC.

## Registry entry (companion)

```python
BenchmarkRegistry = {
  ModelClass.detection:      Benchmark(dataset="open-images-det-sample", metric=map_and_per_class_recall),
  ModelClass.classification: Benchmark(dataset="open-images-cls-sample", metric=top1_top5_macrof1),
  # segmentation / pose / lane / face: registered, dataset supplied later (FR-025)
}
```
