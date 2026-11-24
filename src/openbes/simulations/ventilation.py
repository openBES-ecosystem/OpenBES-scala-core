from collections.abc import Sequence
from math import copysign, isfinite, sqrt
from typing import List

from pandas import Series
from .. import logging
from pandas import DataFrame

from .base import EnergyUseSimulation, EnergyUseSimulationInitError, SimulationError
from .geometry import BuildingGeometry
from .occupancy import OccupationSimulation
from ..schemas import PassiveOpening, VentilationSimulationOutput, VentilationSystemResult
from ..types import OpenBESSpecification

logger = logging.getLogger(__name__)


def passive_stack_opening_factor(openings: Sequence[PassiveOpening]) -> float:
    """Return the stack exchange factor in m² × sqrt(m) for fixed openings.

    In a wind-free, well-mixed zone the temperature term is common to all
    openings. The neutral pressure height therefore only depends on the
    opening elevations and their discharge areas. Solve for it once per run.
    """
    discharge_areas = [
        (opening.centre_height_m, opening.discharge_coefficient * opening.free_area_m2)
        for opening in openings
        if opening.free_area_m2 > 0
    ]
    if len(discharge_areas) < 2:
        return 0.0

    lower = min(height for height, _ in discharge_areas)
    upper = max(height for height, _ in discharge_areas)
    if lower == upper:
        return 0.0

    for _ in range(48):
        neutral = lower + (upper - lower) / 2
        balance = sum(
            area * copysign(sqrt(abs(neutral - height)), neutral - height)
            for height, area in discharge_areas
        )
        if balance > 0:
            upper = neutral
        else:
            lower = neutral

    neutral = lower + (upper - lower) / 2
    # The flow above the neutral height balances this flow. Count it once.
    return sum(
        area * sqrt(neutral - height)
        for height, area in discharge_areas
        if height < neutral
    )


def passive_stack_airflow_m3_h(
    opening_factor: float, indoor_temp_c: float | None, outdoor_temp_c: float
) -> float:
    """Calculate the magnitude of outdoor air exchange from buoyancy."""
    if not opening_factor or indoor_temp_c is None:
        return 0.0

    if any(
        not isfinite(temp) or temp <= -273.15
        for temp in (indoor_temp_c, outdoor_temp_c)
    ):
        raise ValueError("Ventilation temperatures must be finite and above absolute zero.")

    mean_temp_k = (indoor_temp_c + outdoor_temp_c) / 2 + 273.15
    temperature_difference = abs(indoor_temp_c - outdoor_temp_c)
    return 3600 * opening_factor * sqrt(2 * 9.81 * temperature_difference / mean_temp_k)


class VentilationSimulationError(SimulationError):
    """Raised when ventilation report generation fails."""


class VentilationSystemSimulation(EnergyUseSimulation):
    """Simulate energy use for a single ventilation system based on building specifications and occupancy patterns."""
    system_number: int
    geometry: BuildingGeometry
    _air_supply_rate_adjusted: float

    def __init__(
        self,
        spec: OpenBESSpecification,
        system_number: int = 1,
        occupancy: OccupationSimulation = None,
        geometry: BuildingGeometry = None,
    ):
        super().__init__(spec=spec)
        self.system_number = system_number
        self.validate_required_inputs(
            required_inputs=[
                "energy_source",
                "airflow",
                "on_time",
                "off_time",
                "rated_input_power",
                "ventilated_area",
            ],
            getter=self._attr,
            context=f"Ventilation system {system_number}",
            error_cls=EnergyUseSimulationInitError,
        )
        try:
            self.geometry = geometry or BuildingGeometry(spec=self.spec)
            self.occupancy = occupancy or OccupationSimulation(spec=self.spec)
        except SimulationError as err:
            raise EnergyUseSimulationInitError(
                f"Failed to initialize VentilationSystemSimulation due to error in dependent simulation: {err}"
            ) from err

    def _attr(self, attr_name: str):
        return self.get_param_or_spec(
            f"ventilation_system{self.system_number}_{attr_name}"
        )

    @property
    def airflow(self) -> float:
        """Rated airflow (m3/h) of the ventilation system."""
        return self._attr("airflow")

    @property
    def air_supply_rate_adjusted(self) -> float:
        """Air supply rate (m3/h/m2) adjusted for system efficiency.
        [Hourly simulation cells IV99, JB99]
        """
        if (
            not hasattr(self, "_air_supply_rate_adjusted")
            or self._air_supply_rate_adjusted is None
        ):
            rated_flow_rate = self.airflow / self._attr("ventilated_area")  # m3/h/m2
            efficiency = self._attr("heat_recovery_efficiency")
            if rated_flow_rate is None or efficiency is None:
                self._air_supply_rate_adjusted = 0.0
            else:
                self._air_supply_rate_adjusted = rated_flow_rate * (1 - efficiency)
        return self._air_supply_rate_adjusted

    @property
    def ventilation_on(self) -> "Series[bool]":
        """Hourly ventilation status (on/off) throughout the year.
        [Hourly simulation columns IR, IX]

        Ventilation only runs between the specified on and off times,
        and only while the building is occupied.
        """
        if "ventilation_on" not in self._hours.columns:
            on_time = self._attr("on_time")
            off_time = self._attr("off_time")
            self._hours["ventilation_on"] = list(
                map(
                    lambda x: on_time <= x <= off_time,
                    self._hours.index.get_level_values("hour").values,
                )
            )
            self._hours["ventilation_on"] = (
                self._hours["ventilation_on"] * self.occupancy.occupied_days
            )
        return self._hours["ventilation_on"]

    @property
    def ventilated_area(self) -> float:
        """Area (m2) served by the ventilation system."""
        return self._attr("ventilated_area")

    @property
    def efficiency(self) -> float:
        """Heat recovery efficiency of the ventilation system."""
        return self._attr("heat_recovery_efficiency")

    @property
    def air_supply_rate(self) -> "Series[float]":
        """Hourly air supply rate (m3/h/m2) throughout the year.
        [Hourly simulation columns IV, JB]
        """
        if "air_supply_rate" not in self._hours.columns:
            area = self.geometry.conditioned_floor_area
            rated_flow_rate = self.air_supply_rate_adjusted * self._attr(
                "ventilated_area"
            )
            if rated_flow_rate is None or area == 0:
                self._hours["air_supply_rate"] = 0.0
            else:
                self._hours["air_supply_rate"] = (
                    rated_flow_rate / area
                ) * self.ventilation_on.astype(float)
        return self._hours["air_supply_rate"]

    @property
    def energy_use(self) -> DataFrame:
        """Ventilation energy use in kWh for each hour of the year for each ENERGY_SOURCE."""
        if self._energy_use[self._attr("energy_source")].hasnans:
            self._energy_use[self._attr("energy_source")] = self.ventilation_on.astype(
                float
            ) * self._attr("rated_input_power")
        return self._energy_use


