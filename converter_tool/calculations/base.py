from typing import Dict, Any
from abc import ABC, abstractmethod

class ConverterDesign(ABC):
    """Abstract base class for converter design calculators."""

    def __init__(self, core_library: Dict[str, Any] | None = None) -> None:
        self.core_library = core_library

    @abstractmethod
    def run_calculation(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Run calculation using ``cfg`` and return structured results."""
        raise NotImplementedError