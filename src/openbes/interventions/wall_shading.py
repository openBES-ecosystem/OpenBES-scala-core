"""
12/10/2026 HM WIP: Wall shading intervention

Code drafted from Chatgpt

"""
from dataclasses import dataclass

from openbes.types import COMPASS_POINTS

from .base import ScenarioInputs


@dataclass(frozen=True)
class FixedWallShade:
    solar_factor: float

    # None means all opaque façade directions.
    compass_points: tuple[COMPASS_POINTS, ...] | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.solar_factor <= 1.0:
            raise ValueError(
                "solar_factor must be between 0 and 1."
            )

        if self.compass_points is not None:
            if not self.compass_points:
                raise ValueError(
                    "Select at least one façade direction."
                )

            if any(
                    not isinstance(point, COMPASS_POINTS)
                    for point in self.compass_points
            ):
                raise TypeError(
                    "Use COMPASS_POINTS values for façade directions."
                )

    def apply(self, inputs: ScenarioInputs) -> None:
        # Preserve the original all-façade behaviour.
        if self.compass_points is None:
            inputs.wall_solar_factor *= self.solar_factor
            return

        # Apply shading only to the selected directions.
        for point in set(self.compass_points):
            current_factor = inputs.wall_solar_factors.get(
                point,
                1.0,
            )

            inputs.wall_solar_factors[point] = (
                    current_factor * self.solar_factor
            )