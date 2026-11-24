import unittest
from dataclasses import replace
from math import sqrt

from numpy import testing

from openbes.examples import HOLYWELL_HOUSE_SPEC
from openbes.schemas import PassiveOpening, json_to_toml, toml_to_json
from openbes.simulations.thermal import ThermalSimulation, specs_require_thermal_rerun
from openbes.simulations.ventilation import (
    passive_stack_airflow_m3_h,
    passive_stack_opening_factor,
)
from openbes.types import OpenBESSpecification


class TestPassiveVentilation(unittest.TestCase):
    def test_individual_openings_at_same_height_match_grouped_area(self):
        grouped = (
            PassiveOpening(opening_id="low", centre_height_m=0.2, free_area_m2=0.032),
            PassiveOpening(opening_id="high", centre_height_m=3.0, free_area_m2=0.032),
        )
        individual = tuple(
            opening.model_copy(
                update={
                    "opening_id": f"{opening.opening_id}_{i}",
                    "free_area_m2": 0.008,
                }
            )
            for opening in grouped
            for i in range(4)
        )
        expected_factor = 0.6 * 0.032 * sqrt((3.0 - 0.2) / 2.0)
        self.assertAlmostEqual(passive_stack_opening_factor(grouped), expected_factor)
        self.assertAlmostEqual(
            passive_stack_opening_factor(individual), expected_factor
        )

    def test_openings_at_multiple_elevations_balance_at_neutral_height(self):
        openings = tuple(
            PassiveOpening(
                opening_id=str(height), centre_height_m=height, free_area_m2=0.1
            )
            for height in (0.0, 2.0, 3.0, 5.0)
        )
        factor = passive_stack_opening_factor(openings)
        expected_factor = 0.6 * 0.1 * (sqrt(2.5) + sqrt(0.5))
        self.assertAlmostEqual(factor, expected_factor)
        self.assertEqual(passive_stack_airflow_m3_h(factor, 20, 20), 0.0)
        self.assertAlmostEqual(
            passive_stack_airflow_m3_h(factor, 25, 20),
            passive_stack_airflow_m3_h(factor, 20, 25),
        )

    def test_unavailable_openings_produce_no_stack_exchange(self):
        openings = (
            PassiveOpening(opening_id="low", centre_height_m=0.2, free_area_m2=0.032),
            PassiveOpening(opening_id="closed", centre_height_m=3.0, free_area_m2=0.0),
        )
        self.assertEqual(passive_stack_opening_factor(openings), 0.0)
        self.assertEqual(passive_stack_airflow_m3_h(1.0, None, 20), 0.0)

    def test_spec_round_trip_preserves_openings_and_invalidates_thermal_cache(self):
        openings = [
            {"opening_id": "low", "centre_height_m": 0.2, "free_area_m2": 0.032},
            {"opening_id": "high", "centre_height_m": 3.0, "free_area_m2": 0.032},
        ]
        toml = json_to_toml({"passive_openings": openings})
        spec = OpenBESSpecification.from_toml(toml)
        self.assertEqual(toml_to_json(toml)["passive_openings"], openings)
        self.assertEqual(
            spec.passive_openings, tuple(PassiveOpening(**v) for v in openings)
        )
        self.assertTrue(specs_require_thermal_rerun(OpenBESSpecification(), spec))

    def test_thermal_uses_passive_flow_alongside_existing_airflows(self):
        spec = replace(
            HOLYWELL_HOUSE_SPEC,
            passive_openings=(
                PassiveOpening(
                    opening_id="low", centre_height_m=0.2, free_area_m2=0.032
                ),
                PassiveOpening(
                    opening_id="high", centre_height_m=3.0, free_area_m2=0.032
                ),
            ),
        )
        simulation = ThermalSimulation(spec)
        self.assertGreater(simulation.passive_stack_airflow_m3_h.max(), 0.0)
        specific_flow = (
            simulation.passive_stack_airflow_m3_h
            / simulation.geometry.conditioned_floor_area
        )
        testing.assert_allclose(
            simulation.air_flow,
            simulation.air_flow_base
            + simulation.air_flow_dependent
            + simulation.ventilation.air_supply_rate
            + specific_flow,
        )
