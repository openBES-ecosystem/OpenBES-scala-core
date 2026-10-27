"""
Single sided ventilation with one opening using equations from SheltAir paper

Equations also identified in cooling strategies tables

"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .base import ScenarioInputs


@dataclass(frozen=True)
class SheltAirSingleOpening:
    """Settings for one openable aperture."""

    window_id: str
    max_free_area_m2: float
    opening_height_m: float

    driving_force: Literal["wind", "buoyancy"]

    # Assumed ratio:
    # wind speed at opening / weather-file wind speed.
    local_wind_factor: float

    opening_fraction: float = 1.0

    open_above_c: float = 24.0
    close_below_c: float = 23.0
    min_cooling_difference_c: float = 1.0

    open_from_hour: float = 8.0
    open_until_hour: float = 22.0
    months: tuple[int, ...] = tuple(range(1, 13))

    def __post_init__(self):
        if not isinstance(self.window_id, str) or not self.window_id:
            raise ValueError("A window ID is required.")

        if self.driving_force not in ("wind", "buoyancy"):
            raise ValueError(
                "driving_force must be 'wind' or 'buoyancy'."
            )

        numeric_fields = (
            "max_free_area_m2",
            "opening_height_m",
            "local_wind_factor",
            "opening_fraction",
            "open_above_c",
            "close_below_c",
            "min_cooling_difference_c",
            "open_from_hour",
            "open_until_hour",
        )

        for name in numeric_fields:
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite.")

        if self.max_free_area_m2 <= 0 or self.opening_height_m <= 0:
            raise ValueError("Opening area and height must be positive.")

        if self.local_wind_factor < 0:
            raise ValueError("Local wind factor cannot be negative.")

        if not 0 <= self.opening_fraction <= 1:
            raise ValueError("Opening fraction must be between 0 and 1.")

        if self.close_below_c >= self.open_above_c:
            raise ValueError(
                "Closing temperature must be below opening temperature."
            )

        if self.min_cooling_difference_c < 0:
            raise ValueError("Cooling difference cannot be negative.")

        if not 0 <= self.open_from_hour < 24:
            raise ValueError("Opening start time must be in [0, 24).")

        if not 0 <= self.open_until_hour <= 24:
            raise ValueError("Opening end time must be in [0, 24].")

        if self.open_from_hour == self.open_until_hour:
            raise ValueError(
                "Use 0 to 24 for all-day operation; "
                "use opening_fraction=0 for always closed."
            )

        if any(
                not isinstance(month, int) or not 1 <= month <= 12
                for month in self.months
        ):
            raise ValueError("Months must be integers from 1 to 12.")

    def apply(self, inputs: ScenarioInputs) -> None:
        if inputs.sheltair_ventilation is not None:
            raise ValueError(
                "Only one SheltAir opening can be configured per scenario."
            )

        inputs.sheltair_ventilation = self