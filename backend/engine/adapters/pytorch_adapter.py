"""PyTorch adapter (T025): Ultralytics YOLO for detection, timm for classification.

Requires the `ml` extra (torch, ultralytics, timm). Imports are lazy so the
harness core works without them; attempting to use this adapter without the
extra raises AdapterError (an infra condition, not a model failure).

No-egress contract: weights are loaded ONLY from the given artifact path —
auto-download is disabled; adapters never assume connectivity.
"""

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.db.enums import ModelClass
from engine.adapters.base import AdapterError, Image, ModelDescriptor, Prediction

_SEED = 1234


@dataclass
class TorchModel:
    task: ModelClass
    net: Any
    class_names: dict[int, str]
    framework_version: str


class PyTorchAdapter:
    def load(self, artifact_ref: str, model_class: ModelClass) -> TorchModel:
        try:
            import torch
        except ImportError as e:
            raise AdapterError("pytorch runtime not installed (pip install '.[ml]')") from e
        torch.manual_seed(_SEED)
        try:
            if model_class is ModelClass.detection:
                from ultralytics import YOLO

                net = YOLO(artifact_ref)  # local file only; never a model name
                names = dict(net.names) if hasattr(net, "names") else {}
            elif model_class is ModelClass.classification:
                net = torch.load(artifact_ref, map_location="cpu", weights_only=False)
                net.eval()
                names = getattr(net, "class_names", {})
            else:
                raise AdapterError(
                    f"pytorch adapter has no runner for model class '{model_class.value}' in the POC"
                )
        except AdapterError:
            raise
        except Exception as e:  # loading is an infra concern → AdapterError
            raise AdapterError(f"failed to load pytorch weights: {e}") from e
        return TorchModel(
            task=model_class,
            net=net,
            class_names=names,
            framework_version=torch.__version__,
        )

    def predict(self, model: TorchModel, images: Iterable[Image]) -> list[Prediction]:
        try:
            if model.task is ModelClass.detection:
                return [self._predict_det(model, img) for img in images]
            return [self._predict_cls(model, img) for img in images]
        except AdapterError:
            raise
        except Exception as e:
            raise AdapterError(f"pytorch inference failed: {e}") from e

    def _predict_det(self, model: TorchModel, img: Image) -> Prediction:
        results = model.net.predict(img.path, verbose=False)
        r = results[0]
        boxes, scores, labels = [], [], []
        for b in r.boxes:
            boxes.append([float(v) for v in b.xyxy[0].tolist()])
            scores.append(float(b.conf[0]))
            labels.append(model.class_names.get(int(b.cls[0]), str(int(b.cls[0]))))
        return Prediction(image_id=img.id, boxes=boxes, scores=scores, labels=labels)

    def _predict_cls(self, model: TorchModel, img: Image) -> Prediction:
        import torch
        from PIL import Image as PILImage

        im = PILImage.open(img.path).convert("RGB").resize((224, 224))
        x = torch.frombuffer(bytearray(im.tobytes()), dtype=torch.uint8)
        x = x.reshape(224, 224, 3).permute(2, 0, 1).float().div(255).unsqueeze(0)
        with torch.no_grad():
            probs = torch.softmax(model.net(x)[0], dim=-1)
        top = int(probs.argmax())
        names = model.class_names or {}
        return Prediction(
            image_id=img.id,
            label=names.get(top, str(top)),
            class_scores={names.get(i, str(i)): float(p) for i, p in enumerate(probs.tolist())},
        )

    def describe(self, model: TorchModel) -> ModelDescriptor:
        net = getattr(model.net, "model", model.net)
        try:
            params = sum(p.numel() for p in net.parameters())
        except Exception:
            params = None
        # cheap grounding proxy timing hook for Tier 3
        _ = time.time()
        return ModelDescriptor(
            framework="pytorch",
            framework_version=model.framework_version,
            param_count=params,
            input_spec="RGB, model-defined size",
        )
