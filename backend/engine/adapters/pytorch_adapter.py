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
    is_yolo: bool = False  # net is an Ultralytics YOLO (vs a raw timm/torchvision module)


def _try_load_yolo(artifact_ref: str) -> Any | None:
    """Load `artifact_ref` as an Ultralytics YOLO checkpoint, or return None if
    it is not one (a fully-pickled timm/torchvision module or a bare state_dict).

    Ultralytics' own loader owns the compatibility path for legacy/renamed
    checkpoint modules (torch_safe_load aliases `ultralytics.yolo.*` etc.), so it
    is the right FIRST attempt for any .pt that might be a YOLO checkpoint —
    a raw torch.load peek would spuriously fail those. It also loads the weights
    exactly once (no second full copy held alive alongside a peek), which matters
    in the memory-constrained sandbox (Codex #11)."""
    from ultralytics import YOLO

    try:
        return YOLO(artifact_ref)  # local file only; never a model name
    except Exception:
        return None


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
                is_yolo = True
            elif model_class is ModelClass.classification:
                # Two shapes score as classification here: an Ultralytics YOLO
                # classification checkpoint (yolov8n-cls et al., loaded via YOLO
                # like the detection path) or a fully-pickled timm/torchvision
                # nn.Module. Try the Ultralytics loader FIRST — it owns the
                # legacy-checkpoint compat path and loads once — and only fall
                # back to torch.load for a non-Ultralytics artifact (Codex #11).
                yolo = _try_load_yolo(artifact_ref)
                if yolo is not None:
                    if yolo.task != "classify":
                        raise AdapterError(
                            f"Ultralytics checkpoint has task '{yolo.task}', not a "
                            "classifier; submit it under its actual model class"
                        )
                    net = yolo
                    names = dict(yolo.names) if getattr(yolo, "names", None) else {}
                    if not names:
                        # without a class vocabulary, predictions fall back to
                        # numeric labels that match neither the dataset nor the
                        # label_map — fail loud rather than silently score ~0
                        raise AdapterError(
                            "Ultralytics classification checkpoint exposes no class "
                            "names; cannot map predictions to a label space"
                        )
                    is_yolo = True
                else:
                    obj = torch.load(artifact_ref, map_location="cpu", weights_only=False)
                    if isinstance(obj, torch.nn.Module):
                        obj.eval()
                        net = obj
                        names = getattr(net, "class_names", {})
                        is_yolo = False
                    else:
                        # a bare state_dict carries no architecture to reconstruct
                        raise AdapterError(
                            "classification weights must be a pickled nn.Module "
                            "(timm/torchvision) or an Ultralytics YOLO classification "
                            f"checkpoint; got a bare '{type(obj).__name__}' with no "
                            "model architecture (e.g. a state_dict)"
                        )
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
            is_yolo=is_yolo,
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
        if model.is_yolo:
            # Ultralytics classification: predict() returns a Probs over the
            # model's class vocabulary. Emit the top-1 label + the full score
            # vector so canonicalize() (F6 label_map) and top-5 both work.
            r = model.net.predict(img.path, verbose=False)[0]
            probs = r.probs
            if probs is None:
                raise AdapterError("ultralytics model returned no classification probabilities")
            names = model.class_names
            data = probs.data.tolist()
            return Prediction(
                image_id=img.id,
                label=names.get(int(probs.top1), str(int(probs.top1))),
                class_scores={names.get(i, str(i)): float(p) for i, p in enumerate(data)},
            )

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
