# Changelog

## 1.2.0 - 2026-09-03

### Added

1. **Multi-column engineering unit conversion**
   - Airflow: CMS, CMM, and CMH.
   - Temperature: K and degC.
   - Humidity: decimal fraction and percent.
   - Time: ns, us, ms, sec, min, and hr.

2. **Conversion-only and combined processing**
   - The new `Unit Convert` web method converts every row without sampling.
   - Conversion rules can also be applied to Sampling, Average, Minimum, and
     Maximum results.
   - Multiple columns can be converted in one request.

3. **Unit-aware web workflow**
   - Source units are suggested from common header styles.
   - The graph preview immediately reflects configured conversions.
   - Output header units are updated automatically.
   - Duplicate-column and non-numeric-value validation was added.

4. **Command-line conversion**
   - Repeated `--convert COLUMN:FROM:TO` rules are supported.
   - `--convert-only` processes all rows without requiring a sampling interval.
   - Unit-bearing headers can be referenced by their base name, such as `Time`
     for `Time(sec)`.

### Verification

- Added 13 unit-conversion regression tests, bringing the bundled total to 21.
- Verified conversion math, header detection, header replacement, web preview
  metadata, conversion-only processing, conversion combined with sampling and
  aggregation, CLI processing, and non-numeric input rejection.

## 1.1.0 - 2026-09-03

### Fixed

1. **Aggregation time-unit preservation**
   - Average, Minimum, and Maximum results now convert internally stored seconds
     back to the numeric unit detected from the source time header.
   - Example: `Time(ms)` outputs `0, 100, 200`, not `0, 0.1, 0.2`.

2. **Automatic detection of time columns containing units**
   - Recognizes header styles such as `Time(ms)`, `flow-time [s]`,
     `timestamp_us`, `Elapsed Time (min)`, and `physical-time/hr`.
   - Detection works when the time column is not the first column.

3. **Recursive output overwrite prevention**
   - `--recursive` now retains each input file's relative parent directory under
     the output root.
   - Identically named result files in different CAE case folders no longer
     overwrite one another.

4. **Web preview state reset**
   - Changing the uploaded file, pasted text, input mode, or data type invalidates
     the previous preview and axis selections.
   - Processing remains disabled until the changed data is loaded again.
   - Revision guards prevent delayed responses from restoring stale state.

### Additional safeguards

- Invalid numeric time-column indices now return a clear `ValueError` instead of
  an unhandled `IndexError`.
- Eight standard-library regression tests cover the four fixes and the existing
  Fluent sample behavior.
