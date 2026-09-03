from __future__ import annotations

import csv
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SAMPLER_DIR = Path(__file__).resolve().parents[1]
if str(SAMPLER_DIR) not in sys.path:
    sys.path.insert(0, str(SAMPLER_DIR))

import main as sampler  # noqa: E402
import web  # noqa: E402


class TimeHeaderDetectionTests(unittest.TestCase):
    def test_time_column_with_unit_is_detected_when_not_first(self) -> None:
        content = (
            "Value,Time(ms)\n"
            "10,0\n"
            "20,50\n"
            "30,100\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "time_ms.csv"
            path.write_text(content, encoding="utf-8")
            parsed = sampler.parse_file(path, None, None, None)

        self.assertEqual(parsed.time_column_index, 1)
        self.assertEqual(parsed.time_unit, "ms")
        self.assertEqual([record.time_seconds for record in parsed.records], [0.0, 0.05, 0.1])

    def test_common_unit_header_styles(self) -> None:
        cases = {
            "Time(ms)": ("time", "ms"),
            "flow-time [s]": ("flowtime", "s"),
            "timestamp_us": ("timestamp", "us"),
            "Elapsed Time (min)": ("elapsedtime", "min"),
            "physical-time/hr": ("physicaltime", "h"),
            "Time Step": ("timestep", None),
        }
        for header, expected in cases.items():
            with self.subTest(header=header):
                self.assertEqual(sampler.split_time_header(header), expected)
                self.assertTrue(sampler.is_time_header(header))

    def test_invalid_time_column_index_returns_clear_value_error(self) -> None:
        content = "Time(s),Value\n0,1\n1,2\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "data.csv"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside the available range"):
                sampler.parse_file(path, "9", None, None)


class AggregationUnitTests(unittest.TestCase):
    def test_aggregation_restores_millisecond_axis_values(self) -> None:
        content = (
            "Value,Time(ms)\n"
            "10,0\n"
            "20,50\n"
            "30,100\n"
            "40,150\n"
            "50,200\n"
        )
        dataset = web.load_dataset(content.encode("utf-8"), "time_ms.csv", "transient")
        result, output_type = web.process_dataset(
            dataset=dataset,
            data_type="transient",
            method="average",
            interval_text="100ms",
            mode="after",
            x_index=dataset.parsed.time_column_index,
        )

        self.assertEqual(output_type, "csv")
        rows = list(csv.reader(io.StringIO(result.decode("utf-8-sig"))))
        self.assertEqual(rows[0], ["Value", "Time(ms)"])
        self.assertEqual([row[1] for row in rows[1:]], ["0", "100", "200"])
        self.assertEqual([float(row[0]) for row in rows[1:]], [15.0, 35.0, 50.0])

    def test_non_time_axis_is_not_rescaled(self) -> None:
        content = (
            "Time(ms),Iteration,Value\n"
            "0,0,10\n"
            "50,5,20\n"
            "100,10,30\n"
        )
        dataset = web.load_dataset(content.encode("utf-8"), "data.csv", "transient")
        result = web._aggregate_output(  # noqa: SLF001 - regression test for internal behavior
            dataset=dataset,
            values=[0.0, 5.0, 10.0],
            interval=5.0,
            x_index=1,
            method="average",
            data_type="transient",
        )
        rows = list(csv.reader(io.StringIO(result.decode("utf-8-sig"))))
        self.assertEqual([row[1] for row in rows[1:]], ["0", "5", "10"])


class RecursiveOutputTests(unittest.TestCase):
    def test_recursive_processing_preserves_case_subdirectories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_dir = root / "input"
            output_dir = root / "output"
            (input_dir / "caseA").mkdir(parents=True)
            (input_dir / "caseB").mkdir(parents=True)
            (input_dir / "caseA" / "result.csv").write_text(
                "Time(s),Value\n0,1\n1,2\n2,3\n", encoding="utf-8"
            )
            (input_dir / "caseB" / "result.csv").write_text(
                "Time(s),Value\n0,10\n1,20\n2,30\n", encoding="utf-8"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SAMPLER_DIR / "main.py"),
                    "--interval",
                    "1s",
                    "--input",
                    str(input_dir),
                    "--output-dir",
                    str(output_dir),
                    "--recursive",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            case_a = output_dir / "caseA" / "result_1s.csv"
            case_b = output_dir / "caseB" / "result_1s.csv"
            self.assertTrue(case_a.is_file())
            self.assertTrue(case_b.is_file())
            self.assertIn("0,1", case_a.read_text(encoding="utf-8-sig"))
            self.assertIn("0,10", case_b.read_text(encoding="utf-8-sig"))


class FrontendResetTests(unittest.TestCase):
    def test_frontend_contains_preview_invalidation_guards(self) -> None:
        script = (SAMPLER_DIR / "web_static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function invalidatePreview()", script)
        self.assertGreaterEqual(script.count("invalidatePreview();"), 4)
        self.assertIn("sourceRevision", script)
        self.assertIn("if (!state.preview)", script)
        self.assertIn('downloadButton.disabled = true;', script)


class ExistingSampleTests(unittest.TestCase):
    def test_fluent_sample_still_produces_expected_count(self) -> None:
        sample_path = SAMPLER_DIR / "input" / "temp_avg-rfile.out"
        parsed = sampler.parse_file(sample_path, None, None, None)
        selected = sampler.sample_after(parsed.records, 2.0)
        self.assertEqual(len(parsed.records), 1201)
        self.assertEqual(len(selected), 301)
        self.assertEqual(parsed.time_column_index, 2)
        self.assertEqual(parsed.time_unit, "s")


if __name__ == "__main__":
    unittest.main(verbosity=2)
