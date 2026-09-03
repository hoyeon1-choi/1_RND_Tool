# Sampler

Sample time-series data files at a requested time interval.

Current bundled version: **1.2.0**

## Web UI

Sampler can run entirely in a web browser. The web UI supports:

- Transient data (`time - value`) and steady data (`iteration - value`)
- `.csv`, `.dat`, `.out`, and `.txt` uploads up to 100 MB
- Paste small CSV, tab-delimited, or whitespace-delimited data as text (up to 5 MB)
- Interactive X/Y column selection and a graph preview
- Interval sampling (`after` or `nearest`)
- Interval average, minimum, and maximum aggregation
- Downloading the processed result
- Preserving the detected numeric time unit in aggregated CSV output
- Resetting stale preview and axis selections whenever the input source changes
- Converting multiple engineering-data columns in one run
- Applying unit conversion by itself or together with Sampling, Average, Minimum, and Maximum
- Automatically suggesting source units from headers and updating output header units
- Showing converted values immediately in the graph preview

From the project root, run:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_tool.py Sampler --web
```

For a portable server copy, copy the whole `tools\Sampler` folder to the new
server PC and run this file inside that copied folder:

```powershell
.\run_web.bat
```

`run_web.bat` does not need the project root, `scripts\run_tool.py`, or the
`common` folder. It only needs Python 3 on the server PC and the files inside
the copied `Sampler` folder. Python 3.10 or newer is recommended. The batch
file binds to `0.0.0.0:8765`, so other PCs on the same network can connect by
using the server PC's IP address, for example `http://10.x.x.x:8765/`.

The browser opens at `http://127.0.0.1:8765`. To choose another port or avoid
opening the browser automatically:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_tool.py Sampler --web --port 9000
.\.venv\Scripts\python.exe .\scripts\run_tool.py Sampler --web --no-browser
```

To allow another computer on the same network to connect, bind to all network
interfaces. Only do this on a trusted network because uploaded data is sent to
the machine running Sampler.

```powershell
.\.venv\Scripts\python.exe .\scripts\run_tool.py Sampler --web --host 0.0.0.0
```

The web version has no third-party package dependency. Uploaded files are
stored only in a temporary file while a request is being parsed and are then
deleted. If file uploads are blocked by browser or company security policy,
select **텍스트 붙여넣기** and paste the column header and data rows directly.
Pasted text is sent as JSON rather than as a file upload. Sampling preserves
the original text format and encoding. Aggregated results are downloaded as
UTF-8 CSV.

Supported input extensions:

- `.csv`
- `.dat`
- `.out`
- `.txt`

By default, Sampler reads every supported file in `tools/Sampler/input/` and writes sampled files to `tools/Sampler/output/`.

Output file names use this format:

```text
<original_file_name>_<interval><original_extension>
```

Examples:

```text
signal.csv -> signal_10ms.csv
raw_data.dat -> raw_data_1s.dat
```

## Basic Run

From the project root:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_tool.py Sampler --interval 10ms
```

You can also run `main.py` directly:

```powershell
.\.venv\Scripts\python.exe .\tools\Sampler\main.py --interval 10ms
```

or, after activating the virtual environment:

```powershell
python .\scripts\run_tool.py Sampler --interval 10ms
```

If `--interval` is omitted, Sampler asks for it at runtime.

## Options

```powershell
python .\scripts\run_tool.py Sampler --interval 0.1s
python .\scripts\run_tool.py Sampler --interval 1s --input .\tools\Sampler\input\data.csv
python .\scripts\run_tool.py Sampler --interval 10s --input .\tools\Sampler\temp_avg-rfile.out
python .\scripts\run_tool.py Sampler --interval 100ms --time-column Time
python .\scripts\run_tool.py Sampler --interval 100ms --time-column 0 --time-unit ms
python .\scripts\run_tool.py Sampler --interval 1s --mode nearest
```

## Time Column

Sampler uses the first column as time by default.

If a header row exists, it can automatically detect common names such as:

- `time`
- `t`
- `timestamp`
- `datetime`
- `seconds`

You can also specify a column directly:

