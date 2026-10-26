from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .base import ScenarioInputs


@dataclass(frozen=True)
class DailyClosedSchedule:
    """Daily periods during which the device is closed."""

    intervals: tuple[tuple[float, float], ...] = ((10.0, 18.0),)
    months: tuple[int, ...] = tuple(range(1, 13))

    def __post_init__(self):
        for start, end in self.intervals:
            valid = (
                    isfinite(start)
                    and isfinite(end)
                    and 0 <= start < 24
                    and 0 <= end <= 24
                    and start != end
            )
            if not valid:
                raise ValueError(
                    "Use different start/end times between 0 and 24."
                )

        if any(
                not isinstance(month, int) or not 1 <= month <= 12
                for month in self.months
        ):
            raise ValueError("Months must be integers from 1 to 12.")

    def closed_mask(self, index: pd.Index) -> np.ndarray:
        # OpenBES labels hourly periods 1–24.
        # Evaluate the schedule at each period's midpoint.
        time = np.asarray(
            index.get_level_values("hour"), dtype=float
        ) - 0.5

        month = np.asarray(index.get_level_values("month"))
        closed = np.zeros(len(index), dtype=bool)

        for start, end in self.intervals:
            if start < end:
                closed |= (time >= start) & (time < end)
            else:
                # An interval such as 22:00–07:00 crosses midnight.
                closed |= (time >= start) | (time < end)

        return closed & np.isin(month, self.months)


@dataclass(frozen=True)
class ScheduledWindowShade:
    projection_m: float
    gap_m: float = 0.0

    closed_schedule: DailyClosedSchedule = field(
        default_factory=DailyClosedSchedule
    )

    # None selects every modelled window.
    window_ids: tuple[str, ...] | None = None

    mode: Literal[
        "retractable_overhang",
        "top_hung_shutter",
    ] = "retractable_overhang"

    # Fraction reaching the glass through a closed shutter.
    closed_transmittance: float = 0.0

    # True replaces the existing summer/winter multipliers
    # with 1.0 on this scenario's private specification copy.
    replace_seasonal_factors: bool = False

    record_details: bool = False

    def __post_init__(self):
        if not isfinite(self.projection_m) or self.projection_m < 0:
            raise ValueError("projection_m must be finite and >= 0.")

        if not isfinite(self.gap_m) or self.gap_m < 0:
            raise ValueError("gap_m must be finite and >= 0.")

        if self.mode not in (
                "retractable_overhang",
                "top_hung_shutter",
        ):
            raise ValueError("Unknown window shade mode.")

        if not 0 <= self.closed_transmittance <= 1:
            raise ValueError(
                "closed_transmittance must be between 0 and 1."
            )

        if self.window_ids is not None and not self.window_ids:
            raise ValueError(
                "Use None for every window, or supply window IDs."
            )

    def apply(self, inputs: ScenarioInputs) -> None:
        inputs.window_shades.append(self)

        if self.replace_seasonal_factors:
            inputs.spec.solar_external_shading_summer = 1.0
            inputs.spec.solar_external_shading_winter = 1.0