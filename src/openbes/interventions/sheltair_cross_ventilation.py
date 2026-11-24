"""Settings for SheltAir cross-ventilation and same-façade buoyancy."""

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

        if self.driving_force not in ("wind", "buoyancy"):
            raise ValueError("driving_force must be 'wind' or 'buoyancy'.")

        if not all(isfinite(value) and value >= 0 for value in (
            self.reference_wind_factor, self.delta_cp
        )):
            raise ValueError("Wind settings must be finite and non-negative.")
        _validate_two_opening_controls(self)

    def apply(self, inputs: ScenarioInputs) -> None:
        _apply_two_opening_ventilation(self, inputs)


@dataclass(frozen=True)
class SheltAirSingleSidedTwoOpenings:
    """Two openings on the same façade using SheltAir equation 3.

    Specify the free areas of the lower and upper openings in that order.
    The openings can be windows, doors or vents. Their areas and centre
    separation are supplied directly for the scenario.
    """

    max_free_areas_m2: tuple[float, float]
    centre_height_difference_m: float
    opening_fraction: float = 1.0
    open_above_c: float = 24.0
    close_below_c: float = 23.0
    min_cooling_difference_c: float = 1.0
    open_from_hour: float = 8.0
    open_until_hour: float = 22.0
    months: tuple[int, ...] = tuple(range(1, 13))

    def __post_init__(self) -> None:
        _validate_two_opening_controls(self)

    def apply(self, inputs: ScenarioInputs) -> None:
        _apply_two_opening_ventilation(self, inputs)


def _validate_two_opening_controls(
    settings: SheltAirCrossVentilation | SheltAirSingleSidedTwoOpenings,
) -> None:
    if len(settings.max_free_areas_m2) != 2:
        raise ValueError("Supply exactly two maximum free opening areas.")

    numeric = (
        *settings.max_free_areas_m2,
        settings.centre_height_difference_m,
        settings.opening_fraction,
        settings.open_above_c,
        settings.close_below_c,
        settings.min_cooling_difference_c,
        settings.open_from_hour,
        settings.open_until_hour,
    )
    if not all(isfinite(value) for value in numeric):
        raise ValueError("All numeric settings must be finite.")
    if min(settings.max_free_areas_m2) <= 0:
        raise ValueError("Maximum free opening areas must be positive.")
    if min(settings.centre_height_difference_m, settings.min_cooling_difference_c) < 0:
        raise ValueError("Height difference and cooling gap cannot be negative.")

    if not 0 <= settings.opening_fraction <= 1:
        raise ValueError("opening_fraction must be between zero and one.")
    if settings.close_below_c >= settings.open_above_c:
        raise ValueError("Closing temperature must be below opening temperature.")
    if not 0 <= settings.open_from_hour < 24:
        raise ValueError("open_from_hour must be in [0, 24).")
    if not 0 <= settings.open_until_hour <= 24:
        raise ValueError("open_until_hour must be in [0, 24].")
    if settings.open_from_hour == settings.open_until_hour:
        raise ValueError("Use 0 to 24 for all day, or opening_fraction=0 for closed.")
    if any(
        not isinstance(month, int) or isinstance(month, bool) or not 1 <= month <= 12
        for month in settings.months
    ):
        raise ValueError("Months must be integers from 1 to 12.")


def _apply_two_opening_ventilation(
    settings: SheltAirCrossVentilation | SheltAirSingleSidedTwoOpenings,
    inputs: ScenarioInputs,
) -> None:
    if inputs.sheltair_ventilation is not None:
        raise ValueError("Use one SheltAir opening model per scenario.")
    inputs.sheltair_ventilation = settings