```powershell
python .\scripts\run_tool.py Sampler --interval 1s --time-column 0
python .\scripts\run_tool.py Sampler --interval 1s --time-column timestamp
```

## Time Units

Intervals support:

- `ns`
- `us`
- `ms`
- `s`
- `min`
- `h`

Numeric time columns are treated as seconds unless `--time-unit` is provided or the header contains a unit such as `Time(ms)`.

Unit-bearing time headers are detected even when the time column is not the
first column. Supported examples include:

```text
Time(ms)
flow-time [s]
timestamp_us
Elapsed Time (min)
physical-time/hr
```

For Average, Minimum, and Maximum processing in the web UI, calculations are
performed internally in seconds, but the result time values are converted back
to the unit detected from the source header. For example, `Time(ms)` remains in
milliseconds in the downloaded CSV.

## Engineering Unit Conversion

The web UI has an optional **단위 변환** section below the processing methods.
Add one rule for each numeric column to convert. A rule contains:

1. Column
2. Data type (airflow, temperature, humidity, or time)
3. Current unit
4. Target unit

Multiple rules can be applied in the same download. Select **Unit Convert** to
convert every row without reducing the dataset, or keep Sampling/Average/
Minimum/Maximum selected to apply the same rules to that processed result.

Supported conversions:

| Data type | Units | Conversion basis |
|---|---|---|
| Airflow | CMS, CMM, CMH | `1 CMS = 60 CMM = 3600 CMH` |
| Temperature | K, degC | `degC = K - 273.15` |
| Humidity | decimal (0-1), % | `% = decimal x 100` |
| Time | ns, us, ms, sec, min, hr | converted through seconds |

Common unit-bearing headers are detected automatically, including:

```text
Airflow(CMS)
Volume Flow [m3/min]
Temperature[K]
Outlet Temp_degC
RH(%)
Time(sec)
Elapsed Time/hr
```

The user can override every suggestion. When a conversion is applied, the
output header is changed as well; for example:

```text
Airflow(CMS)      -> Airflow(CMH)
Temperature[K]    -> Temperature[degC]
RH                 -> RH (%)
Time/sec           -> Time/min
```

Selected conversion columns must contain numeric values. Empty cells remain
empty, while non-numeric text in a selected column stops processing and reports
the affected row. Humidity values are scaled but not clipped, so the source
range remains the user's responsibility.

For aggregation, Sampler first calculates Average, Minimum, or Maximum in the
source unit and then converts the result. The processing interval is still
interpreted independently; for example, a time output can be converted to
minutes while the interval is entered as `30s` or `1min`.

### Command-line conversion

Use `--convert COLUMN:FROM:TO`. `COLUMN` can be a zero-based index or a header
name without its unit suffix. Repeat the option for multiple columns.

Convert all rows without sampling:

```powershell
python main.py --input .\input\engineering.csv --convert-only `
  --convert Time:sec:min `
  --convert Airflow:CMS:CMH `
  --convert Temperature:K:degC `
  --convert RH:decimal:percent
```

Sample every 60 seconds and convert selected columns at the same time:

```powershell
python main.py --input .\input\engineering.csv --interval 60s `
  --convert Airflow:CMS:CMM `
  --convert Temperature:K:degC
```

The corresponding output names are:

```text
data.csv + --convert-only              -> data_converted.csv
data.csv + --interval 60s + conversion -> data_60s_converted.csv
```

CLI unit aliases include `m3/s`, `m3/min`, `m3/h`, `kelvin`, `celsius`,
`fraction`, `percent`, `sec`, `min`, and `hr`. Using the word `percent` rather
than `%` is recommended in batch files.

## Recursive Input Folders

With `--recursive`, Sampler reproduces the input subfolder structure below the
output folder. This prevents files with the same name in different CAE case
folders from overwriting each other.

```text
input/caseA/result.csv  -> output/caseA/result_1s.csv
input/caseB/result.csv  -> output/caseB/result_1s.csv
```

## Regression Tests

Run the bundled regression checks on Windows:

```powershell
.\run_regression_tests.bat
```

Or run them directly with Python:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Sampling Modes

- `after`: select the first row at or after each target time. This is the default.
- `nearest`: select the row closest to each target time.

Input time values must be sorted in ascending order.
