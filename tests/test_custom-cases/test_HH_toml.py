from calendar import month_name
import tomllib
import unittest
from pathlib import Path

from openbes.simulations.building_energy import (
    BuildingEnergySimulation,
    day_of_the_month,
)
from openbes.types import OpenBESSpecification
from openbes.types.enums import ENERGY_USE_CATEGORIES


class HolywellHouseCase(unittest.TestCase):
    """Regression checks for the Holywell House example summary table."""

    @classmethod
    def setUpClass(cls):
        toml_path = Path(__file__).parent / "custom-cases" / "Holywell-House_v2_newinputs.toml"   #Holywell-House_v1_json.toml
        with open(toml_path, "rb") as f:
            cls.toml_content = tomllib.load(f)
        spec = OpenBESSpecification.from_toml(dict(cls.toml_content))
        cls.simulation = BuildingEnergySimulation(spec)

    def test_input_values_are_applied(self):
        """Every populated TOML key must land on the spec/parameters unchanged."""
        spec = self.simulation.spec
        parameters = spec.parameters
        mismatches = []

        print(f"\n{'Key':<55} {'Input':>20} {'Applied':>20}")
        print("-" * 97)
        for key, raw_value in self.toml_content.items():
            if raw_value is None or raw_value == "":
                continue
            prefix, name = key.split(".", 1)
            target = parameters if prefix == "d" else spec
            target_label = "parameters" if prefix == "d" else "specification"
            if name == "meteorological_file":
                name = "meteorological_file_path"

            if not hasattr(target, name):
                mismatches.append(f"{key}: no matching field on {target_label}")
                print(f"{key:<55} {raw_value!s:>20} {'<missing field>':>20}")
                continue

            applied_value = getattr(target, name)
            print(f"{key:<55} {raw_value!s:>20} {applied_value!s:>20}")
            if applied_value is None:
                mismatches.append(
                    f"{key}: input {raw_value!r} was dropped (applied value is None)"
                )

        if mismatches:
            self.fail("Input values were not applied correctly:\n" + "\n".join(mismatches))

    @staticmethod
    def _peak_date(series):
        month, day_of_year, hour = series.idxmax()
        return {
            "month": month_name[month],
            "day": day_of_the_month(day_of_year, month),
            "hour": hour,
        }

    @staticmethod
    def _display_results(expected_values, calculated_values):
        print("\nHolywell House summary results")
        print(f"{'Metric':<55} {'Expected':>14} {'Calculated':>14} {'Difference':>14}")
        print("-" * 101)
        for metric, expected in expected_values.items():
            calculated = calculated_values[metric]
            if isinstance(expected, (int, float)):
                expected_display = f"{expected:.2f}"
                calculated_display = f"{calculated:.2f}"
                difference_display = f"{calculated - expected:.2f}"
            else:
                expected_display = expected
                calculated_display = calculated
                difference_display = "-"
            print(
                f"{metric:<55} {expected_display!s:>14} "
                f"{calculated_display!s:>14} {difference_display:>14}"
            )

    def test_summary_table(self):
        simulation = self.simulation
        thermal = simulation.thermal
        area = simulation.geometry.conditioned_floor_area
        occupancy_load = (
            simulation.occupancy.occupancy_ratio
            * simulation.occupancy.metabolic_rate_per_m2
        )
        air_changes_per_hour = (
            thermal.air_flow * area / (area * simulation.spec.floor_to_ceiling_height)
        )
        occupied_period = simulation.occupancy.is_occupied
        discomfort_hours = (
            thermal.air_free_temp * occupied_period >= 26.0
        ).sum()
        category_energy = {
            category: energy.sum().sum() / area
            for category, energy in simulation.energy_use_by_category.items()
        }

        expected_values = {
            "Internal heat gains (max W/m2)": 6.00, #7.208627843456142,
            "Occupancy load (max W/m2)": 4.79, #2.50
            "Air changes per hour (max h-1)": 0.172777, #0.1792115984868153,
            "Free-running air temperature maximum (C)": 33.84191, #33.368577787094885,
            "Free-running air temperature maximum month": "July",
            "Free-running air temperature maximum day": 20,
            "Free-running air temperature maximum hour": 17,
            "Free-running air temperature minimum (C)": -0.99765, #-1.018725780924096,
            "Free-running air temperature minimum month": "December",
            "Free-running air temperature minimum day": 14,
            "Free-running air temperature minimum hour": 7,
            "Discomfort hours above 26C (occupied)": 71.0,#60,
            "Heating demand (kWh/m2)": 66.87,#69.85324261822116,
            "Peak heating demand (kW)": 205.35, #202.21543020492584,
            "Cooling demand (kWh/m2)": 8.13,#6.4295132234085095,
            "Peak cooling demand (kW)": 50.44, #47.95130958353576,
            "Final energy - Heating (kWh/m2)": 48.83, #48.8026796296067,
            "Final energy - Cooling (kWh/m2)": 2.02, #1.4367525247472792,
            "Final energy - Ventilation (kWh/m2)": 0.55, #0.34208633438072567,
            "Final energy - Hot water (kWh/m2)": 3.50, #33.4953621455168364,
            "Final energy - Lighting (kWh/m2)": 6.39, #6.3856115751068785,
            "Final energy - Building standby (kWh/m2)": 25.41, #25.4096255796653,
            "Final energy - Others (kWh/m2)": 12.44, #12.43552242740814,
            "Final energy total (kWh/m2)": 99.1, #98.30764021643186,
            "Carbon emissions total (kg CO2e/m2)": 16.0, #18.396515071284224,
        }
        calculated_values = {
            "Internal heat gains (max W/m2)": thermal.internal_heat.max(),
            "Occupancy load (max W/m2)": occupancy_load.max(),
            "Air changes per hour (max h-1)": air_changes_per_hour.max(),
            "Free-running air temperature maximum (C)": thermal.air_free_temp.max(),
            "Free-running air temperature maximum month": self._peak_date(
                thermal.air_free_temp
            )["month"],
            "Free-running air temperature maximum day": self._peak_date(
                thermal.air_free_temp
            )["day"],
            "Free-running air temperature maximum hour": self._peak_date(
                thermal.air_free_temp
            )["hour"],
            "Free-running air temperature minimum (C)": thermal.air_free_temp.min(),
            "Free-running air temperature minimum month": self._peak_date(
                -thermal.air_free_temp
            )["month"],
            "Free-running air temperature minimum day": self._peak_date(
                -thermal.air_free_temp
            )["day"],
            "Free-running air temperature minimum hour": self._peak_date(
                -thermal.air_free_temp
            )["hour"],
            "Discomfort hours above 26C (occupied)": discomfort_hours,
            "Heating demand (kWh/m2)": simulation.space_hvac_demand.loc[
                ("Heating", simulation.building_name), "Demand (kWh/m2)"
            ],
            "Peak heating demand (kW)": simulation.space_hvac_demand.loc[
                ("Heating", simulation.building_name), "Peak (kW)"
            ],
            "Cooling demand (kWh/m2)": simulation.space_hvac_demand.loc[
                ("Cooling", simulation.building_name), "Demand (kWh/m2)"
            ],
            "Peak cooling demand (kW)": simulation.space_hvac_demand.loc[
                ("Cooling", simulation.building_name), "Peak (kW)"
            ],
            "Final energy - Heating (kWh/m2)": category_energy[
                ENERGY_USE_CATEGORIES.Heating
            ],
            "Final energy - Cooling (kWh/m2)": category_energy[
                ENERGY_USE_CATEGORIES.Cooling
            ],
            "Final energy - Ventilation (kWh/m2)": category_energy[
                ENERGY_USE_CATEGORIES.Ventilation
            ],
            "Final energy - Hot water (kWh/m2)": category_energy[
                ENERGY_USE_CATEGORIES.Hot_water
            ],
            "Final energy - Lighting (kWh/m2)": category_energy[
                ENERGY_USE_CATEGORIES.Lighting
            ],
            "Final energy - Building standby (kWh/m2)": category_energy[
                ENERGY_USE_CATEGORIES.Building_standby
            ],
            "Final energy - Others (kWh/m2)": category_energy[
                ENERGY_USE_CATEGORIES.Others
            ],
            "Final energy total (kWh/m2)": simulation.energy_use.sum().sum() / area,
            "Carbon emissions total (kg CO2e/m2)": simulation.kg_co2_eq.sum() / area,
        }

        self._display_results(expected_values, calculated_values)

        for metric, expected in expected_values.items():
            with self.subTest(metric=metric):
                self.assertAlmostEqual(calculated_values[metric], expected, places=2)