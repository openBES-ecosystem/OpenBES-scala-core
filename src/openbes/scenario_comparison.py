"""
08/10/2026 - HM WIP

Cooling strategies wrapper

The aim is to output the results of each cooling strategy and compare to the original input

_run_scenario function copies the original inputs, applies the interventions and creatures a new thermal simulation
and returns the new temperatures

compare_interventions function runs the baseline once, runs the requested scenarios and assembles the comparisons

The wrapper returns 2x tables (1) temperatures = the baseline and intervention temperatures aligned by hour.
(2) temperature_differences = each intervention temperature minus the baseline temperature
"""
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Sequence

import pandas as pd

from openbes.interventions.base import Intervention, ScenarioInputs
from openbes.simulations.thermal import ThermalSimulation
from openbes.types import OpenBESSpecification

@dataclass(frozen=True)
class Scenario:
    name: str
    interventions: tuple[Intervention, ...] = ()

@dataclass
class ComparisonResult:
    temperatures: pd.DataFrame
    temperature_differences: pd.DataFrame

    window_shading: dict[str, pd.DataFrame] = field(
        default_factory = dict
    )

def _run_scenario(
        original_spec : OpenBESSpecification,
        scenario: Scenario,
) -> tuple[pd.Series, pd.DataFrame]:
    # Create inputs belonging only to this scenario
    inputs = ScenarioInputs(
        spec = deepcopy(original_spec),
    )

    # Let each intervention configure those inputs
    for intervention in scenario.interventions:
        intervention.apply(inputs)

    # Creating the thermal model runs its hourly calculation
    thermal = ThermalSimulation(
        spec = inputs.spec,
        roof_solar_factor = inputs.roof_solar_factor,
        wall_solar_factor = inputs.wall_solar_factor,
        wall_solar_factors=inputs.wall_solar_factors,
        window_shades= tuple(inputs.window_shades),
    )

    # Collect the existing free-running temperature output
    return (
        thermal.air_free_temp.copy().rename(scenario.name),
        thermal.window_shading_details,
    )

def compare_interventions(
        original_spec: OpenBESSpecification,
        scenarios: Sequence[Scenario],
) -> ComparisonResult:
    scenarios = tuple(scenarios)
    names = [scenario.name for scenario in scenarios]

    if "Baseline" in names:
        raise ValueError("Baseline is added automatically.")

    if len(names) != len(set(names)):
        raise ValueError("Scenario names must be unique.")

    baseline, _ = _run_scenario(
        original_spec,
        Scenario(name="Baseline"),
    )

    results = {"Baseline": baseline}
    shading_results = {}

    for scenario in scenarios:
        temperature, shading = _run_scenario(
            original_spec,
            scenario,
        )

        results[scenario.name] = temperature
        shading_results[scenario.name] = shading

    temperatures = pd.DataFrame(results)

    differences = temperatures.drop(
        columns="Baseline"
    ).subtract(
        temperatures["Baseline"],
        axis="index",
    )

    return ComparisonResult(
        temperatures=temperatures,
        temperature_differences=differences,
        window_shading=shading_results,
    )