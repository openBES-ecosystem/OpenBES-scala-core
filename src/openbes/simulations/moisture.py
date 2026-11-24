"""
HM WIP - trying to calculate initial indoor moisture conditions using PsychroLib functions
Hourly moisture balance for one well-mixed space with outdoor air exchange."""

from threading import Lock

import numpy as np
from pandas import DataFrame, Series


MAX_WARMUP_DAYS = 25
WARMUP_TOLERANCE = 1e-6  # kg water/kg dry air
_PSYCHROLIB_LOCK = Lock()


def _advance_humidity_ratio(outdoor, air_exchange_fraction, initial):
    """Return humidity ratio at the end of each hour."""
    indoor = np.empty_like(outdoor)
    ratio = initial
    for hour, (outdoor_ratio, fraction) in enumerate(
            zip(outdoor, air_exchange_fraction, strict=True)
    ):
        ratio += fraction * (outdoor_ratio - ratio)
        indoor[hour] = ratio
    return indoor


def calculate_indoor_moisture(
        weather: DataFrame,
        indoor_temperature: Series,
        outdoor_airflow: Series,
        indoor_air_volume: float,
) -> DataFrame:
    """Solve the ventilation-only balance using hourly weather and airflow.

    Airflow is in m³/h and volume in m³. The model uses constant air density
    and constant conditions within each hour. The warm-up repeats the first
    day's weather and airflow using the outdoor humidity ratio as its seed.
    """
    try:
        import psychrolib
    except ModuleNotFoundError as exc:
        raise ImportError(
            "Indoor moisture requires the OpenBES 'moisture' extra."
        ) from exc

    if weather.empty or len(weather) != len(indoor_temperature):
        raise ValueError(
            "Indoor moisture requires matching hourly weather and temperatures."
        )
    if not outdoor_airflow.index.equals(indoor_temperature.index):
        raise ValueError(
            "Outdoor airflow must use the same hours as indoor temperature."
        )
    if not np.isfinite(indoor_air_volume) or indoor_air_volume <= 0:
        raise ValueError("Indoor air volume must be positive and finite.")

    outdoor_temp = weather["temp_air"].to_numpy(dtype=float)
    outdoor_rh = weather["relative_humidity"].to_numpy(dtype=float)
    pressure = weather["atmospheric_pressure"].to_numpy(dtype=float)
    temperature = indoor_temperature.to_numpy(dtype=float)
    airflow = outdoor_airflow.to_numpy(dtype=float)
    if (
            not np.isfinite([outdoor_temp, outdoor_rh, pressure, temperature]).all()
            or np.any((outdoor_rh < 0) | (outdoor_rh > 100))
            or np.any((pressure <= 0) | (pressure == 999999))
            or np.any(outdoor_temp == 99.9)
    ):
        raise ValueError(
            "Indoor moisture requires valid EPW temperature, RH and pressure."
        )
    if not np.isfinite(airflow).all() or np.any(airflow < 0):
        raise ValueError("Outdoor airflow must be nonnegative and finite.")

    # Exact one-hour exchange fraction for the well-mixed volume.
    air_exchange_fraction = -np.expm1(-airflow / indoor_air_volume)

    # PsychroLib 2.5 also vectorizes GetUnitSystem when Numba is installed.
    # Read the module state directly because it can be None before the first run.
    with _PSYCHROLIB_LOCK:
        previous_units = psychrolib.PSYCHROLIB_UNITS
        if previous_units != psychrolib.SI:
            psychrolib.SetUnitSystem(psychrolib.SI)
        try:
            outdoor_ratio = np.array(
                [
                    psychrolib.GetHumRatioFromRelHum(temp, rh / 100, p)
                    for temp, rh, p in zip(
                    outdoor_temp, outdoor_rh, pressure, strict=True
                )
                ]
            )
            initial_ratio = float(outdoor_ratio[0])
            start_ratio = initial_ratio
            for warmup_days in range(1, MAX_WARMUP_DAYS + 1):
                end_ratio = _advance_humidity_ratio(
                    outdoor_ratio[:24], air_exchange_fraction[:24], start_ratio
                )[-1]
                warmup_converged = abs(end_ratio - start_ratio) <= WARMUP_TOLERANCE
                start_ratio = float(end_ratio)
                if warmup_converged:
                    break

            indoor_ratio = _advance_humidity_ratio(
                outdoor_ratio, air_exchange_fraction, start_ratio
            )
            indoor_rh = [
                100 * psychrolib.GetRelHumFromHumRatio(temp, ratio, p)
                for temp, ratio, p in zip(
                    temperature, indoor_ratio, pressure, strict=True
                )
            ]
        finally:
            if previous_units is not None and previous_units != psychrolib.SI:
                psychrolib.SetUnitSystem(previous_units)

    results = DataFrame(
        {
            "outdoor_humidity_ratio": outdoor_ratio,
            "indoor_humidity_ratio": indoor_ratio,
            "indoor_relative_humidity": indoor_rh,
        },
        index=indoor_temperature.index,
    )
    results.attrs.update(
        initial_humidity_ratio=initial_ratio,
        start_of_run_humidity_ratio=start_ratio,
        warmup_days=warmup_days,
        warmup_converged=bool(warmup_converged),
    )
    return results