class VentilationSimulation(EnergyUseSimulation):
    """Aggregate simulation of all ventilation systems in the building, summing their energy use and air supply rates."""
    ventilation_simulations: List[VentilationSystemSimulation]

    def __init__(
        self,
        spec: OpenBESSpecification,
        occupancy: OccupationSimulation = None,
        geometry: BuildingGeometry = None,
    ):
        super().__init__(spec=spec)
        try:
            self.geometry = geometry or BuildingGeometry(spec=self.spec)
            self.occupancy = occupancy or OccupationSimulation(
                spec=self.spec, geometry=self.geometry
            )
        except SimulationError as err:
            raise EnergyUseSimulationInitError(
                f"Failed to initialize VentilationSimulation due to error in dependent simulation: {err}"
            ) from err
        self.ventilation_simulations = []
        while True:
            system_number = len(self.ventilation_simulations) + 1
            try:
                self.ventilation_simulations.append(
                    VentilationSystemSimulation(
                        spec=spec,
                        system_number=system_number,
                        occupancy=self.occupancy,
                        geometry=self.geometry,
                    )
                )
            except EnergyUseSimulationInitError:
                break

    @property
    def air_supply_rate(self) -> "Series[float]":
        """Total hourly air supply rate (m3/h/m2) from all ventilation systems.
        [Hourly simulation column JA]
        """
        if "air_supply_rate" not in self._hours.columns:
            total_air_supply = Series([0.0] * len(self._hours), index=self._hours.index)
            for sim in self.ventilation_simulations:
                total_air_supply += sim.air_supply_rate
            self._hours["air_supply_rate"] = total_air_supply
        return self._hours["air_supply_rate"]

    @property
    def energy_use(self) -> "Series[float]":
        """Ventilation energy use in kWh for each hour of the year for each ENERGY_SOURCES."""
        if len(self.ventilation_simulations) == 0:
            return self._energy_use.fillna(0.0)
        return sum([x.energy_use for x in self.ventilation_simulations])

    @property
    def report(self) -> VentilationSimulationOutput:
        try:
            systems = []
            for vs in self.ventilation_simulations:
                hourly_energy = vs.energy_use.sum(axis="columns")
                ach_hours = (vs.air_supply_rate != 0).sum()
                systems.append(
                    VentilationSystemResult(
                        energy_demand=vs.energy_use.sum().sum() / vs.ventilated_area,
                        peak_load=max(hourly_energy),
                        sfp=max(hourly_energy) / (vs.airflow / 3600),
                        mechanical_ventilation_rate=vs.airflow / vs.ventilated_area,
                        ventilation_rate=vs.airflow / vs.ventilated_area / 3.6,
                        ach=(
                            (vs.air_supply_rate / self.spec.floor_to_ceiling_height).sum()
                            / ach_hours
                            if ach_hours > 0
                            else None
                        ),
                    )
                )
            return VentilationSimulationOutput(ventilation_systems=systems)
        except Exception as exc:
            raise VentilationSimulationError(
                "Failed to generate ventilation report"
            ) from exc
