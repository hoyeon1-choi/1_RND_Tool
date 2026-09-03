"""Browser UI and HTTP API for Sampler.

The server intentionally uses only the Python standard library. Uploaded files
are parsed from a temporary file and are never kept by the application.
"""

from __future__ import annotations

import argparse
import csv
from email import policy
from email.parser import BytesParser
import io
import json
import math
import mimetypes
import re
import socket
import tempfile
import threading
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import main as sampler
import unit_conversion as units


STATIC_DIR = Path(__file__).with_name("web_static")
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_PASTE_BYTES = 5 * 1024 * 1024
MAX_PREVIEW_POINTS = 2_000


@dataclass
class WebDataset:
    parsed: sampler.ParsedFile
    delimiter: str
    columns: list[str]
    fields: list[list[str]]


def _temporary_input(data: bytes, filename: str) -> Path:
    suffix = Path(filename).suffix.lower()
    if suffix not in sampler.SUPPORTED_EXTENSIONS:
        raise ValueError("지원 형식은 .csv, .dat, .out, .txt 입니다.")
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        handle.write(data)
        return Path(handle.name)
    finally:
        handle.close()


def load_dataset(data: bytes, filename: str, data_type: str) -> WebDataset:
    if not data:
        raise ValueError("업로드한 파일이 비어 있습니다.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("파일 크기는 100 MB 이하여야 합니다.")
    if data_type not in {"transient", "steady"}:
        raise ValueError("데이터 형태를 선택해 주세요.")

    temp_path = _temporary_input(data, filename)
    try:
        parsed = sampler.parse_file(
            temp_path,
            time_column=None if data_type == "transient" else "0",
            time_unit=None,
            encoding=None,
        )
    finally:
        temp_path.unlink(missing_ok=True)

    delimiter = sampler.detect_delimiter(parsed.records[0].raw_line)
    fields = [sampler.split_fields(record.raw_line, delimiter) for record in parsed.records]
    width = max(len(row) for row in fields)
    if parsed.header_line:
        header_delimiter = sampler.detect_delimiter(parsed.header_line)
        columns = sampler.split_fields(parsed.header_line, header_delimiter)
    else:
        columns = []
    columns = [column.strip().strip('"') or f"Column {index + 1}" for index, column in enumerate(columns)]
    columns.extend(f"Column {index + 1}" for index in range(len(columns), width))
    return WebDataset(parsed=parsed, delimiter=delimiter, columns=columns, fields=fields)


def _as_number(value: str) -> float | None:
    try:
        number = float(value.strip().strip('"').strip("'"))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _numeric_columns(dataset: WebDataset) -> list[int]:
    sample = dataset.fields[: min(100, len(dataset.fields))]
    numeric: list[int] = []
    for column_index in range(len(dataset.columns)):
        values = [
            _as_number(row[column_index])
            for row in sample
            if column_index < len(row) and row[column_index].strip()
        ]
        if values and sum(value is not None for value in values) / len(values) >= 0.8:
            numeric.append(column_index)
    return numeric


def preview_payload(dataset: WebDataset, data_type: str) -> dict[str, Any]:
    numeric_columns = _numeric_columns(dataset)
    convertible_columns = list(numeric_columns)
    x_index = dataset.parsed.time_column_index if data_type == "transient" else 0
    if data_type == "transient" and x_index not in numeric_columns:
        # Datetime strings are still graphable because parse_file already
        # converted them to seconds internally.
        numeric_columns.insert(0, x_index)
    y_candidates = [index for index in numeric_columns if index != x_index]
    y_index = y_candidates[0] if y_candidates else x_index
    stride = max(1, math.ceil(len(dataset.fields) / MAX_PREVIEW_POINTS))
    rows: list[list[float | None]] = []
    for row_index in range(0, len(dataset.fields), stride):
        row = dataset.fields[row_index]
        preview_row: list[float | None] = []
        for column_index in range(len(dataset.columns)):
            number = _as_number(row[column_index]) if column_index < len(row) else None
            if (
                number is None
                and data_type == "transient"
                and column_index == dataset.parsed.time_column_index
            ):
                number = dataset.parsed.records[row_index].time_seconds
            preview_row.append(number)
        rows.append(preview_row)

    column_hints: list[dict[str, str | None] | None] = []
    for index, column in enumerate(dataset.columns):
        column_hints.append(
            units.header_hint(
                column,
                is_time_column=(
                    data_type == "transient" and index == dataset.parsed.time_column_index
                ),
                parsed_time_unit=dataset.parsed.time_unit,
            )
        )

    return {
        "columns": dataset.columns,
        "numericColumns": numeric_columns,
        "convertibleColumns": convertible_columns,
        "rows": rows,
        "rowCount": len(dataset.fields),
        "previewCount": len(rows),
        "xIndex": x_index,
        "yIndex": y_index,
        "xLabel": "Time" if data_type == "transient" else "Iteration",
        "detectedUnit": dataset.parsed.time_unit if data_type == "transient" else "iteration",
        "unitCatalog": units.catalog_payload(),
        "columnUnitHints": column_hints,
    }


def _interval_value(text: str, data_type: str) -> float:
    if data_type == "transient":
        value, _ = sampler.parse_interval(text)
        return value
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError("Steady data 간격은 양수 숫자로 입력해 주세요.") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError("간격은 0보다 커야 합니다.")
    return value


def _axis_values(dataset: WebDataset, data_type: str, x_index: int) -> list[float]:
    if x_index < 0 or x_index >= len(dataset.columns):
        raise ValueError("X축 열이 올바르지 않습니다.")
    if data_type == "transient" and x_index == dataset.parsed.time_column_index:
        values = [record.time_seconds for record in dataset.parsed.records]
    else:
        values = []
        for row_number, row in enumerate(dataset.fields, start=1):
            value = _as_number(row[x_index]) if x_index < len(row) else None
            if value is None:
                raise ValueError(f"X축 열의 {row_number}번째 데이터가 숫자가 아닙니다.")
            values.append(value)
    for previous, current in zip(values, values[1:]):
        if current < previous:
            raise ValueError("X축 값은 오름차순이어야 합니다.")
    return values


def _sample_indices(values: list[float], interval: float, mode: str) -> list[int]:
    if mode == "after":
        selected = [0]
        target = values[0] + interval
        tolerance = max(interval * 1e-9, 1e-12)
        for index, value in enumerate(values[1:], start=1):
            if value + tolerance >= target:
                selected.append(index)
                while target <= value + tolerance:
                    target += interval
        return selected
    if mode != "nearest":
        raise ValueError("샘플링 기준이 올바르지 않습니다.")

    selected: list[int] = []
    target = values[0]
    index = 0
    last_selected = -1
    tolerance = max(interval * 1e-9, 1e-12)
    while target <= values[-1] + tolerance:
        while index + 1 < len(values) and values[index + 1] < target:
            index += 1
        candidates = [index]
        if index + 1 < len(values):
            candidates.append(index + 1)
        chosen = min(candidates, key=lambda candidate: abs(values[candidate] - target))
        if chosen != last_selected:
            selected.append(chosen)
            last_selected = chosen
        target += interval
    return selected


def _original_rows_output(
    dataset: WebDataset,
    selected: list[int],
    conversion_rules: list[units.ConversionRule],
) -> bytes:
    if not conversion_rules:
        output_lines = [*dataset.parsed.prefix_lines]
        if dataset.parsed.header_line is not None:
            output_lines.append(dataset.parsed.header_line)
        output_lines.extend(dataset.parsed.records[index].raw_line for index in selected)
        return ("\n".join(output_lines) + "\n").encode(dataset.parsed.encoding)

    output_lines = [*dataset.parsed.prefix_lines]
    if dataset.parsed.header_line is not None:
        header_delimiter = sampler.detect_delimiter(dataset.parsed.header_line)
        header_fields = sampler.split_fields(dataset.parsed.header_line, header_delimiter)
        converted_header = units.converted_headers(header_fields, conversion_rules)
        output_lines.append(
            units.serialize_fields(
                converted_header,
                header_delimiter,
                template_line=dataset.parsed.header_line,
                is_header=True,
            )
        )

    for row_index in selected:
        record = dataset.parsed.records[row_index]
        converted = units.apply_rules_to_fields(
            dataset.fields[row_index],
            conversion_rules,
            row_number=record.line_no,
        )
        output_lines.append(
            units.serialize_fields(
                converted,
                dataset.delimiter,
                template_line=record.raw_line,
            )
        )
    return ("\n".join(output_lines) + "\n").encode(dataset.parsed.encoding)


def _sample_output(
    dataset: WebDataset,
    selected: list[int],
    conversion_rules: list[units.ConversionRule] | None = None,
) -> bytes:
    return _original_rows_output(dataset, selected, conversion_rules or [])


def _validate_conversion_source_values(
    dataset: WebDataset,
    conversion_rules: list[units.ConversionRule],
) -> None:
    """Reject non-numeric text in columns selected for conversion.

    Aggregation historically ignored non-numeric cells.  A selected conversion
    column is stricter so engineering data cannot be silently omitted before a
    unit change.
    """

    for rule in conversion_rules:
        for row_index, row in enumerate(dataset.fields):
            if rule.column_index >= len(row):
                raise ValueError(
                    f"{rule.column_index + 1}번째 변환 열이 데이터 행 "
                    f"{dataset.parsed.records[row_index].line_no}에 없습니다."
                )
            raw_value = row[rule.column_index]
            if not raw_value.strip():
                continue
            if _as_number(raw_value) is None:
                raise ValueError(
                    f"{rule.column_index + 1}번째 변환 열의 값 '{raw_value}'은 숫자가 아니어서 "
                    f"단위변환할 수 없습니다 (원본 파일 {dataset.parsed.records[row_index].line_no}행)."
                )


def _parse_conversion_rules(
    raw_text: str | None,
    dataset: WebDataset,
) -> list[units.ConversionRule]:
    if not raw_text:
        return []
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError("단위변환 설정 형식이 올바르지 않습니다.") from exc
    if not isinstance(payload, list):
        raise ValueError("단위변환 설정은 목록이어야 합니다.")
    if len(payload) > 50:
        raise ValueError("단위변환 규칙은 최대 50개까지 설정할 수 있습니다.")

    rules: list[units.ConversionRule] = []
    used_columns: set[int] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("각 단위변환 규칙은 객체 형식이어야 합니다.")
        try:
            column_index = int(item.get("columnIndex", item.get("column_index")))
        except (TypeError, ValueError) as exc:
            raise ValueError("단위변환 열 번호가 올바르지 않습니다.") from exc
        if column_index in used_columns:
            raise ValueError(
                f"{column_index + 1}번째 열에는 단위변환 규칙을 하나만 설정할 수 있습니다."
            )
        rule = units.make_rule(
            column_index=column_index,
            quantity=str(item.get("quantity", "")),
            from_unit=str(item.get("fromUnit", item.get("from_unit", ""))),
            to_unit=str(item.get("toUnit", item.get("to_unit", ""))),
            column_count=len(dataset.columns),
        )
        rules.append(rule)
        used_columns.add(column_index)
    return rules


def _format_number(value: float) -> str:
    """Format calculated values compactly while avoiding floating-point noise."""

    if abs(value) < 1e-15:
        value = 0.0
    return format(value, ".15g")


def _aggregate_axis_output_value(
    dataset: WebDataset,
    data_type: str,
    x_index: int,
    value: float,
) -> str:
    """Convert an internal aggregation axis value back to its displayed unit.

    Parsed transient time is stored internally in seconds. Numeric source time
    columns must therefore be converted back to the unit detected from the
    original header (for example, seconds -> milliseconds for ``Time(ms)``).
    Other user-selected axes are already expressed in their source units.
    """

    is_parsed_transient_time = (
        data_type == "transient" and x_index == dataset.parsed.time_column_index
    )
    if is_parsed_transient_time:
        first_field = dataset.fields[0][x_index] if x_index < len(dataset.fields[0]) else ""
        if _as_number(first_field) is not None:
            factor = sampler.UNIT_FACTORS[dataset.parsed.time_unit]
            value /= factor
    return _format_number(value)


def _aggregate_output(
    dataset: WebDataset,
    values: list[float],
    interval: float,
    x_index: int,
    method: str,
    data_type: str,
    conversion_rules: list[units.ConversionRule] | None = None,
) -> bytes:
    buckets: dict[int, list[int]] = {}
    start = values[0]
    tolerance = max(interval * 1e-9, 1e-12)
    for row_index, value in enumerate(values):
        bucket = max(0, math.floor((value - start + tolerance) / interval))
        buckets.setdefault(bucket, []).append(row_index)

    reducers = {
        "average": lambda items: sum(items) / len(items),
        "min": min,
        "max": max,
    }
    reducer = reducers[method]
    rules = conversion_rules or []
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(units.converted_headers(dataset.columns, rules) if rules else dataset.columns)
    for bucket, row_indices in buckets.items():
        output_row: list[str] = []
        for column_index in range(len(dataset.columns)):
            if column_index == x_index:
                output_row.append(
                    _aggregate_axis_output_value(
                        dataset=dataset,
                        data_type=data_type,
                        x_index=x_index,
                        value=start + bucket * interval,
                    )
                )
                continue
            numbers = [
                value
                for row_index in row_indices
                if column_index < len(dataset.fields[row_index])
                for value in [_as_number(dataset.fields[row_index][column_index])]
                if value is not None
            ]
            output_row.append(_format_number(reducer(numbers)) if numbers else "")
        if rules:
            output_row = units.apply_rules_to_fields(
                output_row,
                rules,
                row_number=bucket + 1,
            )
        writer.writerow(output_row)
    return stream.getvalue().encode("utf-8-sig")


def process_dataset(
    dataset: WebDataset,
    data_type: str,
    method: str,
    interval_text: str,
    mode: str,
    x_index: int,
    conversion_rules: list[units.ConversionRule] | None = None,
) -> tuple[bytes, str]:
    if method not in {"sampling", "average", "min", "max", "convert"}:
        raise ValueError("처리 방법을 선택해 주세요.")
    rules = conversion_rules or []
    if rules:
        _validate_conversion_source_values(dataset, rules)
    if method == "convert":
        if not rules:
            raise ValueError("전체 단위변환을 사용하려면 변환 규칙을 하나 이상 추가해 주세요.")
        selected = list(range(len(dataset.fields)))
        return _original_rows_output(dataset, selected, rules), "original"

    interval = _interval_value(interval_text, data_type)
    values = _axis_values(dataset, data_type, x_index)
    if method == "sampling":
        selected = _sample_indices(values, interval, mode)
        return _sample_output(dataset, selected, rules), "original"
    return (
        _aggregate_output(
            dataset,
            values,
            interval,
            x_index,
            method,
            data_type,
            conversion_rules=rules,
        ),
        "csv",
    )


def _safe_download_name(filename: str, method: str, output_type: str) -> str:
    path = Path(filename)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._") or "result"
    suffix = path.suffix if output_type == "original" else ".csv"
    label = "converted" if method == "convert" else method
    return f"{stem}_{label}{suffix}"


class SamplerHandler(BaseHTTPRequestHandler):
    server_version = "SamplerWeb/1.2"

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[Sampler Web] {self.address_string()} - {format_string % args}")

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"error": message}, status)

    def do_GET(self) -> None:  # noqa: N802
        request_path = urlparse(self.path).path
        relative = "index.html" if request_path == "/" else request_path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _multipart_form(self) -> tuple[dict[str, str], tuple[bytes, str] | None]:
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > MAX_UPLOAD_BYTES + 1024 * 1024:
            raise ValueError("요청 크기는 101 MB 이하여야 합니다.")
        if content_length <= 0:
            raise ValueError("데이터 파일을 선택해 주세요.")
        if not content_type.lower().startswith("multipart/form-data"):
            raise ValueError("요청 형식이 올바르지 않습니다.")

        raw_body = self.rfile.read(content_length)
        message_bytes = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
            + raw_body
        )
        message = BytesParser(policy=policy.default).parsebytes(message_bytes)
        fields: dict[str, str] = {}
        upload: tuple[bytes, str] | None = None

        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if filename is not None and name == "file":
                upload = (payload[: MAX_UPLOAD_BYTES + 1], Path(filename or "data.txt").name)
                continue
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, errors="replace").strip()

        return fields, upload

    def _request_input(self) -> tuple[bytes, str, dict[str, str]]:
        content_type = self.headers.get("Content-Type", "").partition(";")[0].lower()
        field_names = ("data_type", "method", "interval", "mode", "x_index", "conversions")
        if content_type == "application/json":
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > MAX_PASTE_BYTES + 64 * 1024:
                raise ValueError("붙여넣기 데이터는 5 MB 이하여야 합니다.")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("붙여넣기 요청 형식이 올바르지 않습니다.")
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("분석할 데이터를 붙여넣어 주세요.")
            data = text.encode("utf-8")
            if len(data) > MAX_PASTE_BYTES:
                raise ValueError("붙여넣기 데이터는 5 MB 이하여야 합니다.")
            filename = Path(str(payload.get("filename", "pasted_data.txt"))).name
            if Path(filename).suffix.lower() not in sampler.SUPPORTED_EXTENSIONS:
                filename = "pasted_data.txt"
            fields = {name: str(payload.get(name, "")).strip() for name in field_names}
            return data, filename, fields

        form_fields, upload = self._multipart_form()
        if upload is None:
            raise ValueError("데이터 파일을 선택해 주세요.")
        data, filename = upload
        fields = {name: form_fields.get(name, "").strip() for name in field_names}
        return data, filename, fields

    def do_POST(self) -> None:  # noqa: N802
        try:
            data, filename, fields = self._request_input()
            data_type = fields["data_type"]
            dataset = load_dataset(data, filename, data_type)
            if self.path == "/api/preview":
                self._json(preview_payload(dataset, data_type))
                return
            if self.path != "/api/process":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            method = fields["method"]
            conversion_rules = _parse_conversion_rules(fields.get("conversions"), dataset)
            result, output_type = process_dataset(
                dataset=dataset,
                data_type=data_type,
                method=method,
                interval_text=fields["interval"],
                mode=fields["mode"] or "after",
                x_index=int(fields["x_index"] or "0"),
                conversion_rules=conversion_rules,
            )
            download_name = _safe_download_name(filename, method, output_type)
            content_type = (
                "text/csv; charset=utf-8"
                if output_type == "csv" or Path(download_name).suffix.lower() == ".csv"
                else "application/octet-stream"
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        except (ValueError, UnicodeError) as exc:
            self._error(str(exc))
        except Exception as exc:  # Keep browser errors useful without exposing a traceback.
            self._error(f"파일 처리 중 오류가 발생했습니다: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Sampler in a web browser.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser automatically")
    return parser.parse_args()


def _local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    hostname = socket.gethostname()
    candidates = [hostname, socket.getfqdn()]
    for candidate in candidates:
        try:
            for info in socket.getaddrinfo(candidate, None, socket.AF_INET, socket.SOCK_STREAM):
                address = info[4][0]
                if not address.startswith("127."):
                    addresses.add(address)
        except OSError:
            continue

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
        if not address.startswith("127."):
            addresses.add(address)
    except OSError:
        pass
    finally:
        try:
            probe.close()
        except UnboundLocalError:
            pass

    return sorted(addresses)


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), SamplerHandler)
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    print(f"Sampler Web: {url}")
    if args.host == "0.0.0.0":
        addresses = _local_ipv4_addresses()
        if addresses:
            print("다른 PC 접속 주소:")
            for address in addresses:
                print(f"  http://{address}:{args.port}/")
        else:
            print("다른 PC에서는 이 서버 PC의 IPv4 주소와 포트를 사용하세요.")
    print("종료하려면 Ctrl+C를 누르세요.")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSampler Web을 종료합니다.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
