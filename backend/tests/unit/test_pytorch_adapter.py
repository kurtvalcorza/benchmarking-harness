"""PyTorch adapter classification loading (T025 extension).

The classification path accepts an Ultralytics YOLO classification checkpoint
(yolov8n-cls et al. — a dict, loaded via YOLO like detection) or a fully-pickled
timm/torchvision nn.Module. A bare state_dict has no architecture and is rejected
with a clear message rather than crashing with "'dict' has no attribute 'eval'".

The Ultralytics YOLO classify path itself needs the `ml` extra + a real
checkpoint, so it is validated live on the sandbox image (like the detection
path); here we unit-test the shape dispatch that decides which loader runs.
"""

import pytest

from app.db.enums import ModelClass
from engine.adapters.base import AdapterError
from engine.adapters.pytorch_adapter import PyTorchAdapter, _is_ultralytics_checkpoint


def test_is_ultralytics_checkpoint_distinguishes_shapes():
    # an Ultralytics .pt: the model under `model` + training metadata
    assert _is_ultralytics_checkpoint({"model": object(), "train_args": {}, "date": "x"})
    assert _is_ultralytics_checkpoint({"model": object(), "version": "8.3.0"})
    # a bare state_dict: tensor-name keys, no model/metadata
    assert not _is_ultralytics_checkpoint({"backbone.conv.weight": 1, "fc.bias": 2})
    # a lone `model` key without Ultralytics metadata is not enough
    assert not _is_ultralytics_checkpoint({"model": 1})
    # non-dicts (a pickled module, a list, None) are not checkpoints
    assert not _is_ultralytics_checkpoint(object())
    assert not _is_ultralytics_checkpoint([1, 2, 3])
    assert not _is_ultralytics_checkpoint(None)


def test_classification_rejects_bare_state_dict(tmp_path):
    """A state_dict (what `torch.save(model.state_dict(), ...)` writes) has no
    architecture; the adapter must reject it clearly, not raise a bare
    AttributeError that surfaces as an opaque infra failure."""
    torch = pytest.importorskip("torch")  # skipped where the ml extra is absent (CI)
    path = tmp_path / "state_dict.pt"
    torch.save({"backbone.weight": torch.zeros(2, 2), "fc.bias": torch.zeros(2)}, path)
    with pytest.raises(AdapterError) as exc:
        PyTorchAdapter().load(str(path), ModelClass.classification)
    msg = str(exc.value)
    assert "state_dict" in msg or "architecture" in msg
