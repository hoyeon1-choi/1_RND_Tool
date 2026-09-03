from __future__ import annotations

import argparse
import csv
import logging
import re
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import unit_conversion as units


TOOL_PATH = Path(__file__).resolve().parent
ROOT_DIR = TOOL_PATH.parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from common.logging import setup_logging
    from common.paths import ensure_dir, tool_dir
except ModuleNotFoundError:
    def ensure_dir(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def tool_dir(tool_name: str) -> Path:
        return TOOL_PATH if tool_name == TOOL_NAME else TOOL_PATH.parent / tool_name

    def setup_logging(name: str, log_file: Path | None = None) -> logging.Logger:
        logs_dir = ensure_dir(TOOL_PATH / "logs")
        logger = logging.getLogger(name)
        if logger.handlers:
            return logger

        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        file_handler = logging.FileHandler(log_file or logs_dir / f"{name}.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        return logger


TOOL_NAME = "Sampler"
SUPPORTED_EXTENSIONS = {".csv", ".dat", ".out", ".txt"}
COMMENT_PREFIXES = ("#", "%", "//", "!")
TIME_HEADER_PRIORITY = (
    "flowtime",
    "timestamp",
    "datetime",
    "time",
    "elapsedtime",
    "simulationtime",
    "physicaltime",
    "times",
    "seconds",
    "second",
    "sec",
    "t",
    "timestep",
    "date",
)
TIME_HEADER_NAMES = set(TIME_HEADER_PRIORITY)
UNIT_FACTORS = {
    "ns": 1e-9,
    "us": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "min": 60.0,
    "m": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
}
UNIT_ALIASES = {
    "ns": "ns",
    "nsec": "ns",
    "nsecs": "ns",
    "nanosecond": "ns",
    "nanoseconds": "ns",
    "us": "us",
    "usec": "us",
    "usecs": "us",
    "microsecond": "us",
    "microseconds": "us",
    "ms": "ms",
    "msec": "ms",
    "msecs": "ms",
    "millisecond": "ms",
    "milliseconds": "ms",
    "s": "s",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "m": "min",
    "min": "min",
    "mins": "min",
    "minute": "min",
    "minutes": "min",
    "h": "h",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",
}
HEADER_UNIT_TOKEN = (
    r"ns|nsecs?|nanoseconds?|"
    r"us|usecs?|microseconds?|"
    r"ms|msecs?|milliseconds?|"
    r"s|secs?|seconds?|"
    r"m|mins?|minutes?|"
    r"h|hrs?|hours?"
)
BRACKETED_HEADER_UNIT_PATTERN = re.compile(
    rf"[\(\[\{{]\s*(?P<unit>{HEADER_UNIT_TOKEN})\s*[\)\]\}}]\s*$",
    re.IGNORECASE,
)
SUFFIX_HEADER_UNIT_PATTERN = re.compile(
    rf"(?P<separator>[\s_\-/]+)(?P<unit>{HEADER_UNIT_TOKEN})\s*$",
    re.IGNORECASE,
)
INTERVAL_PATTERN = re.compile(
    r"^\s*(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
    r"(?P<unit>ns|us|ms|s|sec|second|seconds|min|m|h|hr)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Record:
    line_no: int
    raw_line: str
    time_seconds: float


@dataclass(frozen=True)
class ParsedFile:
    encoding: str
    prefix_lines: list[str]
    header_line: str | None
    records: list[Record]
    time_column_index: int
    time_unit: str


def parse_args() -> argparse.Namespace:
    base_dir = tool_dir(TOOL_NAME)

    parser = argparse.ArgumentParser(
        description="Sample time-series data files at a requested time interval."
    )
    parser.add_argument(
        "-i",
        "--interval",
        default=None,
        help="Sampling interval. Examples: 10ms, 0.1s, 5s, 1min",
    )
    parser.add_argument(
        "-f",
        "--input",
        type=Path,
        default=base_dir / "input",
        help="Input file or folder. Default: tools/Sampler/input",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=base_dir / "output",
        help="Output folder. Default: tools/Sampler/output",
    )
    parser.add_argument(
        "-t",
        "--time-column",
        default=None,
        help="Time column index, starting at 0, or a header name. Default: auto or 0",
    )
    parser.add_argument(
        "--time-unit",
        choices=("ns", "us", "ms", "s", "min", "h"),
        default=None,
        help="Unit for numeric time values. Default: auto from header, otherwise s",
    )
    parser.add_argument(
        "--mode",
        choices=("after", "nearest"),
        default="after",
        help="Sampling mode. after selects the first row at or after each target time.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Find input files recursively when --input is a folder.",
    )
    parser.add_argument(
        "--encoding",
        default=None,
        help="Input encoding. Default: auto-detect from utf-8-sig, utf-8, cp949, utf-16.",
    )
    parser.add_argument(
        "--convert",
        action="append",
        default=[],
        metavar="COLUMN:FROM:TO",
        help=(
            "Convert one numeric column. Repeat for multiple columns. "
            "Examples: --convert Airflow:CMS:CMH, --convert 2:K:degC, "
            "--convert RH:decimal:percent, --convert Time:sec:min"
        ),
    )
    parser.add_argument(
        "--convert-only",
        action="store_true",
        help="Convert every data row without sampling. Requires at least one --convert rule.",
    )
    return parser.parse_args()


def get_interval_text(args: argparse.Namespace) -> str:
    if args.interval:
        return args.interval

    value = input("Sampling interval (examples: 10ms, 0.1s, 5s, 1min): ").strip()
    if not value:
        raise ValueError("Sampling interval is required.")
    return value


def read_lines(path: Path, encoding: str | None) -> tuple[list[str], str]:
    encodings = [encoding] if encoding else ["utf-8-sig", "utf-8", "cp949", "utf-16"]

    last_error: UnicodeDecodeError | None = None
    for candidate in encodings:
        if candidate is None:
            continue
        try:
            return path.read_text(encoding=candidate).splitlines(), candidate
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error:
        raise ValueError(f"Could not decode {path}: {last_error}") from last_error
    raise ValueError(f"No encoding was provided for {path}")


def parse_interval(interval_text: str) -> tuple[float, str]:
    match = INTERVAL_PATTERN.fullmatch(interval_text)
    if not match:
        raise ValueError(
            "Invalid interval. Use a positive number with optional unit, "
            "such as 10ms, 0.1s, 5s, or 1min."
        )

    value = float(match.group("value"))
    unit = (match.group("unit") or "s").lower()
    if value <= 0:
        raise ValueError("Interval must be greater than 0.")

    return value * UNIT_FACTORS[unit], interval_label(interval_text, unit)


def interval_label(interval_text: str, default_unit: str) -> str:
    text = interval_text.strip().lower()
    if INTERVAL_PATTERN.fullmatch(text) and not re.search(r"[a-z]", text):
        text = f"{text}{default_unit}"
    text = text.replace(".", "p")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def list_input_files(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {input_path.suffix}")
        return [input_path]

    if not input_path.exists():
        raise ValueError(f"Input path does not exist: {input_path}")
    if not input_path.is_dir():
        raise ValueError(f"Input path must be a file or folder: {input_path}")

    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in input_path.glob(pattern)
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def detect_delimiter(line: str) -> str:
    if "," in line:
        return ","
    if "\t" in line:
        return "\t"
    if ";" in line:
        return ";"
    return "whitespace"


def strip_wrapping_parentheses(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        return stripped[1:-1].strip()
    return stripped


def split_fields(line: str, delimiter: str) -> list[str]:
    cleaned_line = strip_wrapping_parentheses(line)
    if delimiter == "whitespace":
        try:
            return shlex.split(cleaned_line)
        except ValueError:
            return cleaned_line.split()
    return next(csv.reader([cleaned_line], delimiter=delimiter))


def is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith(COMMENT_PREFIXES)


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().strip("()").strip('"').lower())


def canonical_time_unit(value: str) -> str | None:
    """Return a canonical unit name for a header unit token."""

    normalized = value.strip().lower().replace("µ", "u").replace("μ", "u")
    return UNIT_ALIASES.get(normalized)


def split_time_header(value: str) -> tuple[str, str | None]:
    """Split a time header into its normalized base name and optional unit.

    Examples:
        Time(ms)        -> ("time", "ms")
        flow-time [s]   -> ("flowtime", "s")
        timestamp_us    -> ("timestamp", "us")
        Time Step       -> ("timestep", None)
    """

    text = value.strip().strip('"').strip("'").replace("µ", "u").replace("μ", "u")
    unit: str | None = None

    match = BRACKETED_HEADER_UNIT_PATTERN.search(text)
    if match:
        unit = canonical_time_unit(match.group("unit"))
        text = text[: match.start()].rstrip()
    else:
        match = SUFFIX_HEADER_UNIT_PATTERN.search(text)
        if match:
            unit = canonical_time_unit(match.group("unit"))
            text = text[: match.start()].rstrip()

    return normalize_name(text), unit


def is_time_header(value: str) -> bool:
    base_name, _ = split_time_header(value)
    return base_name in TIME_HEADER_NAMES


def parse_time_value(value: str, numeric_unit: str) -> float:
    text = value.strip().strip('"').strip("'")
    try:
        return float(text) * UNIT_FACTORS[numeric_unit]
    except ValueError:
        pass

    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?", text):
        parts = [float(part) for part in text.split(":")]
        if len(parts) == 2:
            hours, minutes = parts
            seconds = 0.0
        else:
            hours, minutes, seconds = parts
        return hours * 3600.0 + minutes * 60.0 + seconds

    iso_text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_text).timestamp()
    except ValueError as exc:
        raise ValueError(f"Invalid time value: {value}") from exc


def looks_like_header(fields: list[str], second_fields: list[str] | None) -> bool:
    if any(is_time_header(field) for field in fields):
        return True

    if not second_fields:
        return False

    try:
        parse_time_value(fields[0], "s")
        first_time_parseable = True
    except ValueError:
        first_time_parseable = False

    try:
        parse_time_value(second_fields[0], "s")
        second_time_parseable = True
    except ValueError:
        second_time_parseable = False

    return not first_time_parseable and second_time_parseable


def looks_like_data_row(fields: list[str]) -> bool:
    if not fields:
        return False

    parseable_count = 0
    for field in fields:
        try:
            parse_time_value(field, "s")
        except ValueError:
            continue
        parseable_count += 1

    required_count = 1 if len(fields) == 1 else 2
    return parseable_count >= required_count


def find_first_data_row(meaningful_lines: list[tuple[int, str]]) -> tuple[int, str, list[str]]:
    for line_index, line in meaningful_lines:
        delimiter = detect_delimiter(line)
        fields = split_fields(line, delimiter)
        if looks_like_data_row(fields):
            return line_index, delimiter, fields
    raise ValueError("No data rows found.")


def find_header_before_data(
    meaningful_lines: list[tuple[int, str]],
    data_start_index: int,
    data_fields: list[str],
) -> tuple[int | None, str | None, list[str] | None]:
    previous_lines = [
        (line_index, line)
        for line_index, line in meaningful_lines
        if line_index < data_start_index
    ]

    for line_index, line in reversed(previous_lines):
        delimiter = detect_delimiter(line)
        fields = split_fields(line, delimiter)
        if looks_like_header(fields, data_fields):
            return line_index, line, fields

    return None, None, None


def resolve_time_column(time_column: str | None, header_fields: list[str] | None) -> int:
    if time_column is not None:
        if time_column.isdigit():
            return int(time_column)

        if not header_fields:
            raise ValueError("--time-column by name requires a header row.")

        requested = normalize_name(time_column)
        requested_base, _ = split_time_header(time_column)
        for index, field in enumerate(header_fields):
            if normalize_name(field) == requested:
                return index
        for index, field in enumerate(header_fields):
            field_base, _ = split_time_header(field)
            if requested == field_base or requested_base == field_base:
                return index
        raise ValueError(f"Time column not found in header: {time_column}")

    if header_fields:
        normalized_fields = [split_time_header(field)[0] for field in header_fields]
        for preferred_name in TIME_HEADER_PRIORITY:
            if preferred_name in normalized_fields:
                return normalized_fields.index(preferred_name)

    return 0


def detect_time_unit(header_field: str | None, requested_unit: str | None) -> str:
    if requested_unit:
        return requested_unit
    if not header_field:
        return "s"

    _, detected_unit = split_time_header(header_field)
    if detected_unit:
        return detected_unit

    normalized = header_field.lower().replace(" ", "")
    if "ns" in normalized:
        return "ns"
    if "us" in normalized or "usec" in normalized:
        return "us"
    if "ms" in normalized or "msec" in normalized:
        return "ms"
    if "min" in normalized:
        return "min"
    if "(h)" in normalized or "[h]" in normalized or "hour" in normalized:
        return "h"
    return "s"


def parsed_header_fields(parsed: ParsedFile) -> list[str] | None:
    if parsed.header_line is None:
        return None
    delimiter = detect_delimiter(parsed.header_line)
    return split_fields(parsed.header_line, delimiter)


def resolve_data_column(
    reference: str,
    header_fields: list[str] | None,
    column_count: int,
) -> int:
    text = reference.strip()
    if re.fullmatch(r"[+-]?\d+", text):
        index = int(text)
        if not 0 <= index < column_count:
            raise ValueError(
                f"Conversion column index {index} is outside the available range "
                f"0..{column_count - 1}."
            )
        return index

    if not header_fields:
        raise ValueError(
            f"Conversion column '{reference}' requires a header row. "
            "Use a zero-based column index instead."
        )

    requested = normalize_name(text)
    requested_base = normalize_name(units.header_base_text(text))
    exact_matches = [
        index for index, field in enumerate(header_fields)
        if normalize_name(field) == requested
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise ValueError(f"Conversion column name is duplicated: {reference}")

    base_matches = [
        index for index, field in enumerate(header_fields)
        if normalize_name(units.header_base_text(field)) in {requested, requested_base}
    ]
    if len(base_matches) == 1:
        return base_matches[0]
    if len(base_matches) > 1:
        raise ValueError(f"Conversion column name is duplicated: {reference}")
    raise ValueError(f"Conversion column not found in header: {reference}")


def parse_cli_conversion_rules(
    specifications: list[str],
    parsed: ParsedFile,
) -> list[units.ConversionRule]:
    if not specifications:
        return []

    delimiter = detect_delimiter(parsed.records[0].raw_line)
    first_fields = split_fields(parsed.records[0].raw_line, delimiter)
    header_fields = parsed_header_fields(parsed)
    column_count = max(len(first_fields), len(header_fields or []))
    rules: list[units.ConversionRule] = []
    used_columns: set[int] = set()

    for specification in specifications:
        parts = specification.rsplit(":", 2)
        if len(parts) != 3 or not all(part.strip() for part in parts):
            raise ValueError(
                "Invalid --convert rule. Use COLUMN:FROM:TO, for example "
                "Airflow:CMS:CMH or Temperature:K:degC."
            )
        column_reference, source_text, target_text = (part.strip() for part in parts)
        source_quantity, source_unit = units.resolve_unit_token(source_text)
        target_quantity, target_unit = units.resolve_unit_token(target_text)
        if source_quantity != target_quantity:
            raise ValueError(
                f"Conversion units must describe the same quantity: "
                f"{source_text} -> {target_text}"
            )
        column_index = resolve_data_column(column_reference, header_fields, column_count)
        if column_index in used_columns:
            raise ValueError(
                f"Only one conversion rule can be assigned to column {column_index}."
            )
        rules.append(
            units.make_rule(
                column_index=column_index,
                quantity=source_quantity,
                from_unit=source_unit,
                to_unit=target_unit,
                column_count=column_count,
            )
        )
        used_columns.add(column_index)

    return rules


def parse_file(path: Path, time_column: str | None, time_unit: str | None, encoding: str | None) -> ParsedFile:
    lines, detected_encoding = read_lines(path, encoding)
    meaningful = [
        (index, line)
        for index, line in enumerate(lines)
        if not is_comment_or_blank(line)
    ]
    if not meaningful:
        raise ValueError(f"No data lines found: {path}")

    try:
        data_start_index, delimiter, data_fields = find_first_data_row(meaningful)
    except ValueError as exc:
        raise ValueError(f"{exc} {path}") from exc

    header_index, header_line, header_fields = find_header_before_data(
        meaningful_lines=meaningful,
        data_start_index=data_start_index,
        data_fields=data_fields,
    )
    prefix_end_index = header_index if header_index is not None else data_start_index
    prefix_lines = lines[:prefix_end_index]

    time_column_index = resolve_time_column(time_column, header_fields)
    available_columns = len(header_fields) if header_fields else len(data_fields)
    if time_column_index < 0 or time_column_index >= available_columns:
        raise ValueError(
            f"Time column index {time_column_index} is outside the available range "
            f"0..{available_columns - 1}: {path}"
        )
    header_time_field = header_fields[time_column_index] if header_fields else None
    numeric_time_unit = detect_time_unit(header_time_field, time_unit)

    records: list[Record] = []
    for line_index, line in enumerate(lines[data_start_index:], start=data_start_index):
        if is_comment_or_blank(line):
            continue

        fields = split_fields(line, delimiter)
        if time_column_index >= len(fields):
            raise ValueError(
                f"Line {line_index + 1} does not have time column {time_column_index}: {path}"
            )

        records.append(
            Record(
                line_no=line_index + 1,
                raw_line=line,
                time_seconds=parse_time_value(fields[time_column_index], numeric_time_unit),
            )
        )

    if not records:
        raise ValueError(f"No sampleable records found: {path}")

    ensure_ascending(records, path)
    return ParsedFile(
        encoding=detected_encoding,
        prefix_lines=prefix_lines,
        header_line=header_line,
        records=records,
        time_column_index=time_column_index,
        time_unit=numeric_time_unit,
    )


def ensure_ascending(records: list[Record], path: Path) -> None:
    previous = records[0]
    for current in records[1:]:
        if current.time_seconds < previous.time_seconds:
            raise ValueError(
                f"Time values must be sorted ascending: {path}, "
                f"line {current.line_no} is earlier than line {previous.line_no}."
            )
        previous = current


def sample_after(records: list[Record], interval_seconds: float) -> list[Record]:
    selected = [records[0]]
    target = records[0].time_seconds + interval_seconds
    tolerance = max(interval_seconds * 1e-9, 1e-12)

    for record in records[1:]:
        if record.time_seconds + tolerance >= target:
            selected.append(record)
            while target <= record.time_seconds + tolerance:
                target += interval_seconds

    return selected


def sample_nearest(records: list[Record], interval_seconds: float) -> list[Record]:
    selected: list[Record] = []
    target = records[0].time_seconds
    last_time = records[-1].time_seconds
    index = 0
    last_selected_index = -1
    tolerance = max(interval_seconds * 1e-9, 1e-12)

    while target <= last_time + tolerance:
        while index + 1 < len(records) and records[index + 1].time_seconds < target:
            index += 1

        candidates = [index]
        if index + 1 < len(records):
            candidates.append(index + 1)

        chosen_index = min(
            candidates,
            key=lambda candidate: abs(records[candidate].time_seconds - target),
        )
        if chosen_index != last_selected_index:
            selected.append(records[chosen_index])
            last_selected_index = chosen_index

        target += interval_seconds

    return selected


def write_sampled_file(
    source_path: Path,
    output_dir: Path,
    label: str,
    parsed: ParsedFile,
    selected: list[Record],
    conversion_rules: list[units.ConversionRule] | None = None,
) -> Path:
    ensure_dir(output_dir)
    output_path = output_dir / f"{source_path.stem}_{label}{source_path.suffix}"
    rules = conversion_rules or []

    # Preserve the source text byte-for-byte (apart from line endings) when no
    # conversion was requested.  Reconstruct rows only when numeric values and
    # header units must actually change.
    if not rules:
        output_lines = [*parsed.prefix_lines]
        if parsed.header_line is not None:
            output_lines.append(parsed.header_line)
        output_lines.extend(record.raw_line for record in selected)
        output_path.write_text("\n".join(output_lines) + "\n", encoding=parsed.encoding)
        return output_path

    delimiter = detect_delimiter(parsed.records[0].raw_line)
    output_lines = [*parsed.prefix_lines]
    if parsed.header_line is not None:
        header_delimiter = detect_delimiter(parsed.header_line)
        header_fields = split_fields(parsed.header_line, header_delimiter)
        converted_header = units.converted_headers(header_fields, rules)
        output_lines.append(
            units.serialize_fields(
                converted_header,
                header_delimiter,
                template_line=parsed.header_line,
                is_header=True,
            )
        )

    for record in selected:
        fields = split_fields(record.raw_line, delimiter)
        converted = units.apply_rules_to_fields(
            fields,
            rules,
            row_number=record.line_no,
        )
        output_lines.append(
            units.serialize_fields(converted, delimiter, template_line=record.raw_line)
        )

    output_path.write_text("\n".join(output_lines) + "\n", encoding=parsed.encoding)
    return output_path


def output_dir_for_input(
    input_file: Path,
    input_root: Path,
    output_root: Path,
    recursive: bool,
) -> Path:
    """Return an output directory that avoids recursive filename collisions.

    When recursive input processing is enabled, the input directory structure is
    reproduced below the output root. Files with the same name in different case
    folders therefore cannot overwrite each other.
    """

    if not recursive or not input_root.is_dir():
        return output_root

    try:
        relative_parent = input_file.resolve().relative_to(input_root.resolve()).parent
    except ValueError:
        return output_root
    return output_root / relative_parent


def process_file(
    input_file: Path,
    output_dir: Path,
    interval_seconds: float | None,
    label: str,
    args: argparse.Namespace,
) -> tuple[Path, int, int, int, str, int]:
    parsed = parse_file(input_file, args.time_column, args.time_unit, args.encoding)
    conversion_rules = parse_cli_conversion_rules(args.convert, parsed)
    if args.convert_only:
        selected = parsed.records
    else:
        if interval_seconds is None:
            raise ValueError("Sampling interval is required unless --convert-only is used.")
        selected = (
            sample_nearest(parsed.records, interval_seconds)
            if args.mode == "nearest"
            else sample_after(parsed.records, interval_seconds)
        )
    output_path = write_sampled_file(
        input_file,
        output_dir,
        label,
        parsed,
        selected,
        conversion_rules=conversion_rules,
    )
    return (
        output_path,
        len(parsed.records),
        len(selected),
        parsed.time_column_index,
        parsed.time_unit,
        len(conversion_rules),
    )


def main() -> int:
    logger = setup_logging(TOOL_NAME)
    args = parse_args()

    try:
        if args.convert_only:
            if not args.convert:
                raise ValueError("--convert-only requires at least one --convert rule.")
            interval_text = None
            interval_seconds = None
            label = "converted"
        else:
            interval_text = get_interval_text(args)
            interval_seconds, interval_label_text = parse_interval(interval_text)
            label = f"{interval_label_text}_converted" if args.convert else interval_label_text
        input_files = list_input_files(args.input, args.recursive)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not input_files:
        print(f"No input files found in {args.input}", file=sys.stderr)
        return 1

    logger.info("Tool started")
    if args.convert_only:
        logger.info("Processing mode: unit conversion only")
    else:
        logger.info("Sampling interval: %s (%s seconds)", interval_text, interval_seconds)
        logger.info("Sampling mode: %s", args.mode)
    if args.convert:
        logger.info("Unit conversion rules: %s", "; ".join(args.convert))

    failures = 0
    for input_file in input_files:
        try:
            file_output_dir = output_dir_for_input(
                input_file=input_file,
                input_root=args.input,
                output_root=args.output_dir,
                recursive=args.recursive,
            )
            (
                output_path,
                total_rows,
                sampled_rows,
                time_column_index,
                time_unit,
                conversion_count,
            ) = process_file(
                input_file=input_file,
                output_dir=file_output_dir,
                interval_seconds=interval_seconds,
                label=label,
                args=args,
            )
        except ValueError as exc:
            failures += 1
            logger.error("%s", exc)
            continue

        logger.info(
            "Created %s | rows: %s -> %s | time column: %s | time unit: %s | conversions: %s",
            output_path,
            total_rows,
            sampled_rows,
            time_column_index,
            time_unit,
            conversion_count,
        )

    if failures:
        print(f"Completed with {failures} failed file(s). See logs/Sampler.log.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    if "--web" in sys.argv:
        sys.argv.remove("--web")
        tool_path = str(Path(__file__).resolve().parent)
        if tool_path not in sys.path:
            sys.path.insert(0, tool_path)
        import web

        raise SystemExit(web.main())
    raise SystemExit(main())
