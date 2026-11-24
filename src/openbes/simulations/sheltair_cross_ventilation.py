"""SheltAir two-opening ventilation, equations 3-7 as printed.

Source: Conzatti et al. (2026), Indoor Environments 3, 100154.
DOI: 10.1016/j.indenv.2026.100154, section 2.1.1, page 3.

The functions return an outdoor-air exchange magnitude in m3/s. One throughflow
passes through both openings: do not add its inlet and outlet magnitudes.
Wind and buoyancy candidates are evaluated separately, without max() or addition.
"""

from __future__ import annotations

from math import hypot, isfinite, sqrt
from typing import TYPE_CHECKING

from ..interventions.sheltair_cross_ventilation import (
    SheltAirCrossVentilation,
    SheltAirSingleSidedTwoOpenings,
)
from .sheltair_ventilation import empty_sheltair_details

if TYPE_CHECKING:
    from .window_shading import WindowGeometry


DISCHARGE_COEFFICIENT = 0.6
GRAVITY_M_S2 = 9.81
PAPER_KELVIN_OFFSET = 273.0


def equivalent_areas_m2(
        area_1_m2: float,
        area_2_m2: float,
) -> tuple[float, float]:
    """Return (Aw, Ab) from equations 5 and 7.

    Either closed path gives zero.

    Aw = A1*A2 / sqrt(A1**2 + A2**2)
    Ab = A1*A2 / (A1 + A2)

    The ratio form below is algebraically identical and avoids large products.
    """

    if not all(
            isfinite(a) and a >= 0
            for a in (area_1_m2, area_2_m2)
    ):
        raise ValueError(
            "Opening areas must be finite and non-negative."
        )

    smaller, larger = sorted((area_1_m2, area_2_m2))

    if smaller == 0:
        return 0.0, 0.0

    ratio = smaller / larger

    return (
        smaller / sqrt(1.0 + ratio**2),
        smaller / (1.0 + ratio),
    )


def cross_wind_flow_m3_s(
        area_1_m2: float,
        area_2_m2: float,
        reference_wind_speed_m_s: float,
        delta_cp: float,
) -> float:
    """Equations 4-5: Qw = 0.6 * Aw * vr * sqrt(delta_cp).

    delta_cp is a magnitude. This function does not determine flow direction.
    """

    if not all(
            isfinite(v) and v >= 0
            for v in (reference_wind_speed_m_s, delta_cp)
    ):
        raise ValueError(
            "Reference wind speed and delta_cp must be finite "
            "and non-negative."
        )

    area_wind, _ = equivalent_areas_m2(
        area_1_m2,
        area_2_m2,
    )

    return (
            DISCHARGE_COEFFICIENT
            * area_wind
            * reference_wind_speed_m_s
            * sqrt(delta_cp)
    )


def _stack_velocity_m_s(
        centre_height_difference_m: float,
        indoor_temp_c: float,
        outdoor_temp_c: float,
) -> float:
    if not all(
            isfinite(v)
            for v in (
                    centre_height_difference_m,
                    indoor_temp_c,
                    outdoor_temp_c,
            )
    ):
        raise ValueError("Buoyancy inputs must be finite.")

    if centre_height_difference_m < 0:
        raise ValueError(
            "Centre height difference cannot be negative."
        )

    if min(indoor_temp_c, outdoor_temp_c) <= -PAPER_KELVIN_OFFSET:
        raise ValueError(
            "Temperatures must be above absolute zero "
            "using the paper's offset."
        )

    mean_temperature_k = (
            (indoor_temp_c + outdoor_temp_c) / 2.0
            + PAPER_KELVIN_OFFSET
    )

    return sqrt(
        GRAVITY_M_S2
        * centre_height_difference_m
        * abs(indoor_temp_c - outdoor_temp_c)
        / mean_temperature_k
    )


def cross_buoyancy_flow_m3_s(
    area_1_m2: float,
    area_2_m2: float,
    centre_height_difference_m: float,
    indoor_temp_c: float,
    outdoor_temp_c: float,
) -> float:
    """Equations 6-7 as printed, using temperature-difference magnitude."""
    velocity = _stack_velocity_m_s(
        centre_height_difference_m, indoor_temp_c, outdoor_temp_c
    )
    _, area_buoyancy = equivalent_areas_m2(area_1_m2, area_2_m2)
    return DISCHARGE_COEFFICIENT * area_buoyancy * velocity


def single_sided_two_opening_flow_m3_s(
    lower_area_m2: float,
    upper_area_m2: float,
    centre_height_difference_m: float,
    indoor_temp_c: float,
    outdoor_temp_c: float,
) -> float:
    """Same-façade buoyancy from SheltAir equation 3 as printed."""
    velocity = _stack_velocity_m_s(
        centre_height_difference_m, indoor_temp_c, outdoor_temp_c
    )
    if not all(isfinite(area) and area >= 0 for area in (lower_area_m2, upper_area_m2)):
        raise ValueError("Opening areas must be finite and non-negative.")
    if lower_area_m2 == 0 or upper_area_m2 == 0:
        return 0.0

    # After cancelling (1 + epsilon), the area term is A1 / (1 + epsilon²).
    area_ratio = upper_area_m2 / hypot(lower_area_m2, upper_area_m2)
    effective_area = lower_area_m2 * area_ratio**2
    return DISCHARGE_COEFFICIENT * effective_area * sqrt(2.0) * velocity


