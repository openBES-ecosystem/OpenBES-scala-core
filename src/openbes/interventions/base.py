"""
08/10/2026 - HM WIP

Code from chatgpt model
"""

from dataclasses import dataclass, field
from typing import Protocol

from openbes.types import COMPASS_POINTS, OpenBESSpecification

from .window_overhang import ScheduledWindowShade

from .sheltair_ventilation import SheltAirSingleOpening

from .sheltair_cross_ventilation import SheltAirCrossVentilation

@dataclass
class ScenarioInputs:
    """Inputs used by one scenario
    HM note: ScenarioInputs holds the inputs for one run in this case roof_solar_factor = 1.0, so it's a scenario
    with no roof shading intervention.

    Interventions added:
    Roof shading
    Wall shading
    Window shading (dynamic)
    Single-sided and single opening ventilation - using SheltAir equations

    """
    spec: OpenBESSpecification
    roof_solar_factor:float = 1.0

    # Factor applied to all opaque facades
    wall_solar_factor:float = 1.0

    # Additional factors applied to selected facade directions
    # default_factory = dict creates a separate empty dictionary for every scenario
    wall_solar_factors: dict[COMPASS_POINTS, float] = field(default_factory=dict)

    #adding window shading scenarios
    window_shades: list[ScheduledWindowShade] = field(
        default_factory=list
    )
    sheltair_ventilation: (
            SheltAirSingleOpening | SheltAirCrossVentilation | None
    ) = None # none means additional wind ventilation model is disabled

class Intervention(Protocol):
    """An intervention must provide an apply() method
    HM note: Intervention describes the interface the wrapper expects - an object with an apply() method.
    Other interventions e.g. wall shading can follow the same interface
    """
    def apply(self, inputs:ScenarioInputs) -> None:
        ...