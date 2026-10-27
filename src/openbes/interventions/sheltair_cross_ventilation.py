"""Settings for the two-opening cross-ventilation equations in SheltAir.

This intervention uses the existing ScenarioInputs.sheltair_ventilation slot.
Update its type annotation to accept SheltAirCrossVentilation as well as
SheltAirSingleOpening. Only one opening model is applied in each scenario.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .base import ScenarioInputs


@dataclass(frozen=True)
class SheltAirCrossVentilation:
    """Two apertures on different facades, with a shared opening control.

    Areas are geometric free areas before applying the discharge coefficient.
    centre_height_difference_m is the absolute vertical distance between the
    aperture centres; it is not the aperture height or their horizontal spacing.
    delta_cp is the non-negative magnitude of the facade Cp difference.
    reference_wind_factor maps EPW wind to the reference speed used for those
    pressure coefficients. These two wind assumptions must be consistent.
    """

    window_ids: tuple[str, str]
    max_free_areas_m2: tuple[float, float]
    centre_height_difference_m: float
    driving_force: Literal["wind", "buoyancy"]
    reference_wind_factor: float
    delta_cp: float

    opening_fraction: float = 1.0
    open_above_c: float = 24.0
    close_below_c: float = 23.0
    min_cooling_difference_c: float = 1.0
    open_from_hour: float = 8.0
    open_until_hour: float = 22.0
    months: tuple[int, ...] = tuple(range(1, 13))

    def __post_init__(self):
        if (
                len(self.window_ids) != 2
                or any(not isinstance(w, str) or not w for w in self.window_ids)
                or self.window_ids[0] == self.window_ids[1]
        ):
            raise ValueError("Supply two distinct, non-empty window IDs.")

        if len(self.max_free_areas_m2) != 2:
            raise ValueError("Supply exactly two maximum free opening areas.")

        if self.driving_force not in ("wind", "buoyancy"):
            raise ValueError("driving_force must be 'wind' or 'buoyancy'.")

        numeric = (
            *self.max_free_areas_m2,
            self.centre_height_difference_m,
            self.reference_wind_factor,
            self.delta_cp,
            self.opening_fraction,
            self.open_above_c,
            self.close_below_c,
            self.min_cooling_difference_c,
            self.open_from_hour,
            self.open_until_hour,
        )

        if not all(isfinite(value) for value in numeric):
            raise ValueError("All numeric settings must be finite.")

        if min(self.max_free_areas_m2) <= 0:
            raise ValueError("Maximum free opening areas must be positive.")

        if min(
                self.centre_height_difference_m,
                self.reference_wind_factor,
                self.delta_cp,
                self.min_cooling_difference_c,
        ) < 0:
            raise ValueError(
                "Height difference, wind inputs and cooling gap cannot be negative."
            )

        if not 0 <= self.opening_fraction <= 1:
            raise ValueError("opening_fraction must be between zero and one.")

        if self.close_below_c >= self.open_above_c:
            raise ValueError(
                "Closing temperature must be below opening temperature."
            )

        if not 0 <= self.open_from_hour < 24:
            raise ValueError("open_from_hour must be in [0, 24).")

        if not 0 <= self.open_until_hour <= 24:
            raise ValueError("open_until_hour must be in [0, 24].")

        if self.open_from_hour == self.open_until_hour:
            raise ValueError(
                "Use 0 to 24 for all day, or opening_fraction=0 for closed."
            )

        if any(
                not isinstance(m, int)
                or isinstance(m, bool)
                or not 1 <= m <= 12
                for m in self.months
        ):
            raise ValueError("Months must be integers from 1 to 12.")

    def apply(self, inputs: ScenarioInputs) -> None:
        if inputs.sheltair_ventilation is not None:
            raise ValueError("Use one SheltAir opening model per scenario.")

        inputs.sheltair_ventilation = self