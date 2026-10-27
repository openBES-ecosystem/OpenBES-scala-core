from __future__ import annotations

from math import isfinite, sqrt
from typing import TYPE_CHECKING

from ..interventions.sheltair_ventilation import (
    SheltAirSingleOpening,
)

if TYPE_CHECKING:
    from .window_shading import WindowGeometry


# Conzatti et al. (2026), SheltAir, equations 1 and 2.
# DOI: 10.1016/j.indenv.2026.100154
WIND_COEFFICIENT = 0.025
DISCHARGE_COEFFICIENT = 0.6
GRAVITY = 9.81
PAPER_KELVIN_OFFSET = 273.0


def wind_flow_m3_s(
        area_m2: float,
        opening_wind_speed_m_s: float,
) -> float:
    """SheltAir equation 1."""

    if not all(
            isfinite(value)
            for value in (area_m2, opening_wind_speed_m_s)
    ):
        raise ValueError("Wind-flow inputs must be finite.")

    if area_m2 < 0 or opening_wind_speed_m_s < 0:
        raise ValueError("Area and wind speed cannot be negative.")

    return WIND_COEFFICIENT * area_m2 * opening_wind_speed_m_s


def buoyancy_flow_m3_s(
        area_m2: float,
        opening_height_m: float,
        indoor_temp_c: float,
        outdoor_temp_c: float,
) -> float:
    """SheltAir equation 2 as printed, without a 1/3 prefactor."""

    if not all(
            isfinite(value)
            for value in (
                    area_m2,
                    opening_height_m,
                    indoor_temp_c,
                    outdoor_temp_c,
            )
    ):
        raise ValueError("Buoyancy-flow inputs must be finite.")

    if area_m2 < 0 or opening_height_m <= 0:
        raise ValueError("Area must be non-negative and height positive.")

    mean_temperature_k = (
            (indoor_temp_c + outdoor_temp_c) / 2.0
            + PAPER_KELVIN_OFFSET
    )

    if mean_temperature_k <= 0:
        raise ValueError("Mean absolute temperature must be positive.")

    temperature_difference = abs(indoor_temp_c - outdoor_temp_c)

    return (
            DISCHARGE_COEFFICIENT
            * area_m2
            * sqrt(
        GRAVITY
        * opening_height_m
        * temperature_difference
        / mean_temperature_k
    )
    )


def empty_sheltair_details() -> dict[str, float]:
    """Numeric diagnostics used for both enabled and disabled cases."""

    return {
        "sa_opening_fraction": 0.0,
        "sa_open_area_m2": 0.0,
        "sa_opening_wind_m_s": 0.0,
        "sa_wind_candidate_m3_h": 0.0,
        "sa_buoyancy_candidate_m3_h": 0.0,
        "sa_applied_m3_h": 0.0,
        "sa_ach": 0.0,
    }


class SheltAirOpeningModel:
    """One-opening model with an independent open/closed state."""

    def __init__(
            self,
            settings: SheltAirSingleOpening,
            windows: tuple[WindowGeometry, ...],
    ):
        self.settings = settings
        self._is_open = False

        lookup = {
            window.window_id: window
            for window in windows
        }

        if settings.window_id not in lookup:
            raise ValueError(
                f"Unknown window ID: {settings.window_id}. "
                f"Available IDs: {sorted(lookup)}"
            )

        window = lookup[settings.window_id]

        if settings.opening_height_m > window.height_m + 1e-9:
            raise ValueError(
                "Opening height exceeds the nominal window height."
            )

        available_area = window.width_m * settings.opening_height_m

        if settings.max_free_area_m2 > available_area + 1e-9:
            raise ValueError(
                "Free area exceeds the available rectangular aperture."
            )

    def calculate(
            self,
            *,
            indoor_temp_c: float | None,
            outdoor_temp_c: float,
            weather_wind_speed_m_s: float,
            month: int,
            hour_midpoint: float,
    ) -> dict[str, float]:

        result = empty_sheltair_details()
        settings = self.settings

        if not all(
                isfinite(value)
                for value in (outdoor_temp_c, weather_wind_speed_m_s)
        ):
            raise ValueError("Weather inputs must be finite.")

        if weather_wind_speed_m_s < 0:
            raise ValueError("Weather wind speed cannot be negative.")

        opening_wind = (
                weather_wind_speed_m_s
                * settings.local_wind_factor
        )

        if not isfinite(opening_wind):
            raise ValueError("Calculated opening wind speed is not finite.")

        result["sa_opening_wind_m_s"] = opening_wind

        # The first timestep has no previous indoor-temperature result.
        if indoor_temp_c is None:
            self._is_open = False
            return result

        if not isfinite(indoor_temp_c):
            raise ValueError("Indoor temperature must be finite.")

        if settings.open_from_hour < settings.open_until_hour:
            permitted_time = (
                    settings.open_from_hour
                    <= hour_midpoint
                    < settings.open_until_hour
            )
        else:
            # Supports an overnight period, e.g. 22:00 to 07:00.
            permitted_time = (
                    hour_midpoint >= settings.open_from_hour
                    or hour_midpoint < settings.open_until_hour
            )

        cool_outside = (
                indoor_temp_c - outdoor_temp_c
                >= settings.min_cooling_difference_c
        )

        eligible = (
                month in settings.months
                and permitted_time
                and cool_outside
                and settings.opening_fraction > 0
        )

        if not eligible:
            self._is_open = False
        elif self._is_open:
            if indoor_temp_c <= settings.close_below_c:
                self._is_open = False
        elif indoor_temp_c >= settings.open_above_c:
            self._is_open = True

        if not self._is_open:
            return result

        area_m2 = (
                settings.max_free_area_m2
                * settings.opening_fraction
        )

        wind_candidate = wind_flow_m3_s(
            area_m2=area_m2,
            opening_wind_speed_m_s=opening_wind,
        )

        buoyancy_candidate = buoyancy_flow_m3_s(
            area_m2=area_m2,
            opening_height_m=settings.opening_height_m,
            indoor_temp_c=indoor_temp_c,
            outdoor_temp_c=outdoor_temp_c,
        )

        if settings.driving_force == "wind":
            applied_flow = wind_candidate
        else:
            applied_flow = buoyancy_candidate

        result.update(
            {
                "sa_opening_fraction": settings.opening_fraction,
                "sa_open_area_m2": area_m2,
                "sa_wind_candidate_m3_h": 3600.0 * wind_candidate,
                "sa_buoyancy_candidate_m3_h": 3600.0 * buoyancy_candidate,
                "sa_applied_m3_h": 3600.0 * applied_flow,
            }
        )

        return result