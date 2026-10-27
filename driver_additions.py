"""Helpers for the existing intervention comparison driver.

Keep the existing Scenario import, window catalogue and shading scenarios.
"""

from dataclasses import replace

from openbes.interventions.sheltair_cross_ventilation import (
    SheltAirCrossVentilation,
)


def append_cross_ventilation_cases(
        scenarios,
        windows,
        scenario_class,
):
    """Append cross-ventilation examples to the existing scenario list.

    Example inputs must be reviewed for the building being modelled.

    Call from the existing driver:
        append_cross_ventilation_cases(
            scenarios,
            windows,
            Scenario,
        )
    """

    if not windows:
        raise ValueError("No windows were found.")

    first = windows[0]

    second = next(
        (
            w
            for w in windows
            if w.compass_point != first.compass_point
        ),
        None,
    )

    if second is None:
        raise ValueError(
            "Cross-ventilation needs a second window "
            "on another facade."
        )

    print(
        "Example cross-ventilation pair:",
        first.window_id,
        second.window_id,
    )

    # Confirm that these openings are linked by a usable
    # internal airflow path.
    #
    # Replace the example selection above with known window
    # IDs when selecting the actual pair for your building.

    wind = SheltAirCrossVentilation(
        window_ids=(
            first.window_id,
            second.window_id,
        ),

        # Illustrative free aperture areas, not measured data.
        max_free_areas_m2=(0.20, 0.20),

        # Same-height example: buoyancy flow will be ZERO.
        centre_height_difference_m=0.0,

        driving_force="wind",

        # Illustrative assumption, not Holywell data.
        reference_wind_factor=0.8,

        # Illustrative pressure-coefficient difference.
        # This is not a SheltAir default or measurement.
        delta_cp=0.5,

        opening_fraction=1.0,

        open_above_c=24.0,
        close_below_c=23.0,
        min_cooling_difference_c=1.0,

        open_from_hour=8.0,
        open_until_hour=22.0,

        months=(5, 6, 7, 8, 9),
    )

    # Enter a nonzero centre-height difference above only
    # when the selected apertures actually have one.
    buoyancy = replace(
        wind,
        driving_force="buoyancy",
    )

    closed = replace(
        wind,
        opening_fraction=0.0,
    )

    scenarios.extend(
        [
            scenario_class(
                name="SheltAir cross closed",
                interventions=(closed,),
            ),
            scenario_class(
                name="SheltAir cross wind",
                interventions=(wind,),
            ),
            scenario_class(
                name="SheltAir cross buoyancy",
                interventions=(buoyancy,),
            ),
        ]
    )


def save_cross_ventilation_results(
        comparison,
        output_dir,
):
    """Save results after the existing comparison.

    output_dir must be a pathlib.Path.
    """

    from numpy import allclose

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    names = [
        "Baseline",
        "SheltAir cross closed",
        "SheltAir cross wind",
        "SheltAir cross buoyancy",
    ]

    comparison.temperatures[names].to_csv(
        output_dir / "sheltair_cross_temperatures.csv"
    )

    comparison.temperature_differences[names[2:]].to_csv(
        output_dir / "sheltair_cross_temperature_differences.csv"
    )

    for name, filename in (
            (
                    "SheltAir cross wind",
                    "sheltair_cross_wind_airflow.csv",
            ),
            (
                    "SheltAir cross buoyancy",
                    "sheltair_cross_buoyancy_airflow.csv",
            ),
    ):
        details = comparison.sheltair_ventilation[name]

        details.to_csv(
            output_dir / filename
        )

        candidate = (
            "sa_wind_candidate_m3_h"
            if name.endswith("wind")
            else "sa_buoyancy_candidate_m3_h"
        )

        assert allclose(
            details["sa_applied_m3_h"],
            details[candidate],
            rtol=0.0,
            atol=1e-9,
        )

    assert allclose(
        comparison.temperatures["SheltAir cross closed"],
        comparison.temperatures["Baseline"],
        rtol=0.0,
        atol=1e-6,
    ), (
        "Closed-opening temperatures differ from the baseline: "
        "check the integration."
    )