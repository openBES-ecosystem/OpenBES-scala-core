"""Run the baseline and intervention scenarios defined in a shelter JSON file."""

import faulthandler
import json
from argparse import ArgumentParser
from calendar import month_abbr
from collections.abc import Sequence
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pandas as pd
from numpy import allclose, flatnonzero

from openbes.interventions.base import Intervention
from openbes.interventions.roof_shading import FixedRoofShade
from openbes.interventions.sheltair_cross_ventilation import (
    SheltAirCrossVentilation,
    SheltAirSingleSidedTwoOpenings,
)
from openbes.interventions.sheltair_ventilation import SheltAirSingleOpening
from openbes.interventions.wall_shading import FixedWallShade
from openbes.interventions.window_overhang import (
    DailyClosedSchedule,
    ScheduledWindowShade,
)
from openbes.scenario_comparison import (
    ComparisonResult,
    Scenario,
    compare_interventions,
)
from openbes.schemas import json_to_toml
from openbes.types import COMPASS_POINTS, OpenBESSpecification


PROJECT_ROOT = Path(__file__).resolve().parent
INTERVENTION_TYPES = {
    "roof_shading": FixedRoofShade,
    "wall_shading": FixedWallShade,
    "window_overhang": ScheduledWindowShade,
    "single_opening_ventilation": SheltAirSingleOpening,
    "cross_ventilation": SheltAirCrossVentilation,
    "single_sided_two_opening_ventilation": SheltAirSingleSidedTwoOpenings,
}


def _load_intervention(config: dict[str, Any]) -> Intervention:
    if not isinstance(config, dict):
        raise TypeError("Each intervention must be a JSON object.")
    settings = config.copy()
    kind = settings.pop("type", None)
    if not isinstance(kind, str) or kind not in INTERVENTION_TYPES:
        choices = ", ".join(INTERVENTION_TYPES)
        raise ValueError(f"Unknown intervention type {kind!r}. Choose from {choices}.")

    if kind == "window_overhang" and "closed_schedule" in settings:
        schedule = settings["closed_schedule"]
        if not isinstance(schedule, dict):
            raise TypeError("closed_schedule must be a JSON object.")
        schedule = schedule.copy()
        if "intervals" in schedule:
            schedule["intervals"] = tuple(
                tuple(interval) for interval in schedule["intervals"]
            )
        if "months" in schedule:
            schedule["months"] = tuple(schedule["months"])
        settings["closed_schedule"] = DailyClosedSchedule(**schedule)

    if kind == "wall_shading" and settings.get("compass_points") is not None:
        settings["compass_points"] = tuple(
            COMPASS_POINTS.get_by_value(point) for point in settings["compass_points"]
        )

    for field in ("window_ids", "max_free_areas_m2", "months"):
        if settings.get(field) is not None:
            settings[field] = tuple(settings[field])

    return INTERVENTION_TYPES[kind](**settings)


