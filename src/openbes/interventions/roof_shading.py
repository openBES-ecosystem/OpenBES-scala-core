"""
08/10/2026 - HM WIP

Code from chatgpt model - testing roof shading interventions
"""
from dataclasses import dataclass
from .base import ScenarioInputs

@dataclass(frozen=True)
class FixedRoofShade:
    solar_factor: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.solar_factor <= 1.0:
            raise ValueError("solar factor must be between 0 and 1")

    def apply(self, inputs: ScenarioInputs) -> None:
        inputs.roof_solar_factor *= self.solar_factor
