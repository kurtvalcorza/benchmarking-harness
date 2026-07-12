"""PyTorch adapter classification loading (T025 extension).

The classification path accepts an Ultralytics YOLO classification checkpoint
(yolov8n-cls et al. — tried via YOLO() first, which owns the legacy-checkpoint
compatibility path and loads once) or a fully-pickled timm/torchvision nn.Module.
A bare state_dict has no architecture and is rejected with a clear message rather
than crashing with "'dict' has no attribute 'eval'".

The Ultralytics YOLO classify path itself needs the ml extra + a real checkpoint,
so it is validated live on the sandbox image (like the detection path); here we
unit-test the fallback that rejects an un-loadable artifact.
"""

import pytest

from app.db.enums import ModelClass
from engine.adapters.base import AdapterError
from engine.adapters.pytorch_adapter import PyTorchAdapter


def test_classification_rejects_bare_state_dict(tmp_path):
    """A state_dict (what `torch.save(model.state_dict(), ...)` writes) has no
    architecture: YOLO() cannot load it and it is not a pickled module, so the
    adapter must reject it clearly, not raise an opaque error that surfaces as an
    unexplained infra failure."""
    torch = pytest.importorskip("torch")  # skipped where the ml extra is absent (CI)
    pytest.importorskip("ultralytics")
    path = tmp_path / "state_dict.pt"
    torch.save({"backbone.weight": torch.zeros(2, 2), "fc.bias": torch.zeros(2)}, path)
    with pytest.raises(AdapterError) as exc:
        PyTorchAdapter().load(str(path), ModelClass.classification)
    msg = str(exc.value)
    assert "state_dict" in msg or "architecture" in msg


def test_segmentation_rejects_non_seg_checkpoint(tmp_path):
    """A checkpoint that cannot load as an Ultralytics -seg model (here a bare
    state_dict) under the segmentation class must raise a clear AdapterError
    naming the segmentation requirement — never a silent empty mask set.

    The real yolov8n-seg.pt load + the task=='segment' check are validated live
    on the sandbox image (like the detection/classification YOLO paths, which
    need the ml extra + a real checkpoint)."""
    torch = pytest.importorskip("torch")
    pytest.importorskip("ultralytics")
    path = tmp_path / "state_dict.pt"
    torch.save({"backbone.weight": torch.zeros(2, 2)}, path)
    with pytest.raises(AdapterError) as exc:
        PyTorchAdapter().load(str(path), ModelClass.segmentation)
    assert "segment" in str(exc.value).lower()
