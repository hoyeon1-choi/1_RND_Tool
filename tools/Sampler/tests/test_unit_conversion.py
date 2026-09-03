from __future__ import annotations

import csv
import io
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SAMPLER_DIR = Path(__file__).resolve().parents[1]
if str(SAMPLER_DIR) not in sys.path:
    sys.path.insert(0, str(SAMPLER_DIR))

import unit_conversion as units  # noqa: E402
import web  # noqa: E402


class ConversionMathTests(unittest.TestCase):
    def test_airflow_conversions(self) -> None:
        self.assertAlmostEqual(units.convert_value(1.0, "airflow", "cms", "cmm"), 60.0)
        self.assertAlmostEqual(units.convert_value(1.0, "airflow", "cms", "cmh"), 3600.0)
        self.assertAlmostEqual(units.convert_value(60.0, "airflow", "cmm", "cms"), 1.0)
        self.assertAlmostEqual(units.convert_value(60.0, "airflow", "cmm", "cmh"), 3600.0)
        self.assertAlmostEqual(units.convert_value(3600.0, "airflow", "cmh", "cms"), 1.0)

    def test_temperature_conversions(self) -> None:
        self.assertAlmostEqual(units.convert_value(273.15, "temperature", "k", "degc"), 0.0)
        self.assertAlmostEqual(units.convert_value(25.0, "temperature", "degc", "k"), 298.15)

    def test_humidity_conversions(self) -> None:
        self.assertAlmostEqual(units.convert_value(0.55, "humidity", "fraction", "percent"), 55.0)
        self.assertAlmostEqual(units.convert_value(65.0, "humidity", "percent", "fraction"), 0.65)

    def test_time_conversions(self) -> None:
        self.assertAlmostEqual(units.convert_value(3600.0, "time", "s", "h"), 1.0)
        self.assertAlmostEqual(units.convert_value(2.0, "time", "h", "min"), 120.0)
        self.assertAlmostEqual(units.convert_value(1000.0, "time", "ms", "s"), 1.0)


class HeaderConversionTests(unittest.TestCase):
    def test_header_hints_detect_supported_units(self) -> None:
        cases = {
            "Airflow(CMS)": ("airflow", "cms"),
            "Volume Flow [m3/min]": ("airflow", "cmm"),
            "Temperature[K]": ("temperature", "k"),
            "Outlet Temp_degC": ("temperature", "degc"),
            "RH(%)": ("humidity", "percent"),
            "Time(sec)": ("time", "s"),
            "Elapsed Time/hr": ("time", "h"),
        }
        for header, expected in cases.items():
            with self.subTest(header=header):
                hint = units.header_hint(header)
                self.assertIsNotNone(hint)
                self.assertEqual((hint["quantity"], hint["unit"]), expected)

        # A semantic name can suggest the quantity, but an unlabeled source
        # unit must remain explicit to avoid accidental 50 -> 5000% scaling.
        rh_hint = units.header_hint("RH")
        self.assertEqual(rh_hint, {"quantity": "humidity", "unit": None, "detected": "column-name"})

    def test_time_column_hint_uses_parser_unit(self) -> None:
        hint = units.header_hint("flow-time", is_time_column=True, parsed_time_unit="ms")
        self.assertEqual(hint, {"quantity": "time", "unit": "ms", "detected": "time-column"})

    def test_headers_are_updated_without_losing_style(self) -> None:
        rules = [
            units.make_rule(0, "airflow", "cms", "cmh", 4),
            units.make_rule(1, "temperature", "k", "degc", 4),
            units.make_rule(2, "humidity", "fraction", "percent", 4),
            units.make_rule(3, "time", "s", "min", 4),
        ]
        headers = ["Airflow(CMS)", "Temperature[K]", "RH", "Time/sec"]
        self.assertEqual(
            units.converted_headers(headers, rules),
            ["Airflow(CMH)", "Temperature[degC]", "RH (%)", "Time/min"],
        )

        # An explicit user override is authoritative even when a source header
        # carries a different recognized unit for the same quantity.
        override = units.make_rule(0, "airflow", "cmh", "cmm", 1)
        self.assertEqual(units.converted_headers(["Airflow(CMS)"], [override]), ["Airflow(CMM)"])


class WebConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.content = (
            "Time(sec),Airflow(CMS),Temperature(K),RH(decimal)\n"
            "0,1,300,0.5\n"
            "60,2,273.15,0.75\n"
            "120,3,303.15,0.25\n"
        )
        self.dataset = web.load_dataset(self.content.encode("utf-8"), "engineering.csv", "transient")
        self.rules = [
            units.make_rule(0, "time", "s", "min", 4),
            units.make_rule(1, "airflow", "cms", "cmh", 4),
            units.make_rule(2, "temperature", "k", "degc", 4),
            units.make_rule(3, "humidity", "fraction", "percent", 4),
        ]

    def test_preview_contains_catalog_and_auto_hints(self) -> None:
        payload = web.preview_payload(self.dataset, "transient")
        self.assertEqual(payload["columnUnitHints"][0]["quantity"], "time")
        self.assertEqual(payload["columnUnitHints"][0]["unit"], "s")
        self.assertEqual(payload["columnUnitHints"][1]["unit"], "cms")
        self.assertEqual(payload["columnUnitHints"][2]["unit"], "k")
        self.assertEqual(payload["columnUnitHints"][3]["unit"], "fraction")
        quantity_ids = {item["id"] for item in payload["unitCatalog"]}
        self.assertEqual(quantity_ids, {"airflow", "temperature", "humidity", "time"})

    def test_convert_only_applies_multiple_rules_and_updates_headers(self) -> None:
        result, output_type = web.process_dataset(
            dataset=self.dataset,
            data_type="transient",
            method="convert",
            interval_text="",
            mode="after",
            x_index=0,
            conversion_rules=self.rules,
        )
        self.assertEqual(output_type, "original")
        rows = list(csv.reader(io.StringIO(result.decode("utf-8-sig"))))
        self.assertEqual(
            rows[0],
            ["Time(min)", "Airflow(CMH)", "Temperature(degC)", "RH(%)"],
        )
        self.assertEqual([float(value) for value in rows[1]], [0.0, 3600.0, 26.85, 50.0])
        self.assertEqual([float(value) for value in rows[2]], [1.0, 7200.0, 0.0, 75.0])
        self.assertEqual([float(value) for value in rows[3]], [2.0, 10800.0, 30.0, 25.0])

    def test_sampling_and_conversion_are_combined(self) -> None:
        result, _ = web.process_dataset(
            dataset=self.dataset,
            data_type="transient",
            method="sampling",
            interval_text="120s",
            mode="after",
            x_index=0,
            conversion_rules=self.rules,
        )
        rows = list(csv.reader(io.StringIO(result.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 3)  # header plus t=0 and t=120
        self.assertEqual([float(value) for value in rows[2]], [2.0, 10800.0, 30.0, 25.0])

    def test_aggregation_then_conversion(self) -> None:
        result, output_type = web.process_dataset(
            dataset=self.dataset,
            data_type="transient",
            method="average",
            interval_text="120s",
            mode="after",
            x_index=0,
            conversion_rules=self.rules,
        )
        self.assertEqual(output_type, "csv")
        rows = list(csv.reader(io.StringIO(result.decode("utf-8-sig"))))
        self.assertEqual(rows[0][0], "Time(min)")
        # First bucket averages t=0 and t=60: 1.5 CMS -> 5400 CMH;
        # 286.575 K -> 13.425 degC; RH 0.625 -> 62.5%.
        values = [float(value) for value in rows[1]]
        self.assertAlmostEqual(values[0], 0.0)
        self.assertAlmostEqual(values[1], 5400.0)
        self.assertAlmostEqual(values[2], 13.425)
        self.assertAlmostEqual(values[3], 62.5)
        # The second bucket starts at 120 sec and must be written as 2 min.
        self.assertAlmostEqual(float(rows[2][0]), 2.0)

    def test_non_numeric_selected_value_is_rejected(self) -> None:
        content = "Time(sec),Temperature(K)\n0,300\n1,error\n"
        dataset = web.load_dataset(content.encode("utf-8"), "bad.csv", "transient")
        rule = units.make_rule(1, "temperature", "k", "degc", 2)
        with self.assertRaisesRegex(ValueError, "숫자가 아니어서"):
            web.process_dataset(
                dataset=dataset,
                data_type="transient",
                method="convert",
                interval_text="",
                mode="after",
                x_index=0,
                conversion_rules=[rule],
            )


class CliConversionTests(unittest.TestCase):
    def test_convert_only_cli_supports_multiple_rules(self) -> None:
        content = (
            "Time(sec),Airflow(CMS),Temperature(K),RH(decimal)\n"
            "0,1,300,0.5\n"
            "60,2,273.15,0.75\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "data.csv"
            output = root / "output"
            source.write_text(content, encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SAMPLER_DIR / "main.py"),
                    "--input",
                    str(source),
                    "--output-dir",
                    str(output),
                    "--convert-only",
                    "--convert",
                    "Time:sec:min",
                    "--convert",
                    "Airflow:CMS:CMH",
                    "--convert",
                    "Temperature:K:degC",
                    "--convert",
                    "RH:decimal:%",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result_path = output / "data_converted.csv"
            self.assertTrue(result_path.is_file())
            rows = list(csv.reader(io.StringIO(result_path.read_text(encoding="utf-8-sig"))))
            self.assertEqual(rows[0], ["Time(min)", "Airflow(CMH)", "Temperature(degC)", "RH(%)"])
            self.assertTrue(math.isclose(float(rows[1][2]), 26.85, abs_tol=1e-12))


if __name__ == "__main__":
    unittest.main(verbosity=2)