def load_shelter_run(path: Path) -> tuple[OpenBESSpecification, list[Scenario]]:
    """Load a shelter with optional scenarios, or a plain OpenBES JSON spec."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("The shelter file must contain a JSON object.")

    if "specification" in data:
        extra_fields = data.keys() - {"specification", "scenarios"}
        if extra_fields:
            names = ", ".join(sorted(extra_fields))
            raise ValueError(f"Unknown shelter run fields: {names}")

    specification = data.get("specification", data)
    if not isinstance(specification, dict):
        raise TypeError("specification must be a JSON object.")
    spec = OpenBESSpecification.from_toml(json_to_toml(specification))
    cases = data.get("scenarios", [])
    if not isinstance(cases, list):
        raise TypeError("scenarios must be a JSON array.")
    scenarios = [
        Scenario(
            name=case["name"],
            interventions=tuple(
                _load_intervention(config) for config in case.get("interventions", [])
            ),
        )
        for case in cases
    ]
    return spec, scenarios


def check_cross_ventilation_results(
    comparison: ComparisonResult, scenarios: Sequence[Scenario]
) -> None:
    for scenario in scenarios:
        for intervention in scenario.interventions:
            if not isinstance(intervention, SheltAirCrossVentilation):
                continue

            details = comparison.sheltair_ventilation[scenario.name]
            candidate = f"sa_{intervention.driving_force}_candidate_m3_h"
            assert allclose(
                details["sa_applied_m3_h"], details[candidate], rtol=0.0, atol=1e-9
            ), f"{scenario.name}: applied airflow differs from the selected candidate."

            if (
                intervention.opening_fraction == 0.0
                and len(scenario.interventions) == 1
            ):
                assert allclose(
                    comparison.temperatures[scenario.name],
                    comparison.temperatures["Baseline"],
                    rtol=0.0,
                    atol=1e-6,
                ), f"{scenario.name}: closed openings differ from the baseline."


def save_hourly_plot(
    values: pd.DataFrame, path: Path, *, title: str, ylabel: str
) -> None:
    """Write each full hourly series on the same calendar axis."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure(figsize=(15, 6), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    hours = range(len(values))
    for case, series in values.items():
        if case == "Baseline":
            axes.plot(
                hours, series, label=case, color="#202124", linewidth=1.3, zorder=3
            )
        else:
            axes.plot(hours, series, label=case, linewidth=0.9, alpha=0.8)

    months = values.index.get_level_values("month")
    month_starts = flatnonzero(~months.duplicated())
    tick_labels = [month_abbr[int(months[i])] for i in month_starts]
    axes.set_xticks(month_starts, labels=tick_labels)
    axes.set_xlim(0, max(1, len(values) - 1))
    axes.set(title=title, xlabel="Month", ylabel=ylabel)
    axes.grid(axis="y", alpha=0.25)
    axes.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.15),
        ncols=min(3, len(values.columns)),
        frameon=False,
    )
    figure.savefig(path, dpi=170)


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("shelter_file", type=Path, help="Path to the shelter JSON file")
    parser.add_argument(
        "--relative-humidity",
        action="store_true",
        help="Write one hourly temperature comparison and one relative humidity comparison.",
    )
    parser.add_argument(
        "--plots",
        action="store_true",
        help="Save full-year PNG plots for the hourly comparisons (requires Matplotlib).",
    )
    args = parser.parse_args()

    if args.plots and find_spec("matplotlib") is None:
        parser.error(
            "--plots requires Matplotlib. Install it with python -m pip install matplotlib."
        )

    try:
        spec, scenarios = load_shelter_run(args.shelter_file)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.error(f"Could not load {args.shelter_file}: {exc}")

    try:
        comparison = compare_interventions(
            spec, scenarios, include_relative_humidity=args.relative_humidity
        )
    except ImportError as exc:
        parser.error(str(exc))
    check_cross_ventilation_results(comparison, scenarios)

    temperatures = comparison.temperatures
    summary = pd.DataFrame(
        {
            "Maximum temperature (°C)": temperatures.max(),
            "Hours above 26°C": temperatures.gt(26.0).sum(),
        }
    )

    output_dir = PROJECT_ROOT / "outputs" / args.shelter_file.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    if comparison.relative_humidity is None:
        temperatures.to_csv(output_dir / "hourly_indoor_air_temperature_c.csv")
        comparison.temperature_differences.to_csv(
            output_dir / "hourly_temperature_difference_vs_baseline_c.csv"
        )
        summary.to_csv(output_dir / "peak_temperature_and_hours_above_26c.csv")
    else:
        humidity = comparison.relative_humidity
        humidity_differences = humidity.drop(columns="Baseline").subtract(
            humidity["Baseline"], axis="index"
        )
        pd.concat(
            [
                temperatures,
                comparison.temperature_differences.add_suffix(" minus Baseline (°C)"),
            ],
            axis=1,
        ).to_csv(output_dir / "hourly_indoor_air_temperature_comparison_c.csv")
        pd.concat(
            [
                humidity,
                humidity_differences.add_suffix(" minus Baseline (percentage points)"),
            ],
            axis=1,
        ).to_csv(output_dir / "hourly_indoor_relative_humidity_comparison_pct.csv")

    if args.plots:
        shelter_name = spec.building_name or args.shelter_file.stem
        save_hourly_plot(
            temperatures,
            output_dir / "hourly_indoor_air_temperature.png",
            title=f"{shelter_name} | Hourly indoor air temperature",
            ylabel="Indoor air temperature (°C)",
        )
        if comparison.relative_humidity is not None:
            save_hourly_plot(
                comparison.relative_humidity,
                output_dir / "hourly_indoor_relative_humidity.png",
                title=f"{shelter_name} | Hourly indoor relative humidity",
                ylabel="Indoor relative humidity (%)",
            )

    print(summary.round(3).to_string())
    print(f"Results saved in {output_dir}")


if __name__ == "__main__":
    faulthandler.enable()
    main()
