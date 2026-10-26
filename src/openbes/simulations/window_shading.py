"""
HM WIP - Module to generate window IDs and calculate the hourly shading effects

"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .geometry import BuildingGeometry
from .solar_irradiation import SolarIrradiationSimulation
from ..interventions.window_overhang import ScheduledWindowShade
from ..types import COMPASS_POINTS, ORIENTATIONS, OpenBESSpecification


@dataclass(frozen=True)
class WindowGeometry:
    window_id: str
    compass_point: COMPASS_POINTS
    height_m: float
    width_m: float

    # Gross window area allocated by the existing geometry model.
    modelled_area_m2: float


def windows_from_geometry(
        spec: OpenBESSpecification,
        geometry: BuildingGeometry,
) -> tuple[WindowGeometry, ...]:
    """Generate nominal windows without changing existing window areas."""

    height = float(spec.window_height)
    width = float(spec.window_length)

    if (
            not np.isfinite([height, width]).all()
            or height <= 0
            or width <= 0
    ):
        raise ValueError("Positive window height and width are required.")

    side_names = {
        ORIENTATIONS.Up: "front",
        ORIENTATIONS.Right: "right",
        ORIENTATIONS.Down: "back",
        ORIENTATIONS.Left: "left",
    }

    windows = []

    for (floor, orientation), raw_count in geometry.window_count.items():
        if not raw_count:
            continue

        count = int(raw_count)
        if count != raw_count or count < 0:
            raise ValueError("Window counts must be non-negative integers.")

        point = geometry.get_compass_point_for_orientation(orientation)
        area = float(geometry.window_areas.loc[(floor, point)])

        # Only include windows contributing area to the thermal model.
        if count == 0 or area <= 0:
            continue

        for number in range(1, count + 1):
            windows.append(
                WindowGeometry(
                    window_id=(
                        f"{floor.name.lower()}_"
                        f"{side_names[orientation]}_"
                        f"{number:02d}"
                    ),
                    compass_point=point,
                    height_m=height,
                    width_m=width,
                    modelled_area_m2=area / count,
                )
            )

    # Check that generating IDs has preserved the original areas.
    original_totals = geometry.window_areas.groupby(
        "compass_point"
    ).sum()

    for point, original_area in original_totals.items():
        generated_area = sum(
            window.modelled_area_m2
            for window in windows
            if window.compass_point == point
        )

        if not np.isclose(
                generated_area, original_area, rtol=1e-8, atol=1e-8
        ):
            raise ValueError(
                f"Generated window area does not match {point}."
            )

    return tuple(windows)


def overhang_factors(
        height_m: float,
        projection_m: float,
        gap_m: float,
        altitude_deg: np.ndarray,
        relative_azimuth_deg: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Direct and approximate sky-diffuse factors for a wide overhang."""

    altitude = np.asarray(altitude_deg, dtype=float)
    relative_azimuth = np.asarray(relative_azimuth_deg, dtype=float)

    cos_relative = np.cos(np.radians(relative_azimuth))
    sun_in_front = (altitude > 0) & (cos_relative > 1e-9)

    shadow_drop = np.zeros_like(altitude)

    np.divide(
        projection_m
        * np.tan(np.radians(np.clip(altitude, 0.0, 89.999999))),
        cos_relative,
        out=shadow_drop,
        where=sun_in_front,
        )

    shaded_height = np.clip(
        shadow_drop - gap_m,
        0.0,
        height_m,
        )

    direct_factor = 1.0 - shaded_height / height_m

    # Relative visible sky for an isotropic sky and an infinitely
    # wide horizontal projection, averaged over the window height.
    sky_factor = (
                         np.hypot(height_m + gap_m, projection_m)
                         - np.hypot(gap_m, projection_m)
                 ) / height_m

    diffuse_factor = np.full_like(
        altitude,
        np.clip(sky_factor, 0.0, 1.0),
    )

    return direct_factor, diffuse_factor


def _glazing_components(spec, solar, point):
    """Reproduce the component weighting used by OpenBES glazing."""

    aoi_deg = np.asarray(solar.get_aoi_degrees(point), dtype=float)
    aoi = np.radians(aoi_deg)

    polynomial = np.zeros_like(aoi)
    for power in range(5):
        coefficient = getattr(
            spec.parameters, f"window_optical_c{power + 1}"
        )
        polynomial += coefficient * aoi**power

    g_value = spec.window_gvalue
    hemispheric = 0.92 if g_value >= 0.8 else 0.8

    beam = (
            np.where(aoi_deg > 90, 0.0, g_value * polynomial)
            * np.asarray(solar.get_beam_component(point))
    )

    sky = (
            g_value
            * hemispheric
            * np.asarray(solar.get_diffuse_component(point))
    )

    ground = (
            g_value
            * hemispheric
            * np.asarray(solar.ground_reflected_component)
    )

    return beam, sky, ground


