import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

import run_intervention_comparison as driver
from openbes.interventions.sheltair_cross_ventilation import (
    SheltAirSingleSidedTwoOpenings,
)
from openbes.simulations.base import HOURS_DF
from openbes.simulations.moisture import calculate_indoor_moisture
from openbes.simulations.sheltair_cross_ventilation import SheltAirTwoOpeningModel
from openbes.simulations.thermal import ThermalSimulation


class TestCoolingComparison(unittest.TestCase):
    def test_scheduled_same_wall_buoyancy_uses_printed_equation(self):
        settings = SheltAirSingleSidedTwoOpenings(
            max_free_areas_m2=(2.1, 0.2), centre_height_difference_m=0.6
        )
        model = SheltAirTwoOpeningModel(settings)
        weather = {
            "indoor_temp_c": 30.0,
            "outdoor_temp_c": 25.0,
            "weather_wind_speed_m_s": 4.0,
            "month": 7,
        }
        result = model.calculate(hour_midpoint=12.5, **weather)
        ratio = 2.1 / 0.2
        flow = (
            3600
            * 0.6
            * 2.1
            / (1 + ratio**2)
            * math.sqrt(2 * 9.81 * 0.6 * 5 / (27.5 + 273))
        )
        self.assertAlmostEqual(result["sa_applied_m3_h"], flow)
        self.assertEqual(result["sa_wind_candidate_m3_h"], 0.0)
        self.assertEqual(
            model.calculate(hour_midpoint=23.5, **weather)["sa_applied_m3_h"], 0.0
        )

    def test_moisture_uses_opening_airflow_in_addition_to_background_airflow(self):
        thermal = ThermalSimulation.__new__(ThermalSimulation)
        thermal.spec = SimpleNamespace(floor_to_ceiling_height=2.5)
        thermal.geometry = SimpleNamespace(conditioned_floor_area=10.0)
        thermal.ventilation = SimpleNamespace(ventilation_simulations=[])
        thermal.location = SimpleNamespace(epw_data=pd.DataFrame())
        thermal._hours = pd.DataFrame(
            {"_natural_outdoor_airflow": [2.0], "sa_applied_m3_h": [30.0]}
        )
        temperature = pd.Series([25.0])
        with patch("openbes.simulations.thermal.calculate_indoor_moisture") as solve:
            thermal.indoor_moisture_at_temperature(temperature)
        inputs = solve.call_args.kwargs
        self.assertIs(inputs["indoor_temperature"], temperature)
        self.assertEqual(inputs["outdoor_airflow"].iloc[0], 50.0)
        self.assertEqual(inputs["indoor_air_volume"], 25.0)

    def test_moisture_initializes_si_without_calling_vectorized_unit_getter(self):
        psychrolib = Mock(SI="SI", PSYCHROLIB_UNITS=None)
        psychrolib.GetUnitSystem.side_effect = AssertionError("Used vectorized getter")
        psychrolib.GetHumRatioFromRelHum.return_value = 0.008
        psychrolib.GetRelHumFromHumRatio.return_value = 0.5
        weather = pd.DataFrame(
            {
                "temp_air": [20.0],
                "relative_humidity": [50.0],
                "atmospheric_pressure": [93000.0],
            }
        )
        with patch.dict("sys.modules", {"psychrolib": psychrolib}):
            moisture = calculate_indoor_moisture(
                weather, pd.Series([20.0]), pd.Series([10.0]), 25.0
            )

        psychrolib.GetUnitSystem.assert_not_called()
        psychrolib.SetUnitSystem.assert_called_once_with(psychrolib.SI)
        self.assertEqual(moisture["indoor_relative_humidity"].iloc[0], 50.0)

    def test_driver_exports_both_full_year_comparisons_and_plots(self):
        shelter_path = driver.PROJECT_ROOT / "scala_example_shelters" / "azraq_s05.json"
        hours = HOURS_DF.index
        baseline = Mock(
            air_free_temp=pd.Series(28.0, index=hours),
            window_shading_details=pd.DataFrame(),
            sheltair_ventilation_details=pd.DataFrame(),
        )
        strategy = Mock(
            air_free_temp=pd.Series(25.0, index=hours),
            window_shading_details=pd.DataFrame(),
            sheltair_ventilation_details=pd.DataFrame(),
        )
        baseline.indoor_moisture_at_temperature.return_value = pd.DataFrame(
            {"indoor_relative_humidity": 45.0}, index=hours
        )
        strategy.indoor_moisture_at_temperature.return_value = pd.DataFrame(
            {"indoor_relative_humidity": 50.0}, index=hours
        )
        spec, scenarios = driver.load_shelter_run(shelter_path)
        shading_case = scenarios[0]
        with TemporaryDirectory(dir=driver.PROJECT_ROOT) as directory:
            root = Path(directory)
            with (
                patch.object(driver, "PROJECT_ROOT", root),
                patch.object(
                    driver, "load_shelter_run", return_value=(spec, [shading_case])
                ),
                patch(
                    "openbes.scenario_comparison.ThermalSimulation",
                    side_effect=[baseline, strategy],
                ),
                patch.object(driver, "find_spec", return_value=object()),
                patch.object(driver, "save_hourly_plot") as save_plot,
                patch(
                    "sys.argv",
                    ["run", str(shelter_path), "--relative-humidity", "--plots"],
                ),
            ):
                driver.main()

            output = root / "outputs" / shelter_path.stem
            temperature_csv = output / "hourly_indoor_air_temperature_comparison_c.csv"
            humidity_csv = output / "hourly_indoor_relative_humidity_comparison_pct.csv"
            self.assertEqual(set(output.glob("*.csv")), {temperature_csv, humidity_csv})
            temperatures = pd.read_csv(temperature_csv)
            humidity = pd.read_csv(humidity_csv)
            self.assertEqual(len(temperatures), 8760)
            self.assertEqual(len(humidity), 8760)
            self.assertEqual(temperatures.loc[0, "Baseline"], 28.0)
            self.assertEqual(
                temperatures.loc[0, f"{shading_case.name} minus Baseline (°C)"], -3.0
            )
            self.assertEqual(humidity.loc[0, shading_case.name], 50.0)
            self.assertEqual(
                humidity.loc[
                    0, f"{shading_case.name} minus Baseline (percentage points)"
                ],
                5.0,
            )
            self.assertEqual(save_plot.call_count, 2)
            for call, csv, plot_name in zip(
                save_plot.call_args_list,
                (temperatures, humidity),
                (
                    "hourly_indoor_air_temperature.png",
                    "hourly_indoor_relative_humidity.png",
                ),
                strict=True,
            ):
                plot_values, plot_path = call.args
                self.assertEqual(plot_path, output / plot_name)
                pd.testing.assert_frame_equal(
                    plot_values,
                    csv.set_index(["month", "day", "hour"])[
                        ["Baseline", shading_case.name]
                    ],
                )

    @unittest.skipUnless(driver.find_spec("matplotlib"), "Matplotlib is optional")
    def test_full_year_plot_writes_a_png(self):
        temperatures = pd.DataFrame(
            {"Baseline": 28.0, "Roof shading": 25.0}, index=HOURS_DF.index
        )
        with TemporaryDirectory(dir=driver.PROJECT_ROOT) as directory:
            path = Path(directory) / "temperatures.png"
            driver.save_hourly_plot(
                temperatures,
                path,
                title="Hourly indoor air temperature",
                ylabel="Indoor air temperature (°C)",
            )
            with path.open("rb") as plot_file:
                self.assertEqual(plot_file.read(8), b"\x89PNG\r\n\x1a\n")
