"""ONNX adapter (T026): ONNX Runtime, CPU execution provider (POC).

Requires the `ml` extra (onnxruntime). Lazy-imported; unavailable runtime is
an infra condition (AdapterError), never a model `fail`.

POC convention for ONNX models: single image input NCHW float32 [0,1];
detection output = (boxes[N,4], scores[N], class_ids[N]); classification
output = logits[1, C]. Class names may ride in model metadata `class_names`
(JSON list).
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image as PILImage

from app.db.enums import ModelClass
from engine.adapters.base import AdapterError, Image, ModelDescriptor, Prediction


@dataclass
class OnnxModel:
    task: ModelClass
    session: Any
    class_names: list[str]
    framework_version: str
    input_name: str
    input_hw: tuple[int, int]


class OnnxAdapter:
    def load(self, artifact_ref: str, model_class: ModelClass) -> OnnxModel:
        try:
            import onnxruntime as ort
        except ImportError as e:
            raise AdapterError("onnxruntime not installed (pip install '.[ml]')") from e
        if model_class not in (ModelClass.detection, ModelClass.classification):
            raise AdapterError(
                f"onnx adapter has no runner for model class '{model_class.value}' in the POC"
            )
        try:
            sess = ort.InferenceSession(artifact_ref, providers=["CPUExecutionProvider"])
        except Exception as e:
            raise AdapterError(f"failed to load onnx model: {e}") from e
        meta = sess.get_modelmeta().custom_metadata_map or {}
        names = json.loads(meta.get("class_names", "[]"))
        inp = sess.get_inputs()[0]
        shape = inp.shape
        hw = (
            int(shape[2]) if isinstance(shape[2], int) else 224,
            int(shape[3]) if isinstance(shape[3], int) else 224,
        )
        return OnnxModel(
            task=model_class,
            session=sess,
            class_names=names,
            framework_version=ort.__version__,
            input_name=inp.name,
            input_hw=hw,
        )

    def _tensor(self, model: OnnxModel, img: Image) -> np.ndarray:
        im = PILImage.open(img.path).convert("RGB").resize(model.input_hw[::-1])
        x = np.asarray(im, dtype=np.float32) / 255.0
        return x.transpose(2, 0, 1)[None, ...]

    def predict(self, model: OnnxModel, images: Iterable[Image]) -> list[Prediction]:
        preds = []
        try:
            for img in images:
                out = model.session.run(None, {model.input_name: self._tensor(model, img)})
                if model.task is ModelClass.detection:
                    boxes, scores, cls_ids = out[0], out[1], out[2]
                    preds.append(
                        Prediction(
                            image_id=img.id,
                            boxes=[[float(v) for v in b] for b in np.asarray(boxes).reshape(-1, 4)],
                            scores=[float(s) for s in np.asarray(scores).reshape(-1)],
                            labels=[
                                self._name(model, int(c)) for c in np.asarray(cls_ids).reshape(-1)
                            ],
                        )
                    )
                else:
                    logits = np.asarray(out[0]).reshape(-1)
                    e = np.exp(logits - logits.max())
                    probs = e / e.sum()
                    top = int(probs.argmax())
                    preds.append(
                        Prediction(
                            image_id=img.id,
                            label=self._name(model, top),
                            class_scores={
                                self._name(model, i): float(p) for i, p in enumerate(probs)
                            },
                        )
                    )
        except AdapterError:
            raise
        except Exception as e:
            raise AdapterError(f"onnx inference failed: {e}") from e
        return preds

    def _name(self, model: OnnxModel, idx: int) -> str:
        return model.class_names[idx] if idx < len(model.class_names) else str(idx)

    def describe(self, model: OnnxModel) -> ModelDescriptor:
        return ModelDescriptor(
            framework="onnx",
            framework_version=model.framework_version,
            param_count=None,  # not recoverable from a session without onnx graph walk
            input_spec=f"NCHW float32 {model.input_hw}",
        )