class SheltAirTwoOpeningModel:
    """One pair of openings with independent state for each thermal run.

    The calculate() signature and common sa_* diagnostics match the existing
    single-opening model, allowing the same thermal and reporting connection.
    """

    def __init__(
            self,
            settings: SheltAirCrossVentilation | SheltAirSingleSidedTwoOpenings,
            windows: tuple[WindowGeometry, ...] = (),
    ):
        self.settings = settings
        self._is_open = False

        if isinstance(settings, SheltAirSingleSidedTwoOpenings):
            return

        lookup = {
            w.window_id: w
            for w in windows
        }

        if len(lookup) != len(windows):
            raise ValueError(
                "The window catalogue contains duplicate IDs."
            )

        for window_id, area in zip(
                settings.window_ids,
                settings.max_free_areas_m2,
        ):
            if window_id not in lookup:
                raise ValueError(
                    f"Unknown window ID: {window_id}. "
                    f"Available IDs: {sorted(lookup)}"
                )

            window = lookup[window_id]

            if not all(
                    isfinite(v) and v > 0
                    for v in (window.width_m, window.height_m)
            ):
                raise ValueError(
                    "Window dimensions must be positive and finite: "
                    f"{window_id}"
                )

            if area > window.width_m * window.height_m + 1e-9:
                raise ValueError(
                    "Free opening area exceeds nominal window area: "
                    f"{window_id}"
                )

        first, second = (
            lookup[wid]
            for wid in settings.window_ids
        )

        if first.compass_point == second.compass_point:
            raise ValueError(
                "Select openings on different facades "
                "for cross-ventilation."
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

        settings = self.settings

        if not all(
                isfinite(v)
                for v in (
                        outdoor_temp_c,
                        weather_wind_speed_m_s,
                        hour_midpoint,
                )
        ):
            raise ValueError(
                "Weather and time inputs must be finite."
            )

        if (
                outdoor_temp_c <= -PAPER_KELVIN_OFFSET
                or weather_wind_speed_m_s < 0
        ):
            raise ValueError(
                "Outdoor temperature or wind speed "
                "is outside its physical range."
            )

        if not 1 <= month <= 12 or not 0 <= hour_midpoint < 24:
            raise ValueError(
                "Expected month 1-12 and hour midpoint in [0, 24)."
            )

        if isinstance(settings, SheltAirCrossVentilation):
            reference_wind = weather_wind_speed_m_s * settings.reference_wind_factor
            if not isfinite(reference_wind):
                raise ValueError("Calculated reference wind speed is not finite.")
            result = {
                "sa_opening_fraction": 0.0,
                "sa_cross_area_1_m2": 0.0,
                "sa_cross_area_2_m2": 0.0,
                "sa_cross_wind_area_m2": 0.0,
                "sa_cross_buoyancy_area_m2": 0.0,
                "sa_reference_wind_m_s": reference_wind,
                "sa_wind_candidate_m3_h": 0.0,
                "sa_buoyancy_candidate_m3_h": 0.0,
                "sa_applied_m3_h": 0.0,
                "sa_ach": 0.0,
            }
        else:
            result = empty_sheltair_details()
            result.update(sa_lower_open_area_m2=0.0, sa_upper_open_area_m2=0.0)

        # No previous indoor temperature means closed.
        if indoor_temp_c is None:
            self._is_open = False
            return result

        if (
                not isfinite(indoor_temp_c)
                or indoor_temp_c <= -PAPER_KELVIN_OFFSET
        ):
            raise ValueError(
                "Indoor temperature must be finite "
                "and above absolute zero."
            )

        if settings.open_from_hour < settings.open_until_hour:
            permitted_time = (
                    settings.open_from_hour
                    <= hour_midpoint
                    < settings.open_until_hour
            )
        else:
            # Supports overnight schedules, e.g. 22:00 to 07:00.
            permitted_time = (
                    hour_midpoint >= settings.open_from_hour
                    or hour_midpoint < settings.open_until_hour
            )

        eligible = (
                month in settings.months
                and permitted_time
                and (
                        indoor_temp_c - outdoor_temp_c
                        >= settings.min_cooling_difference_c
                )
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

        area_1, area_2 = (
            a * settings.opening_fraction
            for a in settings.max_free_areas_m2
        )

        if isinstance(settings, SheltAirSingleSidedTwoOpenings):
            buoyancy_flow = 3600.0 * single_sided_two_opening_flow_m3_s(
                area_1, area_2, settings.centre_height_difference_m,
                indoor_temp_c, outdoor_temp_c,
            )
            result.update(
                sa_opening_fraction=settings.opening_fraction,
                sa_open_area_m2=area_1 + area_2,
                sa_lower_open_area_m2=area_1,
                sa_upper_open_area_m2=area_2,
                sa_buoyancy_candidate_m3_h=buoyancy_flow,
                sa_applied_m3_h=buoyancy_flow,
            )
            return result

        area_wind, area_buoyancy = equivalent_areas_m2(
            area_1,
            area_2,
        )

        wind_candidate = cross_wind_flow_m3_s(
            area_1,
            area_2,
            reference_wind,
            settings.delta_cp,
        )

        buoyancy_candidate = cross_buoyancy_flow_m3_s(
            area_1,
            area_2,
            settings.centre_height_difference_m,
            indoor_temp_c,
            outdoor_temp_c,
        )

        applied = (
            wind_candidate
            if settings.driving_force == "wind"
            else buoyancy_candidate
        )

        result.update(
            {
                "sa_opening_fraction": settings.opening_fraction,
                "sa_cross_area_1_m2": area_1,
                "sa_cross_area_2_m2": area_2,
                "sa_cross_wind_area_m2": area_wind,
                "sa_cross_buoyancy_area_m2": area_buoyancy,
                "sa_wind_candidate_m3_h": 3600.0 * wind_candidate,
                "sa_buoyancy_candidate_m3_h": (
                        3600.0 * buoyancy_candidate
                ),
                "sa_applied_m3_h": 3600.0 * applied,
            }
        )

        return result


SheltAirCrossVentilationModel = SheltAirTwoOpeningModel
