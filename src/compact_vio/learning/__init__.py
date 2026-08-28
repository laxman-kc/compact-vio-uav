"""Optional compact learned visual-inertial training stack.

The configuration and target geometry remain importable without PyTorch or
Pillow. Tensor/model APIs are loaded only when explicitly requested.
"""

from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
from compact_vio.learning.errors import LearningDependencyError, LearningError
from compact_vio.learning.geometry import RelativeMotionTarget, relative_motion_target

__all__ = [
    "LearningDependencyError",
    "LearningError",
    "DataConfig",
    "ModelConfig",
    "RelativeMotionTarget",
    "TrainingConfig",
    "relative_motion_target",
]
