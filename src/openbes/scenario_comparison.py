"""
08/10/2026 - HM WIP

Writing the cooling strategies wrapper
The aim is to output the results of each cooling strategy and compare to the original input

_run_scenario function copies the original inputs, applies the interventions and creatures a new thermal simulation
and returns the new temperatures

compare_interventions function runs the baseline once, runs the requested scenarios and assembles the comparisons

The wrapper returns 2x tables (1) temperatures = the baseline and intervention temperatures aligned by hour.
(2) temperature_differences = each intervention temperature minus the baseline temperature
"""
from copy import deepcopy
from dataclasses import dataclass
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

def _run_scenario(
        original_spec : OpenBESSpecification,
        scenario: Scenario,
) -> pd.Series:
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
    )

    # Collect the existing free-running temperature output
    return thermal.air_free_temp.copy().rename(scenario.name)

def compare_interventions(
        original_spec : OpenBESSpecification,
        scenarios: Sequence[Scenario],

)-> ComparisonResult:
    names = [scenario.name for scenario in scenarios]

    if "Baseline" in names or len(names) != len(set(names)):
        raise ValueError(
            "Scenario names must be unique; 'Baseline' is reserved for baseline"
        )
    # Run the original building once, without added interventions
    baseline = _run_scenario(
        original_spec,
        Scenario(name = "Baseline"),
    )

    results = {"Baseline": baseline}

    # Run each requested scenario independently
    for scenario in scenarios:
        results[scenario.name] = _run_scenario(
            original_spec,
            scenario,
        )

    # Each column contains one scenario's hourly temperatures
    temperatures = pd.DataFrame(results)

    # Subtract baseline temperature at the corresponding hour
    differences = (
        temperatures.drop(columns="Baseline")
        .subtract(temperatures["Baseline"], axis = "index")
    )

    return ComparisonResult(
        temperatures = temperatures,
        temperature_differences = differences,
    )