def calculate_window_shading(
        spec: OpenBESSpecification,
        geometry: BuildingGeometry,
        solar: SolarIrradiationSimulation,
        shades: tuple[ScheduledWindowShade, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return direction-level transmission factors and optional details."""

    windows = windows_from_geometry(spec, geometry)
    if not windows:
        raise ValueError("No modelled windows were found.")

    by_id = {window.window_id: window for window in windows}
    assigned = {}

    for shade in shades:
        targets = (
            set(by_id)
            if shade.window_ids is None
            else set(shade.window_ids)
        )

        unknown = targets - set(by_id)
        if unknown:
            raise ValueError(f"Unknown window IDs: {sorted(unknown)}")

        for window_id in targets:
            if window_id in assigned:
                raise ValueError(
                    f"More than one device assigned to {window_id}."
                )

            window = by_id[window_id]

            if (
                    shade.mode == "top_hung_shutter"
                    and shade.projection_m
                    < window.height_m + shade.gap_m
            ):
                raise ValueError(
                    f"The shutter panel for {window_id} must be long "
                    "enough to cover the window when closed."
                )

            assigned[window_id] = shade

    index = solar.solar_altitude.index
    altitude = np.asarray(solar.solar_altitude)
    azimuth = np.asarray(solar.solar_azimuth)

    totals = geometry.window_areas.groupby("compass_point").sum()

    factors = pd.DataFrame(
        1.0,
        index=index,
        columns=list(COMPASS_POINTS),
    )

    for point, area in totals.items():
        if area > 0:
            factors[point] = 0.0

    components = {
        point: _glazing_components(spec, solar, point)
        for point in {window.compass_point for window in windows}
    }

    diagnostics = {}

    for window in windows:
        point = window.compass_point
        shade = assigned.get(window.window_id)

        closed = np.zeros(len(index), dtype=bool)
        direct = np.ones(len(index))
        sky = np.ones(len(index))
        ground = np.ones(len(index))

        if shade is not None:
            closed = shade.closed_schedule.closed_mask(index)

            overhang_direct, overhang_sky = overhang_factors(
                height_m=window.height_m,
                projection_m=shade.projection_m,
                gap_m=shade.gap_m,
                altitude_deg=altitude,
                relative_azimuth_deg=(
                        azimuth - solar.surface_azimuths[point]
                ),
            )

            if shade.mode == "retractable_overhang":
                direct = np.where(closed, overhang_direct, 1.0)
                sky = np.where(closed, overhang_sky, 1.0)

            else:
                transmission = shade.closed_transmittance

                direct = np.where(
                    closed, transmission, overhang_direct
                )
                sky = np.where(
                    closed, transmission, overhang_sky
                )
                ground = np.where(closed, transmission, 1.0)

        beam_gain, sky_gain, ground_gain = components[point]

        unshaded = beam_gain + sky_gain + ground_gain
        shaded = (
                beam_gain * direct
                + sky_gain * sky
                + ground_gain * ground
        )

        effective_factor = np.ones(len(index))
        np.divide(
            shaded,
            unshaded,
            out=effective_factor,
            where=unshaded > 0,
        )
        effective_factor = np.clip(effective_factor, 0.0, 1.0)

        area_weight = window.modelled_area_m2 / totals[point]
        factors[point] += area_weight * effective_factor

        if shade is not None and shade.record_details:
            window_id = window.window_id

            diagnostics[(window_id, "closed")] = closed
            diagnostics[(window_id, "direct_factor")] = direct
            diagnostics[(window_id, "sky_factor")] = sky
            diagnostics[(window_id, "effective_factor")] = (
                effective_factor
            )

            glass_area = window.modelled_area_m2 * (
                    1.0 - spec.window_frame_factor
            )
            diagnostics[
                (window_id, "incoming_before_legacy_W")
            ] = glass_area * shaded

    details = pd.DataFrame(diagnostics, index=index)

    if diagnostics:
        details.columns = pd.MultiIndex.from_tuples(
            list(diagnostics),
            names=["window_id", "quantity"],
        )

    return factors.clip(0.0, 1.0), details