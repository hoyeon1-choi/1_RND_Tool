const state = {
  file: null,
  pastedText: "",
  inputMode: "file",
  preview: null,
  dataType: "transient",
  sourceRevision: 0,
  conversions: [],
  nextConversionId: 1
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const fileInput = $("#fileInput");
const dropzone = $("#dropzone");
const pasteInput = $("#pasteInput");
const previewButton = $("#previewButton");
const downloadButton = $("#downloadButton");
const statusBox = $("#status");
const addConversionButton = $("#addConversionButton");

function sourceReady() {
  return state.inputMode === "file" ? Boolean(state.file) : Boolean(state.pastedText.trim());
}

function updatePreviewButton() {
  previewButton.disabled = !sourceReady();
}

function setStatus(message, type = "loading") {
  statusBox.textContent = message;
  statusBox.className = `status ${type}`;
  if (type === "success") {
    setTimeout(() => {
      if (statusBox.textContent === message && statusBox.classList.contains("success")) {
        statusBox.classList.add("hidden");
      }
    }, 2800);
  }
}

function resetConversions() {
  state.conversions = [];
  state.nextConversionId = 1;
  const rules = $("#conversionRules");
  if (rules) rules.innerHTML = "";
  const empty = $("#conversionEmpty");
  if (empty) empty.classList.remove("hidden");
}

function invalidatePreview() {
  state.preview = null;
  state.sourceRevision += 1;
  resetConversions();
  $("#previewPanel").classList.add("hidden");
  $("#processPanel").classList.add("hidden");
  $("#xColumn").innerHTML = "";
  $("#yColumn").innerHTML = "";
  $("#rowCount").textContent = "0 rows";
  $("#unitBadge").textContent = "unit";
  $("#previewNote").textContent = "";
  $("#chartEmpty").classList.add("hidden");
  const canvas = $("#chart");
  const context = canvas.getContext("2d");
  if (context) context.clearRect(0, 0, canvas.width, canvas.height);
  downloadButton.disabled = true;
  statusBox.className = "status hidden";
}

function setFile(file) {
  state.file = file || null;
  invalidatePreview();
  if (!file) {
    $("#fileTitle").textContent = "파일을 끌어 놓거나 클릭하세요";
    $("#fileHelp").textContent = "CSV, DAT, OUT, TXT · 최대 100 MB";
    updatePreviewButton();
    return;
  }
  $("#fileTitle").textContent = file.name;
  $("#fileHelp").textContent = `${(file.size / 1024).toLocaleString(undefined, {maximumFractionDigits: 1})} KB`;
  updatePreviewButton();
}

fileInput.addEventListener("change", () => setFile(fileInput.files[0]));
["dragenter", "dragover"].forEach((event) => dropzone.addEventListener(event, (e) => {
  e.preventDefault();
  dropzone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((event) => dropzone.addEventListener(event, (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragging");
}));
dropzone.addEventListener("drop", (event) => setFile(event.dataTransfer.files[0]));

$$('.input-tab').forEach((button) => button.addEventListener("click", () => {
  const nextMode = button.dataset.inputMode;
  if (state.inputMode !== nextMode) {
    state.inputMode = nextMode;
    invalidatePreview();
  }
  $$(".input-tab").forEach((tab) => {
    const active = tab === button;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  dropzone.classList.toggle("hidden", state.inputMode !== "file");
  $("#pastePane").classList.toggle("hidden", state.inputMode !== "paste");
  updatePreviewButton();
}));

pasteInput.addEventListener("input", () => {
  state.pastedText = pasteInput.value;
  invalidatePreview();
  const bytes = new TextEncoder().encode(state.pastedText).length;
  $("#pasteSize").textContent = `${(bytes / 1024).toLocaleString(undefined, {maximumFractionDigits: 1})} KB / 5 MB`;
  $("#pasteSize").classList.toggle("over-limit", bytes > 5 * 1024 * 1024);
  updatePreviewButton();
});

$$("input[name=\"dataType\"]").forEach((input) => input.addEventListener("change", () => {
  state.dataType = input.value;
  invalidatePreview();
  $$(".type-card").forEach((card) => card.classList.toggle("selected", card.contains(input)));
  $("#interval").value = state.dataType === "transient" ? "1s" : "100";
  $("#interval").placeholder = state.dataType === "transient" ? "예: 100ms, 1s" : "예: 100 iterations";
  updatePreviewButton();
  if (sourceReady()) loadPreview();
}));

function requestOptions(extra = {}) {
  const fields = { data_type: state.dataType, ...extra };
  if (state.inputMode === "paste") {
    return {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...fields, text: state.pastedText, filename: "pasted_data.txt" })
    };
  }
  const form = new FormData();
  form.append("file", state.file);
  Object.entries(fields).forEach(([key, value]) => form.append(key, value));
  return { method: "POST", body: form };
}

async function errorMessage(response) {
  try {
    return (await response.json()).error || `HTTP ${response.status}`;
  } catch {
    return `요청에 실패했습니다. (HTTP ${response.status})`;
  }
}

async function loadPreview() {
  if (!sourceReady()) return;
  const requestedRevision = state.sourceRevision;
  setStatus("데이터를 분석하고 있습니다…");
  previewButton.disabled = true;
  try {
    const response = await fetch("/api/preview", requestOptions());
    if (!response.ok) throw new Error(await errorMessage(response));
    const preview = await response.json();
    if (requestedRevision !== state.sourceRevision) return;
    state.preview = preview;
    resetConversions();
    renderPreview();
    $("#previewPanel").classList.remove("hidden");
    $("#processPanel").classList.remove("hidden");
    downloadButton.disabled = false;
    setStatus("데이터를 불러왔습니다.", "success");
  } catch (error) {
    if (requestedRevision === state.sourceRevision) setStatus(error.message, "error");
  } finally {
    updatePreviewButton();
  }
}
previewButton.addEventListener("click", loadPreview);

function fillSelect(select, indices, selected) {
  select.innerHTML = "";
  indices.forEach((index) => {
    const option = document.createElement("option");
    option.value = index;
    option.textContent = state.preview.columns[index];
    option.selected = index === selected;
    select.append(option);
  });
}

function renderPreview() {
  const p = state.preview;
  fillSelect($("#xColumn"), p.numericColumns, p.xIndex);
  fillSelect($("#yColumn"), p.numericColumns, p.yIndex);
  $("#rowCount").textContent = `${p.rowCount.toLocaleString()} rows`;
  $("#unitBadge").textContent = p.detectedUnit;
  $("#previewNote").textContent = p.previewCount < p.rowCount
    ? `그래프 성능을 위해 전체 ${p.rowCount.toLocaleString()}개 중 ${p.previewCount.toLocaleString()}개 점을 표시합니다. 후처리는 전체 데이터에 적용됩니다.`
    : `${p.previewCount.toLocaleString()}개 데이터 점을 표시합니다.`;
  renderConversionRules();
  drawChart();
}

function quantitySpec(quantityId) {
  return state.preview?.unitCatalog?.find((item) => item.id === quantityId) || null;
}

function unitSpec(quantityId, unitId) {
  return quantitySpec(quantityId)?.units.find((item) => item.id === unitId) || null;
}

function columnHint(columnIndex) {
  return state.preview?.columnUnitHints?.[columnIndex] || null;
}

function preferredTarget(quantity, sourceUnit) {
  const preferences = {
    airflow: { cms: "cmh", cmm: "cmh", cmh: "cms" },
    temperature: { k: "degc", degc: "k" },
    humidity: { fraction: "percent", percent: "fraction" },
    time: { ns: "s", us: "s", ms: "s", s: "min", min: "h", h: "min" }
  };
  const units = quantitySpec(quantity)?.units || [];
  const preferred = preferences[quantity]?.[sourceUnit];
  if (preferred && units.some((unit) => unit.id === preferred)) return preferred;
  return units.find((unit) => unit.id !== sourceUnit)?.id || sourceUnit || "";
}

function firstUnusedNumericColumn() {
  if (!state.preview) return null;
  const used = new Set(state.conversions.map((rule) => rule.columnIndex));
  const convertible = state.preview.convertibleColumns || state.preview.numericColumns;
  const preferred = Number($("#yColumn").value);
  if (convertible.includes(preferred) && !used.has(preferred)) return preferred;
  return convertible.find((index) => !used.has(index)) ?? null;
}

function createConversionRule(columnIndex) {
  const hint = columnHint(columnIndex);
  const quantity = hint?.quantity || "";
  const unitOptions = quantitySpec(quantity)?.units || [];
  const source = hint?.unit && unitOptions.some((unit) => unit.id === hint.unit)
    ? hint.unit
    : "";
  return {
    id: state.nextConversionId++,
    columnIndex,
    quantity,
    fromUnit: source,
    toUnit: preferredTarget(quantity, source)
  };
}

function addConversionRule() {
  if (!state.preview) return;
  const columnIndex = firstUnusedNumericColumn();
  if (columnIndex === null) {
    setStatus("추가로 변환할 수 있는 숫자 열이 없습니다.", "error");
    return;
  }
  state.conversions.push(createConversionRule(columnIndex));
  renderConversionRules();
  drawChart();
}
addConversionButton.addEventListener("click", addConversionRule);

function appendOption(select, value, label, selected = false) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  option.selected = selected;
  select.append(option);
}

function populateUnitSelect(select, quantity, selected, placeholder) {
  select.innerHTML = "";
  const specification = quantitySpec(quantity);
  if (!specification) {
    appendOption(select, "", placeholder, true);
    select.disabled = true;
    return;
  }
  select.disabled = false;
  if (!selected) appendOption(select, "", placeholder, true);
  specification.units.forEach((unit) => appendOption(select, unit.id, unit.label, unit.id === selected));
}

function conversionFormula(quantity, fromUnit, toUnit) {
  if (!quantity || !fromUnit || !toUnit || fromUnit === toUnit) return "변환 단위를 확인해 주세요.";
  const source = unitSpec(quantity, fromUnit);
  const target = unitSpec(quantity, toUnit);
  if (!source || !target) return "";
  const multiplier = source.scale / target.scale;
  const intercept = (source.offset - target.offset) / target.scale;
  if (Math.abs(multiplier - 1) < 1e-12 && Math.abs(intercept) > 1e-12) {
    const operator = intercept > 0 ? "+" : "−";
    return `값 ${operator} ${Number(Math.abs(intercept).toPrecision(8)).toLocaleString()}`;
  }
  if (Math.abs(intercept) < 1e-12) {
    const rounded = Math.round(multiplier);
    if (Math.abs(multiplier - rounded) < 1e-12) return `값 × ${rounded.toLocaleString()}`;
    const reciprocal = Math.round(1 / multiplier);
    if (reciprocal > 0 && Math.abs(multiplier - 1 / reciprocal) < 1e-12) return `값 ÷ ${reciprocal.toLocaleString()}`;
    return `값 × ${Number(multiplier.toPrecision(8)).toLocaleString()}`;
  }
  const sign = intercept >= 0 ? "+" : "−";
  return `값 × ${Number(multiplier.toPrecision(8)).toLocaleString()} ${sign} ${Number(Math.abs(intercept).toPrecision(8)).toLocaleString()}`;
}

function renderConversionRules() {
  const container = $("#conversionRules");
  const empty = $("#conversionEmpty");
  container.innerHTML = "";
  empty.classList.toggle("hidden", state.conversions.length > 0);
  if (!state.preview) return;

  state.conversions.forEach((rule) => {
    const row = document.createElement("div");
    row.className = "conversion-rule";
    row.dataset.ruleId = String(rule.id);

    const columnLabel = document.createElement("label");
    columnLabel.append("변환 열");
    const columnSelect = document.createElement("select");
    (state.preview.convertibleColumns || state.preview.numericColumns).forEach((index) => {
      appendOption(columnSelect, String(index), state.preview.columns[index], index === rule.columnIndex);
    });
    columnLabel.append(columnSelect);

    const quantityLabel = document.createElement("label");
    quantityLabel.append("데이터 종류");
    const quantitySelect = document.createElement("select");
    appendOption(quantitySelect, "", "종류 선택", !rule.quantity);
    state.preview.unitCatalog.forEach((quantity) => {
      appendOption(quantitySelect, quantity.id, quantity.label, quantity.id === rule.quantity);
    });
    quantityLabel.append(quantitySelect);

    const fromLabel = document.createElement("label");
    fromLabel.append("현재 단위");
    const fromSelect = document.createElement("select");
    populateUnitSelect(fromSelect, rule.quantity, rule.fromUnit, "현재 단위");
    fromLabel.append(fromSelect);

    const arrow = document.createElement("div");
    arrow.className = "conversion-arrow";
    arrow.textContent = "→";

    const toLabel = document.createElement("label");
    toLabel.append("변환 단위");
    const toSelect = document.createElement("select");
    populateUnitSelect(toSelect, rule.quantity, rule.toUnit, "변환 단위");
    toLabel.append(toSelect);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-conversion";
    remove.title = "변환 규칙 삭제";
    remove.setAttribute("aria-label", "변환 규칙 삭제");
    remove.textContent = "×";

    const formula = document.createElement("div");
    formula.className = "conversion-formula";
    const fromName = unitSpec(rule.quantity, rule.fromUnit)?.label || "?";
    const toName = unitSpec(rule.quantity, rule.toUnit)?.label || "?";
    const hint = columnHint(rule.columnIndex);
    const detected = hint?.quantity === rule.quantity && hint?.unit === rule.fromUnit
      ? " · 헤더에서 자동 감지"
      : "";
    formula.innerHTML = `<strong>${fromName} → ${toName}</strong> · ${conversionFormula(rule.quantity, rule.fromUnit, rule.toUnit)}${detected}`;

    columnSelect.addEventListener("change", () => {
      const nextColumn = Number(columnSelect.value);
      if (state.conversions.some((item) => item.id !== rule.id && item.columnIndex === nextColumn)) {
        setStatus("같은 열에는 단위변환 규칙을 하나만 설정할 수 있습니다.", "error");
        renderConversionRules();
        return;
      }
      rule.columnIndex = nextColumn;
      const hintForColumn = columnHint(nextColumn);
      rule.quantity = hintForColumn?.quantity || "";
      const available = quantitySpec(rule.quantity)?.units || [];
      rule.fromUnit = hintForColumn?.unit && available.some((unit) => unit.id === hintForColumn.unit)
        ? hintForColumn.unit
        : "";
      rule.toUnit = rule.fromUnit ? preferredTarget(rule.quantity, rule.fromUnit) : "";
      renderConversionRules();
      drawChart();
    });

    quantitySelect.addEventListener("change", () => {
      rule.quantity = quantitySelect.value;
      const available = quantitySpec(rule.quantity)?.units || [];
      const hintForColumn = columnHint(rule.columnIndex);
      rule.fromUnit = hintForColumn?.quantity === rule.quantity && available.some((unit) => unit.id === hintForColumn.unit)
        ? hintForColumn.unit
        : "";
      rule.toUnit = rule.fromUnit ? preferredTarget(rule.quantity, rule.fromUnit) : "";
      renderConversionRules();
      drawChart();
    });

    fromSelect.addEventListener("change", () => {
      rule.fromUnit = fromSelect.value;
      if (!rule.toUnit || rule.toUnit === rule.fromUnit) {
        rule.toUnit = preferredTarget(rule.quantity, rule.fromUnit);
      }
      renderConversionRules();
      drawChart();
    });

    toSelect.addEventListener("change", () => {
      rule.toUnit = toSelect.value;
      renderConversionRules();
      drawChart();
    });

    remove.addEventListener("click", () => {
      state.conversions = state.conversions.filter((item) => item.id !== rule.id);
      renderConversionRules();
      drawChart();
    });

    row.append(columnLabel, quantityLabel, fromLabel, arrow, toLabel, remove, formula);
    container.append(row);
  });
}

function validatedConversionRules() {
  const used = new Set();
  return state.conversions.map((rule) => {
    if (!rule.quantity || !rule.fromUnit || !rule.toUnit) {
      throw new Error("모든 단위변환 규칙에서 데이터 종류와 단위를 선택해 주세요.");
    }
    if (rule.fromUnit === rule.toUnit) {
      throw new Error(`${state.preview.columns[rule.columnIndex]} 열의 현재 단위와 변환 단위가 같습니다.`);
    }
    if (used.has(rule.columnIndex)) {
      throw new Error("같은 열에는 단위변환 규칙을 하나만 설정할 수 있습니다.");
    }
    used.add(rule.columnIndex);
    return {
      columnIndex: rule.columnIndex,
      quantity: rule.quantity,
      fromUnit: rule.fromUnit,
      toUnit: rule.toUnit
    };
  });
}

function convertPreviewValue(columnIndex, value) {
  if (!Number.isFinite(value)) return value;
  const rule = state.conversions.find((item) => item.columnIndex === columnIndex);
  if (!rule || !rule.quantity || !rule.fromUnit || !rule.toUnit || rule.fromUnit === rule.toUnit) return value;
  const source = unitSpec(rule.quantity, rule.fromUnit);
  const target = unitSpec(rule.quantity, rule.toUnit);
  if (!source || !target) return value;
  const baseValue = value * source.scale + source.offset;
  return (baseValue - target.offset) / target.scale;
}

function displayColumnName(columnIndex) {
  const original = state.preview.columns[columnIndex];
  const rule = state.conversions.find((item) => item.columnIndex === columnIndex);
  const target = unitSpec(rule?.quantity, rule?.toUnit)?.header;
  return target ? `${original} → ${target}` : original;
}

function compact(value) {
  const absolute = Math.abs(value);
  if ((absolute >= 1e5) || (absolute > 0 && absolute < 1e-3)) return value.toExponential(2);
  return Number(value.toFixed(4)).toLocaleString();
}

function drawChart() {
  if (!state.preview) return;
  const canvas = $("#chart");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  const xIndex = Number($("#xColumn").value);
  const yIndex = Number($("#yColumn").value);
  const points = state.preview.rows
    .map((row) => [convertPreviewValue(xIndex, row[xIndex]), convertPreviewValue(yIndex, row[yIndex])])
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  $("#chartEmpty").classList.toggle("hidden", points.length > 1);
  if (points.length < 2) return;
  let [xMin, xMax] = [Math.min(...points.map((p) => p[0])), Math.max(...points.map((p) => p[0]))];
  let [yMin, yMax] = [Math.min(...points.map((p) => p[1])), Math.max(...points.map((p) => p[1]))];
  if (xMin === xMax) { xMin -= 0.5; xMax += 0.5; }
  if (yMin === yMax) { yMin -= 0.5; yMax += 0.5; }
  const yPad = (yMax - yMin) * 0.08;
  yMin -= yPad;
  yMax += yPad;
  const pad = { left: 70, right: 22, top: 20, bottom: 48 };
  const px = (x) => pad.left + (x - xMin) / (xMax - xMin) * (width - pad.left - pad.right);
  const py = (y) => height - pad.bottom - (y - yMin) / (yMax - yMin) * (height - pad.top - pad.bottom);
  ctx.font = "11px Segoe UI";
  ctx.fillStyle = "#718078";
  ctx.strokeStyle = "#e3e9e5";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i += 1) {
    const y = pad.top + i / 5 * (height - pad.top - pad.bottom);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    const value = yMax - i / 5 * (yMax - yMin);
    ctx.textAlign = "right";
    ctx.fillText(compact(value), pad.left - 10, y + 4);
  }
  for (let i = 0; i <= 5; i += 1) {
    const x = pad.left + i / 5 * (width - pad.left - pad.right);
    const value = xMin + i / 5 * (xMax - xMin);
    ctx.textAlign = "center";
    ctx.fillText(compact(value), x, height - 20);
  }
  ctx.strokeStyle = "#16845c";
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.beginPath();
  points.forEach(([x, y], index) => index ? ctx.lineTo(px(x), py(y)) : ctx.moveTo(px(x), py(y)));
  ctx.stroke();
  ctx.fillStyle = "#4f6259";
  ctx.textAlign = "center";
  ctx.fillText(displayColumnName(xIndex), (pad.left + width - pad.right) / 2, height - 3);
  ctx.save();
  ctx.translate(13, (pad.top + height - pad.bottom) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText(displayColumnName(yIndex), 0, 0);
  ctx.restore();

  const xRule = state.conversions.find((rule) => rule.columnIndex === xIndex);
  $("#unitBadge").textContent = unitSpec(xRule?.quantity, xRule?.toUnit)?.header || state.preview.detectedUnit;
}
$("#xColumn").addEventListener("change", drawChart);
$("#yColumn").addEventListener("change", drawChart);
window.addEventListener("resize", () => requestAnimationFrame(drawChart));

const help = {
  sampling: "첫 행부터 지정한 간격마다 데이터를 선택합니다. 단위변환 규칙이 있으면 선택된 행에도 함께 적용됩니다.",
  average: "각 구간의 모든 숫자 열 평균을 계산한 뒤 선택한 열의 단위를 변환하여 CSV로 저장합니다.",
  min: "각 구간의 모든 숫자 열 최솟값을 계산한 뒤 선택한 열의 단위를 변환하여 CSV로 저장합니다.",
  max: "각 구간의 모든 숫자 열 최댓값을 계산한 뒤 선택한 열의 단위를 변환하여 CSV로 저장합니다.",
  convert: "행을 줄이거나 집계하지 않고 전체 데이터에 단위변환만 적용합니다. 변환 규칙이 하나 이상 필요합니다."
};
function updateMethod(method) {
  $$(".method-card").forEach((card) => card.classList.toggle("selected", card.querySelector("input").value === method));
  $("#intervalField").classList.toggle("hidden", method === "convert");
  $("#modeField").classList.toggle("hidden", method !== "sampling");
  $("#processPanel").classList.toggle("convert-mode", method === "convert");
  $("#methodHelp").textContent = help[method];
  downloadButton.innerHTML = method === "convert"
    ? "변환 데이터 다운로드 <span>↓</span>"
    : "처리 데이터 다운로드 <span>↓</span>";
}
$$("input[name=\"method\"]").forEach((input) => input.addEventListener("change", () => updateMethod(input.value)));

updateMethod($("input[name=\"method\"]:checked").value);

downloadButton.addEventListener("click", async () => {
  if (!state.preview) {
    setStatus("변경된 데이터를 먼저 다시 불러와 주세요.", "error");
    return;
  }
  const method = $("input[name=\"method\"]:checked").value;
  const interval = $("#interval").value.trim();
  if (method !== "convert" && !interval) {
    setStatus("처리 간격을 입력해 주세요.", "error");
    return;
  }

  let conversions;
  try {
    conversions = validatedConversionRules();
    if (method === "convert" && conversions.length === 0) {
      throw new Error("Unit Convert를 사용하려면 변환 규칙을 하나 이상 추가해 주세요.");
    }
  } catch (error) {
    setStatus(error.message, "error");
    return;
  }

  const requestedRevision = state.sourceRevision;
  downloadButton.disabled = true;
  setStatus("전체 데이터를 처리하고 있습니다…");
  try {
    const response = await fetch("/api/process", requestOptions({
      method,
      interval,
      mode: $("#mode").value,
      x_index: $("#xColumn").value,
      conversions: JSON.stringify(conversions)
    }));
    if (!response.ok) throw new Error(await errorMessage(response));
    if (requestedRevision !== state.sourceRevision) return;
    const blob = await response.blob();
    if (requestedRevision !== state.sourceRevision) return;
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] || "sampler_result.csv";
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    setStatus("후처리 파일을 다운로드했습니다.", "success");
  } catch (error) {
    if (requestedRevision === state.sourceRevision) setStatus(error.message, "error");
  } finally {
    downloadButton.disabled = !state.preview;
  }
});
