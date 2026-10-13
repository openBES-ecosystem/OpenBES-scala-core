"""
08/10/2026 HM WIP

Driver script to run the comparison wrapper - testing new wrapper and basic roof shading cooling strategy

Code is from Chatgpt

"""
# Path lets us locate files relative to this script.
from pathlib import Path

# Pandas provides tables and reads the stored reference CSV.
import pandas as pd

# This helper loads the supplied Holywell House specification.
from openbes.examples import get_holywell_house_spec

# This class describes the fixed roof-shading intervention.
from openbes.interventions.roof_shading import FixedRoofShade

# These are the scenario definition and comparison wrapper.
from openbes.scenario_comparison import Scenario, compare_interventions

from openbes.simulations.geometry import BuildingGeometry
from openbes.types import ORIENTATIONS

from openbes.interventions.wall_shading import FixedWallShade


# Find the folder containing this driver script.
PROJECT_ROOT = Path(__file__).resolve().parent


# Define the function that organises our comparison.
def main():

    # Load the original Holywell House inputs.
    spec = get_holywell_house_spec()

    geometry = BuildingGeometry(spec)

    wall_directions = {
        orientation: geometry.get_compass_point_for_orientation(orientation)
        for orientation in ORIENTATIONS
    }
    print("\nBuilding-side directions:")
    for orientation, direction in wall_directions.items():
        print(f"{orientation.value}: {direction.value}")

    front_direction = wall_directions[ORIENTATIONS.Up]
    right_direction = wall_directions[ORIENTATIONS.Right]

    # Describe the intervention cases we want to compare.
    # For an initial baseline-only run, replace this list with:
    #scenarios = []

    scenarios = [
        Scenario(
            name="Neutral shading",
            interventions=(
                FixedRoofShade(solar_factor=1.0),
                FixedWallShade(
                    solar_factor=1.0,
                    compass_points=(front_direction,),
                ),
            ),
        ),
        Scenario(
            name="Roof shading only",
            interventions=(
                FixedRoofShade(solar_factor=0.5),
            ),
        ),
        # Testing shading of two different walls using different solar factors
        Scenario(
            name="Front and right wall shading",
            interventions=(
                FixedWallShade(
                    solar_factor=0.5,
                    compass_points=(front_direction,),
                ),
                FixedWallShade(
                    solar_factor = 0.7,
                    compass_points=(right_direction,),
                ),
            ),
        ),
        Scenario(
            name="Roof and front and right wall shading",
            interventions=(
                FixedRoofShade(solar_factor=0.5),
                FixedWallShade(
                    solar_factor=0.5,
                    compass_points=(front_direction,),
                ),
            ),
        ),
    ]

    # Run the baseline and requested scenarios
    comparison = compare_interventions(
        original_spec = spec,
        scenarios = scenarios,
    )

    # Retrieve the table of hourly temperatures.
    temperatures = comparison.temperatures

    # Retrieve each intervention's hourly difference from baseline.
    differences = comparison.temperature_differences

    # Extract the baseline column as a single temperature series.
    baseline = temperatures["Baseline"]

    # Display the number of hours and a preview of the results.
    print("\nNumber of simulated hours:", len(baseline))
    print("\nFirst 12 hours: indoor temperatures (°C)")
    print(temperatures.head(12).round(3))

    # Locate the repository's stored Holywell temperature reference.
    reference_path = (
            PROJECT_ROOT
            / "tests"
            / "unit"
            / "fixtures"
            / "hh_air_free_temp.csv"
    )

    # Read the reference temperature column.
    reference = pd.read_csv(reference_path)["air_free_temp"]

    # Replace the simulation's time index with a simple row index.
    calculated = baseline.reset_index(drop=True)

    # Check that both series contain the same number of values.
    if len(calculated) != len(reference):
        raise ValueError(
            "Baseline and reference have different lengths."
        )

    # Compare the values after rounding to six decimal places.
    matches_reference = calculated.round(6).equals(
        reference.round(6)
    )

    # Report whether the baseline reproduces the stored reference.
    print("\nBaseline matches stored reference:", matches_reference)

    # Calculate and display the largest absolute reference difference.
    reference_difference = (calculated - reference).abs().max()
    print("Largest reference difference (°C):", reference_difference)

    # Display intervention differences if intervention runs exist.
    if not differences.empty:
        print("\nLargest absolute hourly difference from baseline (°C)")
        print(differences.abs().max())

    # Check the neutral roof intervention, if it was requested.
    if "Roof factor 1.0" in temperatures.columns:
        neutral_matches = baseline.equals(
            temperatures["Roof factor 1.0"]
        )
        print("\nRoof factor 1.0 matches baseline:", neutral_matches)

    # Create one summary row for each scenario.
    summary = pd.DataFrame({
        "Maximum temperature (°C)": temperatures.max(),
        "Hours above 26°C": temperatures.gt(26.0).sum(),
    })

    # Display the summary with temperatures rounded for readability.
    print("\nTemperature summary")
    print(summary.round(3))

    # Choose a folder for saving the results.
    output_dir = PROJECT_ROOT / "outputs"

    # Create that folder if it does not already exist.
    output_dir.mkdir(exist_ok=True)

    # Save the hourly temperatures.
    temperatures.to_csv(
        output_dir / "holywell_temperatures.csv"
    )

    # Save the hourly temperature differences.
    differences.to_csv(
        output_dir / "holywell_temperature_differences.csv"
    )

    # Save the scenario summary.
    summary.to_csv(
        output_dir / "holywell_temperature_summary.csv"
    )

    # Show where the files were saved.
    print("\nResults saved in:", output_dir)


# Run main() when this file is launched directly.
if __name__ == "__main__":
    main()