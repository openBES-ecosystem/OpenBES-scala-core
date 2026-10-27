"""
08/10/2026 HM WIP

Driver script to run the comparison wrapper - testing new wrapper and basic roof shading cooling strategy

Testing dynamic window shading

# Connecting driver additions to include new cross-ventilation model

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

#from openbes.simulations.geometry import BuildingGeometry
from openbes.types import ORIENTATIONS

from openbes.interventions.wall_shading import FixedWallShade

from openbes.interventions.window_overhang import (
    DailyClosedSchedule,
    ScheduledWindowShade,
)
from openbes.simulations.geometry import BuildingGeometry
from openbes.simulations.window_shading import windows_from_geometry
from dataclasses import replace
from openbes.interventions.sheltair_ventilation import (
    SheltAirSingleOpening,
)

# Connecting driver additions:
from pathlib import Path

from driver_additions import (
    append_cross_ventilation_cases,
    save_cross_ventilation_results,
)


# Find the folder containing this driver script.
PROJECT_ROOT = Path(__file__).resolve().parent


# Define the function that organises our comparison.
def main():

    # Load the original Holywell House inputs.
    spec = get_holywell_house_spec()

    geometry = BuildingGeometry(spec=spec)
    windows = windows_from_geometry(spec, geometry)

    #HM WIP - Single sided ventilation using equations from SheltAir
    if not windows:
        raise ValueError("No modelled windows were found.")

    # Start with one window from the existing catalogue.
    selected_window = windows[0]

    """
    Replace selected_window = windows[0] with below code to select specific window using window ID
    
    selected_window = next(
        window
        for window in windows
        if window.window_id == "your_selected_window_id"
)"""

    print(
        "Selected ventilation window:",
        selected_window.window_id,
        selected_window.compass_point,
    )

    wind_opening = SheltAirSingleOpening(
        window_id=selected_window.window_id,

        # Illustrative aperture assumption; replace with your geometry.
        max_free_area_m2=0.20,

        # Assumes an aperture extending over the full window height.
        opening_height_m=selected_window.height_m,

        driving_force="wind",

        # Illustrative assumption, NOT measured Holywell data.
        local_wind_factor=0.8,

        opening_fraction=1.0,

        open_above_c=24.0,
        close_below_c=23.0,
        min_cooling_difference_c=1.0,

        open_from_hour=8.0,
        open_until_hour=22.0,
        months=(5, 6, 7, 8, 9),
    )

    # Identical geometry and control settings, different driving force.
    buoyancy_opening = replace(
        wind_opening,
        driving_force="buoyancy",
    )

    # A neutral integration check.
    closed_opening = replace(
        wind_opening,
        opening_fraction=0.0,
    )


    scenarios = [
        Scenario(
            name="SheltAir closed",
            interventions=(closed_opening,),
        ),

        Scenario(
            name="SheltAir wind",
            interventions=(wind_opening,),
        ),

        Scenario(
            name="SheltAir buoyancy",
            interventions=(buoyancy_opening,),
         ),
]
    # Cross-ventilation connection:
    append_cross_ventilation_cases(
        scenarios,
        windows,
        Scenario,
    )

    for window in windows:
        print(
             window.window_id,
             window.compass_point,
             window.modelled_area_m2,
        )

    # Defining a window shade closing schedule
    closed_schedule = DailyClosedSchedule(
        intervals=((10.0, 18.0),),
        months=(5, 6, 7, 8, 9),
    )

    # Defining window shading devices
    neutral_overhang = ScheduledWindowShade(
        projection_m=0.0,
        gap_m=0.0,
        closed_schedule=closed_schedule,
        replace_seasonal_factors = True,
    )

    all_window_overhangs = ScheduledWindowShade(
        projection_m=0.6,
        gap_m=0.2,
        closed_schedule=closed_schedule,
        window_ids=None,
        mode="retractable_overhang",
        replace_seasonal_factors= True,
        record_details=True,
    )

    selected_window_overhang = ScheduledWindowShade(
        projection_m=0.6,
        gap_m=0.2,
        closed_schedule=closed_schedule,
        window_ids=(windows[0].window_id,),
        mode="retractable_overhang",
        record_details=True,
    )

    #geometry = BuildingGeometry(spec)

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

    scenarios.extend ([
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
        Scenario(
            name="Neutral overhang",
            interventions=(neutral_overhang,),
        ),
        Scenario(
            name="Scheduled overhangs",
            interventions=(all_window_overhangs,),
        ),
        Scenario(
            name="Selected window overhang",
            interventions=(selected_window_overhang,),
        ),

])

    # Run the baseline and requested scenarios
    comparison = compare_interventions(
        original_spec = spec,
        scenarios = scenarios,
    )

    # Cross-ventilation connection
    output_dir = (
            Path(__file__).resolve().parent
            / "outputs"
    )

    save_cross_ventilation_results(
        comparison,
        output_dir,
    )

    # Retrieve the table of hourly temperatures.
    temperatures = comparison.temperatures

    # Retrieve each intervention's hourly difference from baseline.
    differences = comparison.temperature_differences

    #HM WIP; single sided ventilation using sheltair equations
    output_dir = Path(__file__).resolve().parent / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    selected_cases = [
        "Baseline",
        "SheltAir closed",
        "SheltAir wind",
        "SheltAir buoyancy",
    ]

    temperatures[selected_cases].to_csv(
        output_dir / "holywell_sheltair_temperatures.csv"
    )

    differences[
        ["SheltAir wind", "SheltAir buoyancy"]
    ].to_csv(
         output_dir / "holywell_sheltair_temperature_differences.csv"
    )

    comparison.sheltair_ventilation["SheltAir wind"].to_csv(
     output_dir / "sheltair_wind_airflow.csv"
    )

    comparison.sheltair_ventilation["SheltAir buoyancy"].to_csv(
     output_dir / "sheltair_buoyancy_airflow.csv"
    )

    closed_matches = (
        temperatures["SheltAir closed"].round(6).equals(
            temperatures["Baseline"].round(6)
        )
    )

    print("Closed-opening control matches baseline:", closed_matches)

    for name in ("SheltAir wind", "SheltAir buoyancy"):
        details = comparison.sheltair_ventilation[name]

        open_hours = int(
            (details["sa_opening_fraction"] > 0).sum()
        )

        print(name, "- hours with opening enabled:", open_hours)

    # Extract the baseline column as a single temperature series.
    baseline = temperatures["Baseline"]

    overhang_effect = (
            temperatures["Scheduled overhangs"]
            - temperatures["Neutral overhang"]
    )

    print(temperatures.head())
    print("Largest temperature reduction:", overhang_effect.min())

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

    overhang_effect.rename(
        "Overhang temperature difference"
    ).to_csv(
        output_dir / "overhang_effect_vs_control.csv"
    )

    comparison.window_shading[
        "Scheduled overhangs"
    ].to_csv(
        output_dir / "overhang_window_details.csv"
    )

    # Show where the files were saved.
    print("\nResults saved in:", output_dir)


# Run main() when this file is launched directly.
if __name__ == "__main__":
    main()