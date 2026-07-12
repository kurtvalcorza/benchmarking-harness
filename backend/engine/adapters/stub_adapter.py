"""Deterministic stub adapter for tests and the offline demo.

The "weights" file is a JSON document (owned, committed under samples/) that
describes a synthetic model's skill:

    {
      "kind": "stub-model",
      "task": "detection" | "classification",
      "skill": 0.9,                       # base probability of hitting a GT object
      "class_skill": {"pedestrian": 0.4}, # per-class override (weak-model demo)
      "brightness_sensitivity": 1.0,      # low-light/fog degrade a sensitive model
      "grounding": 0.8,                   # Tier-3 visual-grounding score
      "param_count": 3500000,
      "emit_labels": {"pedestrian": "person"}  # optional: emit a foreign label
                                               # vocabulary (tests the F6 label_map)
    }

Predictions are generated from the dataset's ground truth with per-object,
hash-seeded hits — so the REAL metrics code scores them, degradation under
perturbation is REAL (image brightness/contrast feed the hit probability), and
identical inputs always reproduce identical outputs (SC-004).
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage

from app.db.enums import ModelClass
from engine.adapters.base import AdapterError, Image, ModelDescriptor, Prediction


@dataclass
class StubModel:
    spec: dict
    weights_digest: str
    model_class: ModelClass


def _unit_hash(*parts: str) -> float:
    """Deterministic float in [0, 1) from the given parts."""
    h = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


class StubAdapter:
    def load(self, artifact_ref: str, model_class: ModelClass) -> StubModel:
        try:
            raw = Path(artifact_ref).read_bytes()
            spec = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            raise AdapterError(f"stub weights unreadable: {e}") from e
        if spec.get("kind") != "stub-model":
            raise AdapterError("not a stub-model weights file")
        return StubModel(
            spec=spec,
            weights_digest=hashlib.sha256(raw).hexdigest(),
            model_class=model_class,
        )

    def _skill_for(self, model: StubModel, label: str) -> float:
        return float(model.spec.get("class_skill", {}).get(label, model.spec.get("skill", 0.8)))

    def _quality(self, model: StubModel, img_path: str) -> float:
        """Image-derived quality factor in (0, 1]. Dark / washed-out (perturbed)
        images reduce a brightness-sensitive model's hit probability."""
        sensitivity = float(model.spec.get("brightness_sensitivity", 1.0))
        if sensitivity <= 0:
            return 1.0
        with PILImage.open(img_path) as im:
            g = im.convert("L").resize((16, 16))
            pixels = list(g.getdata())
        mean = sum(pixels) / len(pixels) / 255.0
        contrast = (max(pixels) - min(pixels)) / 255.0
        quality = 0.35 + 0.4 * min(1.0, mean * 2.0) + 0.25 * contrast
        return max(0.05, 1.0 - sensitivity * (1.0 - min(1.0, quality)))

    def predict(self, model: StubModel, images: Iterable[Image]) -> list[Prediction]:
        preds = []
        for img in images:
            gt = _ground_truth_for(img)
            quality = self._quality(model, img.path)
            if model.model_class is ModelClass.classification:
                preds.append(self._predict_cls(model, img, gt, quality))
            elif model.model_class is ModelClass.segmentation:
                preds.append(self._predict_seg(model, img, gt, quality))
            else:
                preds.append(self._predict_det(model, img, gt, quality))
        return preds

    def _predict_det(self, model: StubModel, img: Image, gt: list[dict], quality: float) -> Prediction:
        emit = model.spec.get("emit_labels", {})  # emulate a foreign vocabulary (F6)
        # US5/T065: `grounding` is the model's grounding QUALITY in [0,1] — the
        # probability its attribution point lands inside the object it detects.
        # Reproducible evidence, never a bare confidence scalar.
        grounding_quality = float(model.spec.get("grounding", 0.5))
        # a model that provides NO attribution (only detections + confidence)
        # cannot have its grounding measured — Tier 3 will declare it unavailable
        emit_attribution = bool(model.spec.get("emit_attribution", True))
        boxes, scores, labels, attribution = [], [], [], []
        for i, obj in enumerate(gt):
            label = obj["label"]
            p_hit = self._skill_for(model, label) * quality
            roll = _unit_hash(model.weights_digest, img.id, str(i), label)
            if roll < p_hit:
                box = list(obj["bbox"])
                boxes.append(box)
                scores.append(round(0.5 + 0.5 * p_hit * (1 - roll / 2), 4))
                labels.append(emit.get(label, label))
                if not emit_attribution:
                    continue
                # deterministic attribution point: inside the box with probability
                # `grounding_quality`, otherwise outside it (poorly grounded)
                groll = _unit_hash(model.weights_digest, img.id, str(i), "grounding")
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                point = (
                    [round(cx, 2), round(cy, 2)]
                    if groll < grounding_quality
                    else [round(box[0] - 5.0, 2), round(box[1] - 5.0, 2)]
                )
                # attribution is keyed on the GROUND-TRUTH label (the class the
                # model localizes), independent of any emitted foreign vocabulary
                attribution.append({"label": label, "point": point})
        return Prediction(
            image_id=img.id, boxes=boxes, scores=scores, labels=labels, attribution=attribution
        )

    def _predict_seg(self, model: StubModel, img: Image, gt: list[dict], quality: float) -> Prediction:
        """Deterministic per-instance masks from ground truth (hash-seeded hit/
        miss like detection), so the REAL mIoU scorer runs, degradation under
        perturbation is real, and identical inputs reproduce identical masks
        (SC-004). Emits the GT RLE for each hit instance; a miss omits it (an
        empty mask that lowers IoU — complete accounting)."""
        emit = model.spec.get("emit_labels", {})  # emulate a foreign vocabulary (F6)
        masks = []
        for i, obj in enumerate(gt):
            rle = obj.get("rle")
            if not rle:  # a non-segmentation annotation carries no mask to emit
                continue
            label = obj["label"]
            p_hit = self._skill_for(model, label) * quality
            roll = _unit_hash(model.weights_digest, img.id, str(i), label)
            if roll < p_hit:
                masks.append(
                    {
                        "label": emit.get(label, label),
                        "score": round(0.5 + 0.5 * p_hit * (1 - roll / 2), 4),
                        "rle": rle,
                    }
                )
        return Prediction(image_id=img.id, masks=masks)

    def _predict_cls(self, model: StubModel, img: Image, gt: list[dict], quality: float) -> Prediction:
        true_label = gt[0]["label"] if gt else "unknown"
        p_hit = self._skill_for(model, true_label) * quality
        roll = _unit_hash(model.weights_digest, img.id, true_label)
        if roll < p_hit:
            label = true_label
        else:
            # deterministic wrong answer
            label = f"not_{true_label}"
        return Prediction(
            image_id=img.id,
            label=label,
            class_scores={label: round(0.5 + p_hit / 2, 4)},
        )

    def describe(self, model: StubModel) -> ModelDescriptor:
        return ModelDescriptor(
            framework="stub",
            framework_version="0.1",
            param_count=int(model.spec.get("param_count", 1_000_000)),
            input_spec="RGB HxW (any)",
            extra={"grounding": float(model.spec.get("grounding", 0.5))},
        )


def _ground_truth_for(img: Image) -> list[dict]:
    """The stub reads the dataset's annotations (its 'perception oracle').

    Dataset layout (see engine/datasets.py): <dataset>/annotations.json maps
    image id → [{label, bbox}]. Images live in <dataset>/images/.
    """
    ann_path = Path(img.path).parent.parent / "annotations.json"
    if not ann_path.exists():
        return []
    ann = json.loads(ann_path.read_text())
    return ann.get(img.id, [])
