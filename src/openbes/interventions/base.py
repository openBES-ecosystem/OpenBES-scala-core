"""
08/10/2026 - HM WIP

Code from chatgpt model
"""

from dataclasses import dataclass
from typing import Protocol

from openbes.types import OpenBESSpecification

@dataclass
class ScenarioInputs:
    """Inputs used by one scenario
    HM note: ScenarioInputs holds the inputs for one run in this case roof_solar_factor = 1.0, so it's a scenario
    with no roof shading intervention.
    """
    spec: OpenBESSpecification
    roof_solar_factor:float = 1.0

class Intervention(Protocol):
    """An intervention must provide an apply() method
    HM note: Intervention describes the interface the wrapper expects - an object with an apply() method.
    Other interventions e.g. wall shading can follow the same interface
    """
    def apply(self, inputs:ScenarioInputs) -> None:
        ...