import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
// Imports
import * as echarts from 'echarts';
import { SpreadsheetProvider, SpreadsheetGrid, FormulaBar, FormattingToolbar, useSpreadsheet, keyOf, evaluateFormula, } from 'opensheets';
// Imports
import { exportToExcel } from 'opensheets/excel';
import 'opensheets/styles/tokens.css';
import 'opensheets/styles.css';
// Value: page size
const PAGE_SIZE = 500;
// Value: import preview rows
const IMPORT_PREVIEW_ROWS = 1000;
// Value: extra empty rows
const EXTRA_EMPTY_ROWS = 200;
// Value: extra empty columns
const EXTRA_EMPTY_COLUMNS = 50;
// Value: default row height
const DEFAULT_ROW_HEIGHT = 22;
// Component or function: make initial data
function makeInitialData(rows, columns) {
    // Value: data
    const data = new Map();
    if (!rows.length)
        return data;
    // Value: headers
    const headers = columns?.length
        ? columns.map(column => column.field)
        : Object.keys(rows[0]);
    headers.forEach((header, col) => data.set(keyOf(0, col), { value: header }));
    rows.forEach((row, rowIndex) => {
        headers.forEach((header, col) => {
            const value = row[header];
            if (value !== undefined && value !== null && value !== '') {
                data.set(keyOf(rowIndex + 1, col), { value });
            }
        });
    });
    return data;
}
// Component or function: read rows from state
function readRowsFromState(state) {
    // Value: data
    const data = state?.data;
    if (!data || typeof data.get !== 'function')
        return [];
    // Value: max rows
    const maxRows = Math.min(Math.max(Number(state.maxRows) || 1000, 1), 1000);
    // Value: max cols
    const maxCols = Math.min(Math.max(Number(state.maxCols) || 100, 1), 100);
    // Value: matrix
    const matrix = [];
    for (let row = 0; row < maxRows; row++) {
        const values = [];
        for (let col = 0; col < maxCols; col++) {
            const cell = data.get(keyOf(row, col));
            if (cell?.formula && String(cell.formula).startsWith('=')) {
                values.push(evaluateFormula(cell.formula, (sourceRow, sourceCol) => data.get(keyOf(sourceRow, sourceCol))));
            }
            else {
                values.push(cell?.value ?? null);
            }
        }
        matrix.push(values);
    }
    // Value: header row
    const headerRow = matrix[0] || [];
    // Value: last header col
    const lastHeaderCol = headerRow.reduce((last, value, index) => value !== null && value !== undefined && String(value).trim() !== '' ? index : last, -1);
    if (lastHeaderCol < 0)
        return [];
    // Value: headers
    const headers = [];
    // Value: used
    const used = new Set();
    for (let col = 0; col <= lastHeaderCol; col++) {
        const raw = String(headerRow[col] ?? '').trim();
        let name = raw || `Column${col + 1}`;
        if (used.has(name)) {
            let suffix = 2;
            while (used.has(`${name}_${suffix}`))
                suffix++;
            name = `${name}_${suffix}`;
        }
        used.add(name);
        headers.push(name);
    }
    // Value: rows
    const rows = [];
    for (let rowIndex = 1; rowIndex < matrix.length; rowIndex++) {
        const values = matrix[rowIndex].slice(0, headers.length);
        if (values.every(value => value === null || value === undefined || String(value).trim() === ''))
            continue;
        const row = {};
        headers.forEach((header, col) => { row[header] = values[col] ?? null; });
        rows.push(row);
    }
    return rows;
}
// Component or function: load page state
function loadPageState(rows, columns, dispatch) {
    // Value: data
    const data = makeInitialData(rows, columns);
    // Value: col count
    const colCount = columns.length || (rows[0] ? Object.keys(rows[0]).length : 1);
    // The first spreadsheet row contains headers; data rows follow it.
    const rowCount = Math.max(rows.length + 1, 1);
    dispatch({
        type: 'LOAD_STATE',
        payload: {
            data,
            maxRows: rowCount,
            maxCols: Math.max(colCount, 1),
            selection: { ranges: [], active: null },
            editing: null,
            formulaInput: '',
            readOnly: false,
            rowHeights: Array(rowCount).fill(22),
            colWidths: Array(Math.max(colCount, 1)).fill(140),
            validation: new Map(),
        },
    });
}
// Component or function: make sparse row heights
function makeSparseRowHeights(count) {
    // OpenSheets virtualizes rows, so we do not need to materialize 10M height
    // entries. Keep a sparse array and let the grid use its default row height
    // for unassigned rows.
    const heights = new Array(Math.max(1, count));
    // Value: seeded
    const seeded = Math.min(2000, heights.length);
    for (let index = 0; index < seeded; index++)
        heights[index] = DEFAULT_ROW_HEIGHT;
    return heights;
}
// Component or function: data rows to map
function dataRowsToMap(rows, columns, spreadsheetStartRow, existingData) {
    // Value: data
    const data = existingData ? new Map(existingData) : new Map();
    // Function: fields
    const fields = columns.map(column => column.field);
    rows.forEach((row, rowOffset) => {
        const spreadsheetRow = spreadsheetStartRow + rowOffset;
        fields.forEach((field, col) => {
            const value = row[field];
            const cellKey = keyOf(spreadsheetRow, col);
            if (value !== undefined && value !== null && value !== '') {
                data.set(cellKey, { value });
            }
            else {
                data.delete(cellKey);
            }
        });
    });
    return data;
}
// Component or function: cleaning blank
function cleaningBlank(value) {
    return value === null || value === undefined || String(value).trim() === '';
}
// Component or function: cleaning numeric
function cleaningNumeric(value) {
    if (typeof value === 'number')
        return Number.isFinite(value) ? value : null;
    if (cleaningBlank(value))
        return null;
    // Value: number
    const number = Number(String(value)
        .replace(/,/g, '')
        .replace(/[₹$€£%]/g, '')
        .trim());
    return Number.isFinite(number) ? number : null;
}
// Component or function: cleaning title case
function cleaningTitleCase(value) {
    if (typeof value !== 'string')
        return value;
    return value
        .trim()
        .toLowerCase()
        .replace(/\b([a-z])/g, match => match.toUpperCase());
}
// Component or function: cleaning date
function cleaningDate(value) {
    if (cleaningBlank(value))
        return value;
    // Value: text
    const text = String(value).trim();
    // Value: direct
    const direct = new Date(text);
    if (Number.isNaN(direct.getTime())) {
        const match = text.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})/);
        if (match) {
            const day = Number(match[1]);
            const month = Number(match[2]) - 1;
            let year = Number(match[3]);
            if (year < 100)
                year += year >= 70 ? 1900 : 2000;
            const parsed = new Date(year, month, day);
            if (!Number.isNaN(parsed.getTime())) {
                return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, '0')}-${String(parsed.getDate()).padStart(2, '0')}`;
            }
        }
        return value;
    }
    return `${direct.getFullYear()}-${String(direct.getMonth() + 1).padStart(2, '0')}-${String(direct.getDate()).padStart(2, '0')}`;
}
// Component or function: cleaning headers
function cleaningHeaders(state) {
    // Value: data
    const data = state?.data;
    if (!data || typeof data.get !== 'function')
        return [];
    // Value: max cols
    const maxCols = Math.min(Math.max(Number(state?.maxCols) || 0, 0), 100);
    // Value: headers
    const headers = [];
    // Value: seen
    const seen = new Set();
    for (let col = 0; col < maxCols; col++) {
        const raw = String(data.get(keyOf(0, col))?.value ?? '').trim();
        if (!raw)
            continue;
        let name = raw;
        let suffix = 2;
        while (seen.has(name)) {
            name = `${raw}_${suffix}`;
            suffix += 1;
        }
        seen.add(name);
        headers.push(name);
    }
    return headers;
}
// Component or function: cleaning clone data
function cleaningCloneData(state) {
    // Value: result
    const result = new Map();
    // Value: data
    const data = state?.data;
    if (!data || typeof data.entries !== 'function')
        return result;
    for (const [key, value] of data.entries()) {
        result.set(key, value && typeof value === 'object' ? { ...value } : value);
    }
    return result;
}
// Component or function: cleaning load
function cleaningLoad(dispatch, data, rows, cols, currentState) {
    dispatch({
        type: 'LOAD_STATE',
        payload: {
            ...currentState,
            data,
            maxRows: Math.max(1, rows),
            maxCols: Math.max(1, cols),
            selection: { ranges: [], active: null },
            editing: null,
            formulaInput: '',
            readOnly: false,
            rowHeights: Array(Math.max(1, rows)).fill(22),
            colWidths: Array(Math.max(1, cols)).fill(140),
            validation: new Map(),
        },
    });
}
// Component or function: data cleaning ribbon
function DataCleaningRibbon({ state, dispatch, setMessage, selectedColumn, setSelectedColumn, onRowsChanged, }) {
    // Value: headers
    const headers = cleaningHeaders(state);
    // State: 
    const [customValue, setCustomValue] = useState('');
    // State: 
    const [openMenu, setOpenMenu] = useState(null);
    // State: 
    const [ribbonCollapsed, setRibbonCollapsed] = useState(false);
    // State: 
    const [busy, setBusy] = useState(false);
    // Run side effect when dependencies change
    useEffect(() => {
        if (!headers.includes(selectedColumn)) {
            setSelectedColumn(headers[0] || '');
        }
    }, [headers.join('|'), selectedColumn, setSelectedColumn]);
    // Value: rows
    const rows = Math.max(1, Number(state?.maxRows) || 1);
    // Value: cols
    const cols = Math.max(1, Number(state?.maxCols) || 1);
    // Function: close menu
    const closeMenu = () => setOpenMenu(null);
    // Component or function: require column
    function requireColumn() {
        if (!selectedColumn)
            throw new Error('Select a column first.');
        const index = headers.indexOf(selectedColumn);
        if (index < 0)
            throw new Error(`Column "${selectedColumn}" was not found.`);
        return index;
    }
    // Component or function: read column values
    function readColumnValues(col) {
        const values = [];
        for (let row = 1; row < rows; row++) {
            values.push(state?.data?.get?.(keyOf(row, col))?.value ?? null);
        }
        return values;
    }
    // Component or function: apply column transform
    function applyColumnTransform(transform, message) {
        const col = requireColumn();
        const data = cleaningCloneData(state);
        const values = readColumnValues(col);
        for (let row = 1; row < rows; row++) {
            const key = keyOf(row, col);
            const cell = data.get(key) || {};
            const nextValue = transform(cell.value ?? null, row - 1, values);
            data.set(key, { ...cell, value: nextValue, formula: undefined });
        }
        cleaningLoad(dispatch, data, rows, cols, state);
        setMessage(`${message} Applied to "${selectedColumn}" on the current page.`);
        closeMenu();
    }
    // Component or function: fill missing
    function fillMissing(action) {
        const col = requireColumn();
        const data = cleaningCloneData(state);
        const values = readColumnValues(col);
        const numericValues = values
            .map(cleaningNumeric)
            .filter((value) => value !== null);
        let fillValue = null;
        if (action === 'mean') {
            if (!numericValues.length)
                throw new Error('Mean requires at least one numeric value.');
            fillValue = numericValues.reduce((sum, value) => sum + value, 0) / numericValues.length;
        }
        else if (action === 'median') {
            if (!numericValues.length)
                throw new Error('Median requires at least one numeric value.');
            const sorted = [...numericValues].sort((a, b) => a - b);
            const middle = Math.floor(sorted.length / 2);
            fillValue = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
        }
        else if (action === 'mode') {
            const counts = new Map();
            values.filter(value => !cleaningBlank(value)).forEach(value => {
                const key = typeof value === 'object' ? JSON.stringify(value) : String(value);
                const entry = counts.get(key) || { value, count: 0 };
                entry.count += 1;
                counts.set(key, entry);
            });
            let best = null;
            for (const entry of counts.values()) {
                if (!best || entry.count > best.count)
                    best = entry;
            }
            if (!best)
                throw new Error('Mode requires at least one non-empty value.');
            fillValue = best.value;
        }
        else if (action === 'zero') {
            fillValue = 0;
        }
        else if (action === 'custom') {
            fillValue = customValue;
        }
        for (let row = 1; row < rows; row++) {
            const key = keyOf(row, col);
            const cell = data.get(key) || {};
            if (cleaningBlank(cell.value)) {
                let nextValue = fillValue;
                if (action === 'previous') {
                    nextValue = null;
                    for (let previous = row - 1; previous >= 1; previous--) {
                        const candidate = data.get(keyOf(previous, col))?.value;
                        if (!cleaningBlank(candidate)) {
                            nextValue = candidate;
                            break;
                        }
                    }
                }
                else if (action === 'next') {
                    nextValue = null;
                    for (let next = row + 1; next < rows; next++) {
                        const candidate = data.get(keyOf(next, col))?.value;
                        if (!cleaningBlank(candidate)) {
                            nextValue = candidate;
                            break;
                        }
                    }
                }
                if (!cleaningBlank(nextValue)) {
                    data.set(key, { ...cell, value: nextValue, formula: undefined });
                }
            }
        }
        cleaningLoad(dispatch, data, rows, cols, state);
        setMessage(`Missing values filled using ${action} in "${selectedColumn}" on the current page.`);
        closeMenu();
    }
    // Component or function: remove rows
    function removeRows(action) {
        const data = cleaningCloneData(state);
        const headerValues = [];
        for (let col = 0; col < cols; col++) {
            headerValues.push(String(data.get(keyOf(0, col))?.value ?? `Column${col + 1}`));
        }
        const sourceRows = [];
        for (let row = 1; row < rows; row++) {
            sourceRows.push(Array.from({ length: cols }, (_, col) => data.get(keyOf(row, col))?.value ?? null));
        }
        const isError = (value) => typeof value === 'string' && /^(#(REF!|DIV\/0!|N\/A|VALUE!|NAME\?|NUM!|NULL!|SPILL!|CALC!)|ERROR)/i.test(value.trim());
        const seen = new Set();
        const kept = sourceRows.filter(rowValues => {
            const blank = rowValues.every(cleaningBlank);
            if (action === 'remove-blank-rows' && blank)
                return false;
            if (action === 'remove-missing' && cleaningBlank(rowValues[requireColumn()]))
                return false;
            if (action === 'remove-errors' && rowValues.some(isError))
                return false;
            if (action === 'remove-duplicates') {
                const signature = JSON.stringify(rowValues.map(value => value ?? null));
                if (seen.has(signature))
                    return false;
                seen.add(signature);
            }
            return true;
        });
        const nextData = new Map();
        headerValues.forEach((header, col) => nextData.set(keyOf(0, col), { value: header }));
        kept.forEach((rowValues, rowIndex) => {
            rowValues.forEach((value, col) => {
                if (!cleaningBlank(value))
                    nextData.set(keyOf(rowIndex + 1, col), { value });
            });
        });
        const nextRows = kept.map(rowValues => {
            const row = {};
            headerValues.forEach((header, col) => { row[header] = rowValues[col] ?? null; });
            return row;
        });
        cleaningLoad(dispatch, nextData, Math.max(1, kept.length + 1), cols, state);
        onRowsChanged(nextRows);
        setMessage(`Removed ${sourceRows.length - kept.length} row(s) using ${action} from the current page.`);
        closeMenu();
    }
    // Component or function: run action
    function runAction(action) {
        if (busy)
            return;
        setBusy(true);
        try {
            if (action === 'mean' || action === 'median' || action === 'mode' ||
                action === 'zero' || action === 'custom' || action === 'previous' || action === 'next') {
                fillMissing(action);
                return;
            }
            if (action === 'remove-missing' || action === 'remove-duplicates' ||
                action === 'remove-blank-rows' || action === 'remove-errors') {
                removeRows(action);
                return;
            }
            if (action === 'trim') {
                applyColumnTransform(value => typeof value === 'string' ? value.trim() : value, 'Trim spaces');
            }
            else if (action === 'clean') {
                applyColumnTransform(value => typeof value === 'string' ? value.replace(/[\u0000-\u001F\u007F]/g, '') : value, 'Clean characters');
            }
            else if (action === 'upper') {
                applyColumnTransform(value => typeof value === 'string' ? value.toUpperCase() : value, 'Uppercase');
            }
            else if (action === 'lower') {
                applyColumnTransform(value => typeof value === 'string' ? value.toLowerCase() : value, 'Lowercase');
            }
            else if (action === 'proper') {
                applyColumnTransform(value => cleaningTitleCase(value), 'Proper case');
            }
            else if (action === 'text-to-number') {
                applyColumnTransform(value => cleaningNumeric(value), 'Text to number');
            }
            else if (action === 'number-to-text') {
                applyColumnTransform(value => cleaningBlank(value) ? value : String(value), 'Number to text');
            }
            else if (action === 'standardize-date') {
                applyColumnTransform(value => cleaningDate(value), 'Standardize date');
            }
            else if (action === 'remove-outliers' || action === 'cap-outliers') {
                const col = requireColumn();
                const data = cleaningCloneData(state);
                const numeric = readColumnValues(col).map(cleaningNumeric);
                const sorted = numeric.filter((value) => value !== null).sort((a, b) => a - b);
                if (sorted.length < 4)
                    throw new Error('At least 4 numeric values are required for IQR outlier handling.');
                const q1Index = (sorted.length - 1) * 0.25;
                const q3Index = (sorted.length - 1) * 0.75;
                const interpolate = (index) => {
                    const lower = Math.floor(index);
                    const upper = Math.ceil(index);
                    return lower === upper ? sorted[lower] : sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
                };
                const q1 = interpolate(q1Index);
                const q3 = interpolate(q3Index);
                const iqr = q3 - q1;
                const lower = q1 - 1.5 * iqr;
                const upper = q3 + 1.5 * iqr;
                for (let row = 1; row < rows; row++) {
                    const key = keyOf(row, col);
                    const cell = data.get(key) || {};
                    const value = cleaningNumeric(cell.value);
                    if (value === null)
                        continue;
                    if (action === 'remove-outliers' && (value < lower || value > upper)) {
                        data.set(key, { ...cell, value: null, formula: undefined });
                    }
                    else if (action === 'cap-outliers') {
                        const capped = Math.min(upper, Math.max(lower, value));
                        if (capped !== value)
                            data.set(key, { ...cell, value: capped, formula: undefined });
                    }
                }
                cleaningLoad(dispatch, data, rows, cols, state);
                setMessage(`${action === 'remove-outliers' ? 'Removed' : 'Capped'} IQR outliers in "${selectedColumn}" on the current page.`);
                closeMenu();
            }
        }
        catch (error) {
            setMessage(error instanceof Error ? `Cleaning failed: ${error.message}` : 'Cleaning failed.');
        }
        finally {
            setBusy(false);
        }
    }
    // Value: menu style
    const menuStyle = {
        position: 'absolute',
        top: '100%',
        left: 0,
        zIndex: 1000,
        minWidth: 190,
        padding: 6,
        background: 'var(--os-surface, #fff)',
        border: '1px solid var(--os-border, #ddd)',
        borderRadius: 6,
        boxShadow: '0 6px 18px rgba(0,0,0,0.15)',
    };
    // Value: item style
    const itemStyle = {
        display: 'block',
        width: '100%',
        textAlign: 'left',
        padding: '6px 8px',
        border: 0,
        background: 'transparent',
        cursor: 'pointer',
        fontSize: 12,
    };
    // Function: section
    const section = (id, title, items) => (<div style={{ position: 'relative' }}>
      <button type="button" disabled={busy || !selectedColumn} onClick={() => setOpenMenu(openMenu === id ? null : id)}>
        {title} ▾
      </button>
      {openMenu === id && (<div style={menuStyle}>
          {items.map(item => (<button key={item.action} type="button" style={itemStyle} onClick={() => runAction(item.action)}>
              {item.label}
            </button>))}
        </div>)}
    </div>);
    return (<div className="excel-cleaning-panel">
      <div className="excel-ribbon-group">
        <div className="excel-group-label">Column</div>
        <select className="excel-ribbon-select" value={selectedColumn} onChange={event => setSelectedColumn(event.target.value)} disabled={busy} title="Select the column to clean">
          <option value="">Select column…</option>
          {headers.map(header => (<option key={header} value={header}>{header}</option>))}
        </select>
      </div>

      <div className="excel-ribbon-divider"/>

      {section('missing', 'Missing Values', [
            { action: 'mean', label: 'Mean' },
            { action: 'median', label: 'Median' },
            { action: 'mode', label: 'Mode' },
            { action: 'zero', label: 'Fill 0' },
            { action: 'previous', label: 'Previous Value' },
            { action: 'next', label: 'Next Value' },
            { action: 'remove-missing', label: 'Remove Missing Rows' },
        ])}

      <div className="excel-ribbon-group excel-ribbon-custom">
        <button type="button" className="excel-ribbon-big-button" disabled={busy || !selectedColumn} onClick={() => runAction('custom')}>
          <span className="excel-ribbon-icon">✎</span>
          <span>Custom</span>
        </button>
        <input className="excel-ribbon-input" value={customValue} onChange={event => setCustomValue(event.target.value)} placeholder="Value" title="Value used by Fill Custom"/>
        <div className="excel-group-label">Fill Custom</div>
      </div>

      {section('duplicates', 'Duplicates & Rows', [
            { action: 'remove-duplicates', label: 'Remove Duplicates' },
            { action: 'remove-blank-rows', label: 'Remove Blank Rows' },
            { action: 'remove-errors', label: 'Remove Error Rows' },
        ])}

      {section('text', 'Text Cleaning', [
            { action: 'trim', label: 'Trim Spaces' },
            { action: 'clean', label: 'Clean Characters' },
            { action: 'upper', label: 'UPPERCASE' },
            { action: 'lower', label: 'lowercase' },
            { action: 'proper', label: 'Proper Case' },
        ])}

      {section('types', 'Data Types', [
            { action: 'text-to-number', label: 'Text → Number' },
            { action: 'number-to-text', label: 'Number → Text' },
            { action: 'standardize-date', label: 'Standardize Date' },
        ])}

      {section('outliers', 'Outliers', [
            { action: 'remove-outliers', label: 'Remove IQR Outliers' },
            { action: 'cap-outliers', label: 'Cap IQR Outliers' },
        ])}

      <div className="excel-cleaning-note">
        <strong>{busy ? 'Working…' : 'Ready'}</strong>
        <span>Select a column header or use the Column selector.</span>
        <span>Current page only.</span>
      </div>
    </div>);
}
// Value: excel ribbon css
const EXCEL_RIBBON_CSS = `
  .excel-shell { background: #fff; border-bottom: 1px solid #d0d7de; font-family: "Segoe UI", Arial, sans-serif; color: #242424; }
  .excel-tabs { height: 36px; display: flex; align-items: flex-end; padding: 0 14px; gap: 2px; border-bottom: 1px solid #d6d6d6; background: #fff; }
  .excel-tab { height: 36px; padding: 0 16px; border: 0; background: transparent; color: #333; font-size: 13px; cursor: pointer; position: relative; }
  .excel-tab:hover { background: #f3f3f3; }
  .excel-tab.active { color: #0b57d0; font-weight: 600; }
  .excel-tab.active::after { content: ""; position: absolute; left: 10px; right: 10px; bottom: 0; height: 3px; background: #107c41; border-radius: 3px 3px 0 0; }
  .excel-ribbon-collapse-button { margin-left: auto; width: 32px; height: 28px; align-self: center; flex: 0 0 32px; border: 1px solid #d0d0d0; border-radius: 4px; background: #fff; color: #444; font-size: 18px; line-height: 1; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: background .15s ease, border-color .15s ease, transform .15s ease; }
  .excel-ribbon-collapse-button:hover { background: #eef5ff; border-color: #9bb8e8; }
  .excel-ribbon-collapse-button:active { transform: translateY(1px); }
  .excel-ribbon { min-height: 68px; display: flex; align-items: stretch; padding: 3px 8px 0; background: #f8f9fa; overflow-x: auto; overflow-y: hidden; }
  .excel-ribbon-group { min-width: 68px; padding: 2px 7px 15px; position: relative; display: flex; align-items: center; justify-content: center; gap: 4px; }
  .excel-ribbon-group::after { content: ""; position: absolute; right: 0; top: 5px; bottom: 14px; width: 1px; background: #d8d8d8; }
  .excel-ribbon-group:last-child::after { display: none; }
  .excel-group-label { position: absolute; bottom: 1px; left: 0; right: 0; text-align: center; font-size: 10px; color: #666; white-space: nowrap; }
  .excel-ribbon-big-button { min-width: 54px; height: 48px; border: 0; background: transparent; border-radius: 4px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; cursor: pointer; color: #242424; font-size: 11px; }
  .excel-ribbon-big-button:hover:not(:disabled) { background: #e9eef7; }
  .excel-ribbon-big-button { padding: 2px 4px; }
  .excel-ribbon-big-button:disabled { opacity: .45; cursor: not-allowed; }
  .excel-ribbon-icon { font-size: 18px; line-height: 1; }
  .excel-ribbon-small-button { min-width: 90px; height: 30px; padding: 0 10px; border: 1px solid #cfcfcf; background: #fff; border-radius: 3px; cursor: pointer; font-size: 11px; }
  .excel-ribbon-small-button:hover:not(:disabled) { background: #eef5ff; border-color: #9bb8e8; }
  .excel-ribbon-small-button:disabled { opacity: .5; cursor: not-allowed; }
  .excel-ribbon-select { height: 26px; min-width: 130px; border: 1px solid #bdbdbd; background: #fff; border-radius: 3px; padding: 0 8px; font-size: 12px; }
  .excel-ribbon-input { width: 72px; height: 26px; border: 1px solid #bdbdbd; border-radius: 3px; padding: 0 7px; font-size: 11px; }
  .excel-ribbon-divider { width: 1px; background: #d8d8d8; margin: 5px 2px 14px; }
  .excel-ribbon-menu { min-width: 125px; }
  .excel-ribbon-menu-button { min-width: 105px; }
  .excel-menu { position: absolute; top: 72px; left: 6px; z-index: 5000; min-width: 190px; padding: 5px; background: #fff; border: 1px solid #cfcfcf; border-radius: 3px; box-shadow: 0 7px 20px rgba(0,0,0,.18); }
  .excel-menu-item { display: block; width: 100%; text-align: left; border: 0; background: #fff; padding: 8px 10px; font-size: 12px; cursor: pointer; }
  .excel-menu-item:hover { background: #eaf2ff; }
  .excel-menu-item:disabled { opacity: .45; cursor: not-allowed; }
  .excel-home-panel { min-height: 68px; display: flex; flex-direction: column; background: #f8f9fa; }
  .excel-home-actions { display: flex; align-items: center; gap: 2px; padding: 3px 8px; border-bottom: 1px solid #e2e2e2; }
  .excel-action-button { height: 30px; padding: 0 10px; border: 0; background: transparent; border-radius: 3px; cursor: pointer; font-size: 11px; }
  .excel-action-button:hover:not(:disabled) { background: #e9eef7; }
  .excel-action-button:disabled { opacity: .45; cursor: not-allowed; }
  .excel-action-button.primary { background: #107c41; color: #fff; }
  .excel-action-button.primary:hover:not(:disabled) { background: #0d6c39; }
  .excel-statusbar { height: 25px; display: flex; align-items: center; gap: 12px; padding: 0 12px; border-top: 1px solid #ddd; background: #f6f6f6; font-size: 11px; color: #555; }
  .excel-statusbar .status-main { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .excel-cleaning-panel { min-height: 68px; display: flex; align-items: stretch; padding: 5px 10px 0; background: #f8f9fa; overflow-x: auto; }
  .excel-cleaning-panel > .excel-cleaning-panel { min-height: 0; padding: 0; background: transparent; overflow: visible; }
  .excel-cleaning-panel .excel-ribbon-group { min-width: 76px; }
  .excel-cleaning-panel .excel-ribbon-group::after { top: 7px; bottom: 17px; }
  .excel-ribbon-custom { min-width: 116px !important; flex-wrap: wrap; align-content: center; padding-bottom: 18px !important; }
  .excel-ribbon-custom .excel-group-label { bottom: 2px; }
  .excel-cleaning-note { min-width: 130px; max-width: 180px; display: flex; flex-direction: column; justify-content: center; gap: 4px; padding: 0 12px 17px; color: #666; font-size: 10px; }
  .excel-cleaning-note strong { color: #107c41; font-size: 11px; }
  .excel-transform-panel { min-height: 68px; display: flex; align-items: stretch; padding: 5px 10px 0; background: #f8f9fa; overflow-x: auto; }
  .excel-transform-panel .excel-ribbon-group { min-width: 118px; }
  .excel-help-panel { min-height: 68px; padding: 16px 20px; background: #f8f9fa; font-size: 12px; color: #555; }
  .excel-ai-panel { min-height: 68px; display: flex; align-items: stretch; padding: 5px 10px 0; background: #f8f9fa; }
  .excel-ai-card { display: flex; align-items: center; gap: 12px; padding: 0 16px; }
  .excel-ai-card .ai-icon { font-size: 28px; }
  @media (max-width: 900px) {
    .excel-tab { padding: 0 10px; }
    .excel-ribbon, .excel-cleaning-panel, .excel-transform-panel { overflow-x: auto; }
  }
`;
// Component or function: excel ribbon
function ExcelRibbon({ activeTab, setActiveTab, state, dispatch, setMessage, selectedColumn, setSelectedColumn, selectedDataType, setSelectedDataType, columnActionBusy, loadingPage, isBackendWorkbook, syncing, showFindReplace, setShowFindReplace, handleImport, handleExport, handleSavePage, handleSyncToAI, handleReplaceAll, replaceBusy, findText, setFindText, replaceText, setReplaceText, matchCase, setMatchCase, matchWholeCell, setMatchWholeCell, runColumnAction, onRowsChanged, onOpenChartDialog, }) {
    // State: 
    const [openMenu, setOpenMenu] = useState(null);
    // State: 
    const [ribbonCollapsed, setRibbonCollapsed] = useState(false);
    // Value: tabs
    const tabs = ['File', 'Home', 'Insert', 'Data', 'Transform', 'AI Analyst', 'View', 'Help'];
    // Function: menu
    const menu = (id, title, items) => (<div className="excel-ribbon-group excel-ribbon-menu" style={{ position: 'relative' }}>
      <button type="button" className="excel-ribbon-big-button excel-ribbon-menu-button" onClick={() => setOpenMenu(openMenu === id ? null : id)}>
        <span className="excel-ribbon-icon">▾</span>
        <span>{title}</span>
      </button>
      {openMenu === id && (<div className="excel-menu">
          {items.map(item => (<button key={item.label} type="button" className="excel-menu-item" onClick={() => {
                    setOpenMenu(null);
                    item.onClick();
                }}>
              {item.label}
            </button>))}
        </div>)}
    </div>);
    // Function: render tab
    const renderTab = () => {
        if (activeTab === 'File') {
            return (<div className="excel-home-panel">
          <div className="excel-home-actions" style={{ minHeight: 68, alignItems: 'stretch', gap: 4 }}>
            <label className="excel-action-button" style={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}>
              <span style={{ fontSize: 22, marginRight: 7 }}>↥</span>
              <span>
                <strong style={{ display: 'block' }}>Import Excel / CSV</strong>
                <small style={{ color: '#777' }}>.xlsx, .xls, .csv</small>
              </span>
              <input type="file" accept=".xlsx,.xls,.csv" style={{ display: 'none' }} onChange={event => {
                    const file = event.target.files?.[0];
                    void handleImport(file);
                    event.target.value = '';
                }}/>
            </label>
            <button type="button" className="excel-ribbon-big-button" onClick={handleExport}>
              <span className="excel-ribbon-icon">⇩</span>
              <span>Export current page</span>
            </button>
            {isBackendWorkbook ? (<button type="button" className="excel-ribbon-big-button" disabled={syncing || loadingPage} onClick={handleSavePage}>
                <span className="excel-ribbon-icon">▣</span>
                <span>{syncing ? 'Saving…' : 'Save edits'}</span>
              </button>) : (<button type="button" className="excel-ribbon-big-button" disabled={syncing} onClick={handleSyncToAI}>
                <span className="excel-ribbon-icon">✓</span>
                <span>{syncing ? 'Syncing…' : 'Apply to AI'}</span>
              </button>)}
            <div className="excel-help-panel" style={{ flex: 1, minHeight: 0, padding: '12px 18px' }}>
              <strong>Workbook</strong>
              <div style={{ marginTop: 7 }}>Import a workbook, export the current page, or save backend edits.</div>
            </div>
          </div>
        </div>);
        }
        if (activeTab === 'Home') {
            return (<div className="excel-home-panel">
          <div className="excel-home-actions">
            <button type="button" className="excel-action-button" onClick={() => setActiveTab('Data')}>Data</button>
            <button type="button" className="excel-action-button" onClick={() => setShowFindReplace(!showFindReplace)}>
              {showFindReplace ? 'Hide Find & Replace' : 'Find & Replace'}
            </button>
            <button type="button" className="excel-action-button" onClick={handleExport}>Export</button>
            {isBackendWorkbook ? (<button type="button" className="excel-action-button primary" disabled={syncing || loadingPage} onClick={handleSavePage}>
                {syncing ? 'Saving…' : 'Save'}
              </button>) : (<button type="button" className="excel-action-button primary" disabled={syncing} onClick={handleSyncToAI}>
                {syncing ? 'Syncing…' : 'Apply to AI Analyst'}
              </button>)}
          </div>
          <FormattingToolbar />
        </div>);
        }
        if (activeTab === 'Data') {
            return (<div className="excel-cleaning-panel" style={{ minHeight: 68 }}>
          <DataCleaningRibbon state={state} dispatch={dispatch} setMessage={setMessage} selectedColumn={selectedColumn} setSelectedColumn={setSelectedColumn} onRowsChanged={onRowsChanged}/>
        </div>);
        }
        if (activeTab === 'Transform') {
            return (<div className="excel-transform-panel">
          <div className="excel-ribbon-group">
            <button type="button" className="excel-ribbon-big-button" onClick={() => setActiveTab('Data')}>
              <span className="excel-ribbon-icon">🧹</span>
              <span>Data Cleaning</span>
            </button>
            <div className="excel-group-label">Clean</div>
          </div>
          <div className="excel-ribbon-group">
            <button type="button" className="excel-ribbon-big-button" onClick={() => setShowFindReplace(!showFindReplace)}>
              <span className="excel-ribbon-icon">⌕</span>
              <span>Find & Replace</span>
            </button>
            <div className="excel-group-label">Transform</div>
          </div>
          <div className="excel-ribbon-group">
            <button type="button" className="excel-ribbon-big-button" onClick={handleExport}>
              <span className="excel-ribbon-icon">⇩</span>
              <span>Export Page</span>
            </button>
            <div className="excel-group-label">Output</div>
          </div>
        </div>);
        }
        if (activeTab === 'AI Analyst') {
            return (<div className="excel-ai-panel">
          <div className="excel-ai-card">
            <span className="ai-icon">🤖</span>
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>AI Analyst</div>
              <div style={{ fontSize: 11, color: '#666', marginTop: 3 }}>Send the current workbook data to your AI Analyst.</div>
            </div>
            <button type="button" className="excel-action-button primary" disabled={syncing} onClick={handleSyncToAI}>
              {syncing ? 'Syncing…' : 'Apply data to AI Analyst'}
            </button>
          </div>
        </div>);
        }
        if (activeTab === 'View') {
            return (<div className="excel-help-panel">
          <strong>View</strong>
          <div style={{ marginTop: 8 }}>Spreadsheet navigation, formula bar and OpenSheets grid remain unchanged.</div>
        </div>);
        }
        if (activeTab === 'Insert') {
            return (<div className="excel-transform-panel" style={{ minHeight: 68, alignItems: 'stretch' }}>
          <div className="excel-ribbon-group">
            <button type="button" className="excel-ribbon-big-button" onClick={() => onOpenChartDialog('column')}>
              <span className="excel-ribbon-icon">▥</span>
              <span>Recommended<br />Charts</span>
            </button>
            <div className="excel-group-label">Charts</div>
          </div>
          <div className="excel-ribbon-group">
            <button type="button" className="excel-ribbon-big-button" onClick={() => onOpenChartDialog('column')}>
              <span className="excel-ribbon-icon">📊</span>
              <span>Column</span>
            </button>
            <div className="excel-group-label">Charts</div>
          </div>
          <div className="excel-ribbon-group">
            <button type="button" className="excel-ribbon-big-button" onClick={() => onOpenChartDialog('line')}>
              <span className="excel-ribbon-icon">📈</span>
              <span>Line</span>
            </button>
            <div className="excel-group-label">Charts</div>
          </div>
          <div className="excel-ribbon-group">
            <button type="button" className="excel-ribbon-big-button" onClick={() => onOpenChartDialog('pie')}>
              <span className="excel-ribbon-icon">🥧</span>
              <span>Pie</span>
            </button>
            <div className="excel-group-label">Charts</div>
          </div>
          <div className="excel-ribbon-group">
            <button type="button" className="excel-ribbon-big-button" onClick={() => onOpenChartDialog('bar')}>
              <span className="excel-ribbon-icon">▥</span>
              <span>Bar</span>
            </button>
            <div className="excel-group-label">Charts</div>
          </div>
          <div className="excel-ribbon-group">
            <button type="button" className="excel-ribbon-big-button" onClick={() => onOpenChartDialog()}>
              <span className="excel-ribbon-icon">↶</span>
              <span>Chart<br />Tools</span>
            </button>
            <div className="excel-group-label">Chart</div>
          </div>
        </div>);
        }
        return (<div className="excel-help-panel">
        <strong>Help</strong>
        <div style={{ marginTop: 8 }}>Select a column header to target it for Data Cleaning. Use the Data tab for cleaning, sorting and data-type operations.</div>
      </div>);
    };
    return (<>
      <style>{EXCEL_RIBBON_CSS}</style>
      <div className="excel-shell">
        <div className="excel-tabs">
          {tabs.map(tab => (<button key={tab} type="button" className={`excel-tab ${activeTab === tab ? 'active' : ''}`} onClick={() => {
                setOpenMenu(null);
                setActiveTab(tab);
                if (ribbonCollapsed)
                    setRibbonCollapsed(false);
            }}>
              {tab}
            </button>))}
          <button type="button" className="excel-ribbon-collapse-button" title={ribbonCollapsed ? 'Show ribbon' : 'Hide ribbon'} aria-label={ribbonCollapsed ? 'Show ribbon' : 'Hide ribbon'} aria-expanded={!ribbonCollapsed} onClick={() => {
            setOpenMenu(null);
            setRibbonCollapsed(value => !value);
        }}>
            {ribbonCollapsed ? '⌄' : '⌃'}
          </button>
        </div>
        {!ribbonCollapsed && renderTab()}
      </div>
    </>);
}
// Component or function: column to letters
function columnToLetters(index) {
    let n = index + 1;
    let out = '';
    while (n > 0) {
        const r = (n - 1) % 26;
        out = String.fromCharCode(65 + r) + out;
        n = Math.floor((n - 1) / 26);
    }
    return out;
}
// Component or function: letters to column
function lettersToColumn(value) {
    let result = 0;
    for (const ch of value.toUpperCase())
        result = result * 26 + ch.charCodeAt(0) - 64;
    return Math.max(0, result - 1);
}
// Component or function: normalize chart range
function normalizeChartRange(range) {
    // Value: clean
    const clean = range.trim().replace(/\$/g, '');
    // Value: match
    const match = clean.match(/^([A-Za-z]+)(\d+)(?::([A-Za-z]+)(\d+))?$/);
    if (!match)
        return null;
    // Value: start col
    const startCol = lettersToColumn(match[1]);
    // Value: start row
    const startRow = Math.max(0, Number(match[2]) - 1);
    // Value: end col
    const endCol = match[3] ? lettersToColumn(match[3]) : startCol;
    // Value: end row
    const endRow = match[4] ? Math.max(0, Number(match[4]) - 1) : startRow;
    return {
        startRow: Math.min(startRow, endRow),
        endRow: Math.max(startRow, endRow),
        startCol: Math.min(startCol, endCol),
        endCol: Math.max(startCol, endCol),
    };
}
// Component or function: selection to chart range
function selectionToChartRange(selection) {
    // Value: range
    const range = Array.isArray(selection?.ranges) ? selection.ranges[0] : null;
    if (!range)
        return '';
    // Value: sr
    const sr = Number(range.startRow);
    // Value: er
    const er = Number(range.endRow);
    // Value: sc
    const sc = Number(range.startCol);
    // Value: ec
    const ec = Number(range.endCol);
    if (![sr, er, sc, ec].every(Number.isFinite))
        return '';
    return `${columnToLetters(Math.min(sc, ec))}${Math.min(sr, er) + 1}:${columnToLetters(Math.max(sc, ec))}${Math.max(sr, er) + 1}`;
}
// Component or function: chart data from state
function chartDataFromState(state, rangeText) {
    // Value: range
    const range = normalizeChartRange(rangeText);
    if (!range || !state?.data?.get)
        return { headers: [], rows: [], range: null };
    // OpenSheets intentionally keeps extra empty worksheet columns available.
    // Do NOT treat those empty columns as chart columns. This is what caused
    // Ctrl+A selections such as A1:I501 to show a fake "Series 9" when the
    // actual dataset only had A:H.
    let lastUsedCol = range.startCol - 1;
    for (let c = range.startCol; c <= range.endCol; c++) {
        const headerValue = state.data.get(keyOf(range.startRow, c))?.value;
        if (headerValue !== null && headerValue !== undefined && String(headerValue).trim() !== '') {
            lastUsedCol = c;
        }
    }
    if (lastUsedCol < range.startCol) {
        return { headers: [], rows: [], range: null };
    }
    // Value: effective end col
    const effectiveEndCol = lastUsedCol;
    // Value: effective range
    const effectiveRange = { ...range, endCol: effectiveEndCol };
    // Value: headers
    const headers = [];
    for (let c = effectiveRange.startCol; c <= effectiveRange.endCol; c++) {
        const header = state.data.get(keyOf(effectiveRange.startRow, c))?.value;
        headers.push(String(header ?? '').trim());
    }
    // Value: rows
    const rows = [];
    for (let r = effectiveRange.startRow + 1; r <= effectiveRange.endRow; r++) {
        const row = headers.map((_, offset) => {
            const cell = state.data.get(keyOf(r, effectiveRange.startCol + offset));
            if (cell?.formula && String(cell.formula).startsWith('=')) {
                return evaluateFormula(cell.formula, (sourceRow, sourceCol) => state.data.get(keyOf(sourceRow, sourceCol)));
            }
            return cell?.value ?? null;
        });
        if (row.some(v => v !== null && v !== undefined && String(v).trim() !== ''))
            rows.push(row);
    }
    return { headers, rows, range: effectiveRange };
}
// Component or function: numeric series from chart data
function numericSeriesFromChartData(preview, categoryIndex) {
    return preview.headers.map((_, index) => index).filter(index => {
        if (index === categoryIndex)
            return false;
        let numericCount = 0;
        let nonBlankCount = 0;
        for (const row of preview.rows.slice(0, 200)) {
            const value = row[index];
            if (value === null || value === undefined || String(value).trim() === '')
                continue;
            nonBlankCount += 1;
            if (chartNumeric(value) !== null)
                numericCount += 1;
        }
        return nonBlankCount > 0 && numericCount / nonBlankCount >= 0.7;
    });
}
// Component or function: chart numeric
function chartNumeric(value) {
    if (typeof value === 'number' && Number.isFinite(value))
        return value;
    if (value === null || value === undefined || String(value).trim() === '')
        return null;
    // Value: n
    const n = Number(String(value).replace(/,/g, '').replace(/[₹$€£%]/g, '').trim());
    return Number.isFinite(n) ? n : null;
}
// Component or function: chart preview
function ChartPreview({ chart, state, selected, onSelect, onMove }) {
    // Ref: chart ref
    const chartRef = useRef(null);
    // Ref: instance ref
    const instanceRef = useRef(null);
    // Value: 
    const { headers, rows } = chartDataFromState(state, chart.range);
    // Value: category index
    const categoryIndex = Math.max(0, Math.min(headers.length - 1, chart.categoryIndex ?? 0));
    // Function: series index
    const seriesIndex = chart.seriesIndices?.find(i => i >= 0 && i < headers.length && i !== categoryIndex)
        ?? numericSeriesFromChartData({ headers, rows }, categoryIndex)[0]
        ?? Math.min(1, Math.max(0, headers.length - 1));
    // Legend is truly independent from Y, but it must only be used when the
    // user explicitly selected a different legend column. Older chart objects
    // may contain the Y column in legendIndices from the previous chart model;
    // treating that as a legend would group/sum values and produce incorrect
    // totals such as 5,181 instead of the row value 280.
    const requestedLegendIndex = chart.legendIndices?.[0];
    // Value: legend index
    const legendIndex = requestedLegendIndex != null
        && requestedLegendIndex >= 0
        && requestedLegendIndex < headers.length
        && requestedLegendIndex !== seriesIndex
        && requestedLegendIndex !== categoryIndex
        ? requestedLegendIndex
        : null;
    // Function: build option
    const buildOption = () => {
        const categoryHeader = headers[categoryIndex] || 'Category';
        const valueHeader = headers[seriesIndex] || 'Values';
        const labels = rows.map(r => String(r[categoryIndex] ?? ''));
        const values = rows.map(r => chartNumeric(r[seriesIndex]));
        const grouped = new Map();
        if (chart.legend !== false && legendIndex !== null && !['pie', 'doughnut'].includes(chart.type)) {
            rows.forEach(r => {
                const category = String(r[categoryIndex] ?? '');
                const legendValue = String(r[legendIndex] ?? '');
                const value = chartNumeric(r[seriesIndex]);
                if (!category || value === null)
                    return;
                if (!grouped.has(legendValue))
                    grouped.set(legendValue, new Map());
                const map = grouped.get(legendValue);
                map.set(category, (map.get(category) || 0) + value);
            });
        }
        if (chart.type === 'pie' || chart.type === 'doughnut') {
            const pieMap = new Map();
            rows.forEach(r => {
                const name = String(r[categoryIndex] ?? '');
                const value = chartNumeric(r[seriesIndex]);
                if (!name || value === null)
                    return;
                pieMap.set(name, (pieMap.get(name) || 0) + value);
            });
            return {
                animation: true,
                tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
                legend: { show: chart.legend !== false, type: 'scroll', bottom: 0 },
                series: [{
                        name: valueHeader,
                        type: 'pie',
                        radius: chart.type === 'doughnut' ? ['42%', '70%'] : '68%',
                        center: ['50%', '46%'],
                        label: { show: true, formatter: '{b}: {c}' },
                        data: Array.from(pieMap, ([name, value]) => ({ name, value })),
                    }],
            };
        }
        // Keep every worksheet row in the chart, but make large categorical
        // datasets readable. ECharts still receives all rows; only the initial
        // viewport and axis-label density are adjusted.
        const denseData = rows.length > 40;
        // For large datasets, start with a small readable window. All points remain in
        // the ECharts dataset; dataZoom only controls the initial viewport.
        const initialVisiblePoints = rows.length > 40 ? Math.min(24, rows.length) : rows.length;
        const initialZoomEnd = rows.length > 40
            ? Math.max(1, ((initialVisiblePoints - 1) / Math.max(1, rows.length - 1)) * 100)
            : 100;
        const labelInterval = denseData
            ? Math.max(0, Math.ceil(initialVisiblePoints / 8) - 1)
            : 0;
        const base = {
            animation: true,
            tooltip: {
                trigger: chart.type === 'scatter' || chart.type === 'bubble' ? 'item' : 'axis',
                axisPointer: { type: chart.type === 'line' || chart.type === 'area' ? 'line' : 'shadow' },
                formatter: (params) => {
                    const list = Array.isArray(params) ? params : [params];
                    if (!list.length)
                        return '';
                    const category = list[0]?.axisValue ?? list[0]?.name ?? '';
                    const lines = list.map((item) => {
                        const value = Array.isArray(item?.value) ? item.value[item.value.length - 1] : item?.value;
                        const formatted = value === null || value === undefined || value === ''
                            ? ''
                            : (typeof value === 'number' ? value.toLocaleString() : String(value));
                        return `${item?.marker || ''}${item?.seriesName || valueHeader}: <strong>${formatted}</strong>`;
                    });
                    return `<div style=\"min-width:120px\"><strong>${String(category)}</strong><br/>${lines.join('<br/>')}</div>`;
                },
            },
            legend: { show: chart.legend !== false, type: 'scroll', top: 0 },
            grid: { left: 62, right: 24, top: 48, bottom: denseData ? 88 : 62, containLabel: true },
            xAxis: {
                type: 'category',
                name: categoryHeader,
                nameLocation: 'middle',
                nameGap: denseData ? 52 : 32,
                data: labels,
                axisLabel: { interval: labelInterval, hideOverlap: true, rotate: rows.length > 100 ? 30 : 0 },
            },
            yAxis: { type: 'value', name: valueHeader, nameLocation: 'middle', nameGap: 46 },
            dataZoom: denseData ? [
                { type: 'slider', xAxisIndex: 0, start: 0, end: initialZoomEnd, height: 20, bottom: 16, showDetail: true, filterMode: 'filter' },
                { type: 'inside', xAxisIndex: 0, start: 0, end: initialZoomEnd, filterMode: 'filter' },
            ] : undefined,
        };
        const series = [];
        if (grouped.size) {
            for (const [groupName, map] of grouped) {
                const data = labels.map(label => map.get(label) ?? null);
                series.push({ name: groupName || '(Blank)', data, type: chart.type === 'area' ? 'line' : chart.type === 'bar' ? 'bar' : 'line' });
            }
        }
        else {
            const data = rows.map(r => chartNumeric(r[seriesIndex]));
            if (chart.type === 'scatter' || chart.type === 'bubble') {
                const scatterData = rows.map(r => [chartNumeric(r[categoryIndex]), chartNumeric(r[seriesIndex])]).filter(p => p[0] !== null && p[1] !== null);
                series.push({ name: valueHeader, type: 'scatter', data: scatterData, symbolSize: chart.type === 'bubble' ? 16 : 8 });
                return {
                    animation: true,
                    tooltip: { trigger: 'item' },
                    legend: { show: chart.legend !== false, top: 0 },
                    grid: { left: 62, right: 24, top: 48, bottom: 62, containLabel: true },
                    xAxis: { type: 'value', name: categoryHeader, nameLocation: 'middle', nameGap: 32 },
                    yAxis: { type: 'value', name: valueHeader, nameLocation: 'middle', nameGap: 46 },
                    series,
                };
            }
            if (chart.type === 'funnel') {
                return {
                    animation: true,
                    tooltip: { trigger: 'item' },
                    legend: { show: chart.legend !== false, type: 'scroll', top: 0 },
                    series: [{ type: 'funnel', left: '8%', top: 45, bottom: 25, width: '84%', minSize: '0%', maxSize: '100%', label: { show: true, formatter: '{b}: {c}' }, data: rows.map(r => ({ name: String(r[categoryIndex] ?? ''), value: chartNumeric(r[seriesIndex]) || 0 })) }],
                };
            }
            if (chart.type === 'radar') {
                const max = Math.max(1, ...data.map(v => Math.abs(v ?? 0)));
                return {
                    animation: true,
                    tooltip: { trigger: 'item' },
                    legend: { show: chart.legend !== false, top: 0 },
                    radar: { indicator: labels.map(name => ({ name, max })) },
                    series: [{ type: 'radar', data: [{ name: valueHeader, value: data.map(v => v ?? 0) }] }],
                };
            }
            series.push({ name: valueHeader, data });
        }
        if (chart.type === 'bar') {
            base.xAxis = { type: 'value', name: valueHeader };
            base.yAxis = {
                type: 'category',
                name: categoryHeader,
                data: labels,
                axisLabel: { interval: labelInterval, hideOverlap: true },
            };
            if (denseData) {
                base.grid = { left: 82, right: 24, top: 48, bottom: 58, containLabel: true };
                base.dataZoom = [
                    { type: 'slider', yAxisIndex: 0, start: 0, end: initialZoomEnd, width: 20, right: 8, showDetail: true, filterMode: 'filter' },
                    { type: 'inside', yAxisIndex: 0, start: 0, end: initialZoomEnd, filterMode: 'filter' },
                ];
            }
            series.forEach(s => s.type = 'bar');
        }
        else if (chart.type === 'column' || chart.type === 'waterfall') {
            series.forEach(s => s.type = 'bar');
        }
        else if (chart.type === 'area') {
            series.forEach(s => { s.type = 'line'; s.areaStyle = {}; });
        }
        else if (chart.type === 'combo') {
            series.forEach((s, i) => { s.type = i === 0 ? 'bar' : 'line'; });
        }
        else {
            series.forEach(s => s.type = 'line');
        }
        series.forEach(s => {
            if (s.type === 'bar')
                s.label = { show: rows.length <= 40, position: chart.type === 'bar' ? 'right' : 'top', formatter: ({ value }) => Number(value).toLocaleString() };
            if (s.type === 'line')
                s.label = { show: rows.length <= 40, formatter: ({ value }) => Number(value).toLocaleString() };
        });
        return { ...base, series };
    };
    // Run side effect when dependencies change
    useEffect(() => {
        if (!chartRef.current)
            return;
        const instance = instanceRef.current || echarts.init(chartRef.current);
        instanceRef.current = instance;
        instance.setOption(buildOption(), true);
        const resize = () => instance.resize();
        window.addEventListener('resize', resize);
        const observer = new ResizeObserver(resize);
        observer.observe(chartRef.current);
        resize();
        return () => {
            window.removeEventListener('resize', resize);
            observer.disconnect();
        };
    }, [chart, headers.join('|'), rows.length, categoryIndex, seriesIndex, legendIndex]);
    // Run side effect when dependencies change
    useEffect(() => () => {
        instanceRef.current?.dispose();
        instanceRef.current = null;
    }, []);
    return (<div onPointerDown={e => { e.stopPropagation(); onSelect(); }} style={{ position: 'absolute', left: chart.x, top: chart.y, width: chart.width, height: chart.height, background: '#fff', border: selected ? '2px solid #217346' : '1px solid #9ca3af', boxShadow: '0 2px 8px rgba(0,0,0,.18)', zIndex: selected ? 30 : 20, resize: 'both', overflow: 'hidden' }}>
      <div style={{ height: 32, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 600, fontSize: 14, color: '#222', userSelect: 'none', cursor: 'move' }} onPointerDown={e => {
            e.stopPropagation();
            const sx = e.clientX, sy = e.clientY, ox = chart.x, oy = chart.y;
            const move = (ev) => onMove(ox + ev.clientX - sx, oy + ev.clientY - sy);
            const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
            window.addEventListener('pointermove', move);
            window.addEventListener('pointerup', up);
        }}>{chart.title}</div>
      <div ref={chartRef} style={{ width: '100%', height: 'calc(100% - 32px)' }}/>
    </div>);
}
// Component or function: chart column dropdown
function ChartColumnDropdown({ headers, selected, onChange, placeholder, disabledIndices = [], singleSelect = false, }) {
    // State: 
    const [open, setOpen] = useState(false);
    // Value: selected set
    const selectedSet = new Set(selected);
    // Function: selected label
    const selectedLabel = selected.map(i => headers[i]).filter(Boolean).join(', ');
    return <div style={{ position: 'relative' }}>
    <button type="button" onClick={() => setOpen(v => !v)} style={{ width: '100%', height: 34, border: '1px solid #aaa', borderRadius: 3, background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 9px', cursor: 'pointer', textAlign: 'left' }}>
      <span style={{ overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis', fontSize: 11 }}>{selectedLabel || placeholder}</span><span style={{ fontSize: 10 }}>▾</span>
    </button>
    {open && <div style={{ position: 'absolute', top: 37, left: 0, right: 0, zIndex: 1100, background: '#fff', border: '1px solid #aaa', borderRadius: 3, boxShadow: '0 8px 24px rgba(0,0,0,.18)', maxHeight: 190, overflow: 'auto', padding: 5 }}>
      {headers.map((header, index) => {
                const disabled = disabledIndices.includes(index);
                return <label key={index} style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '6px 7px', fontSize: 11, opacity: disabled ? .45 : 1, cursor: disabled ? 'not-allowed' : 'pointer' }}>
          <input type={singleSelect ? 'radio' : 'checkbox'} name={singleSelect ? `chart-column-${placeholder}` : undefined} checked={selectedSet.has(index)} disabled={disabled} onChange={() => { if (disabled)
                    return; if (singleSelect) {
                    onChange([index]);
                    setOpen(false);
                }
                else
                    onChange(selectedSet.has(index) ? selected.filter(i => i !== index) : [...selected, index]); }}/>
          <span>{index + 1}. {header}</span>
        </label>;
            })}
      {!headers.length && <div style={{ padding: 8, fontSize: 11, color: '#777' }}>No columns available.</div>}
    </div>}
  </div>;
}
// Component or function: chart insert dialog
function ChartInsertDialog({ state, initialRange, initialType = 'column', initialTitle = 'Chart', initialChart, onClose, onInsert }) {
    // State: 
    const [type, setType] = useState(initialChart?.type || initialType);
    // State: 
    const [range, setRange] = useState(initialChart?.range || initialRange || 'A1:B10');
    // State: 
    const [title, setTitle] = useState(initialChart?.title || initialTitle || 'Chart');
    // State: 
    const [categoryIndex, setCategoryIndex] = useState(initialChart?.categoryIndex ?? 0);
    // State: 
    const [seriesIndices, setSeriesIndices] = useState(initialChart?.seriesIndices?.length ? [initialChart.seriesIndices[0]] : []);
    // State: 
    const [legendIndices, setLegendIndices] = useState(initialChart?.legendIndices?.length ? [initialChart.legendIndices[0]] : []);
    // State: 
    const [legend, setLegend] = useState(initialChart?.legend !== false);
    // State: 
    const [error, setError] = useState('');
    // Value: types
    const types = [['column', 'Column', 'Clustered columns'], ['bar', 'Bar', 'Horizontal bars'], ['line', 'Line', 'Line with markers'], ['pie', 'Pie', 'Category + values'], ['doughnut', 'Doughnut', 'Category + values'], ['area', 'Area', 'Area chart'], ['scatter', 'Scatter', 'XY scatter'], ['bubble', 'Bubble', 'Bubble chart'], ['radar', 'Radar', 'Radar chart'], ['waterfall', 'Waterfall', 'Waterfall'], ['funnel', 'Funnel', 'Funnel'], ['combo', 'Combo', 'Column + line']];
    // Value: preview
    const preview = chartDataFromState(state, range);
    // Value: numeric series
    const numericSeries = numericSeriesFromChartData(preview, categoryIndex);
    // Value: is pie
    const isPie = type === 'pie' || type === 'doughnut';
    // Run side effect when dependencies change
    useEffect(() => {
        if (!preview.headers.length)
            return;
        const safe = Math.min(Math.max(categoryIndex, 0), preview.headers.length - 1);
        if (safe !== categoryIndex)
            setCategoryIndex(safe);
        setSeriesIndices(current => {
            const valid = current.filter(i => i >= 0 && i < preview.headers.length && i !== safe);
            return valid.length ? valid : (numericSeries[0] != null ? [numericSeries[0]] : []);
        });
        setLegendIndices(current => {
            const valid = current.filter(i => i >= 0 && i < preview.headers.length && i !== safe);
            return valid.length ? valid : [];
        });
    }, [preview.headers.join('|'), preview.rows.length, categoryIndex]);
    // Function: insert
    const insert = () => {
        if (!normalizeChartRange(range)) {
            setError('Enter a valid range such as A1:B20.');
            return;
        }
        if (preview.headers.length < 2 || !preview.rows.length) {
            setError('Select a range containing a header row and data.');
            return;
        }
        if (!seriesIndices.length) {
            setError('Select one numeric Values / Data Series column.');
            return;
        }
        if (!isPie && categoryIndex === seriesIndices[0]) {
            setError('X Axis and Y Axis must be different columns.');
            return;
        }
        onInsert({
            id: initialChart?.id || `chart-${Date.now()}`, type, title: title.trim() || 'Chart', range,
            x: initialChart?.x ?? 70, y: initialChart?.y ?? 70, width: initialChart?.width ?? 560, height: initialChart?.height ?? 360,
            categoryIndex, seriesIndices: [seriesIndices[0]], legend, legendIndices: legendIndices.length ? [legendIndices[0]] : [],
            xAxisTitle: isPie ? undefined : (preview.headers[categoryIndex] || 'X Axis'),
            yAxisTitle: isPie ? undefined : (preview.headers[seriesIndices[0]] || 'Y Axis'),
        });
    };
    return <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,.25)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onMouseDown={e => { if (e.target === e.currentTarget)
        onClose(); }}>
    <div style={{ width: 900, maxHeight: '90vh', overflow: 'auto', background: '#fff', borderRadius: 6, boxShadow: '0 12px 40px rgba(0,0,0,.25)', border: '1px solid #c8c8c8' }}>
      <div style={{ padding: '14px 18px', borderBottom: '1px solid #ddd', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><div><strong style={{ fontSize: 18 }}>Insert Chart</strong><div style={{ fontSize: 11, color: '#666', marginTop: 3 }}>Excel-style chart insertion with independent column selectors.</div></div><button onClick={onClose} style={{ border: 0, background: 'transparent', fontSize: 22, cursor: 'pointer' }}>×</button></div>
      <div style={{ display: 'grid', gridTemplateColumns: '1.1fr .9fr', gap: 16, padding: 18 }}>
        <div><div style={{ fontSize: 12, fontWeight: 600, marginBottom: 7 }}>Chart type</div><div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 7 }}>{types.map(([v, label, sub]) => <button key={v} type="button" onClick={() => setType(v)} style={{ height: 62, border: type === v ? '2px solid #217346' : '1px solid #cfcfcf', background: type === v ? '#eef7f0' : '#fff', borderRadius: 4, cursor: 'pointer', textAlign: 'left', padding: '7px 8px' }}><div style={{ fontSize: 12, fontWeight: 600 }}>{label}</div><div style={{ fontSize: 9, color: '#777', marginTop: 3 }}>{sub}</div></button>)}</div></div>
        <div><label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 5 }}>Chart data range</label><div style={{ display: 'flex', gap: 6 }}><input value={range} onChange={e => { setRange(e.target.value); setError(''); }} style={{ flex: 1, height: 32, border: '1px solid #aaa', borderRadius: 3, padding: '0 8px' }}/><button type="button" onClick={() => setRange(selectionToChartRange(state.selection) || range)} style={{ height: 32, padding: '0 10px', border: '1px solid #aaa', background: '#f7f7f7', borderRadius: 3 }}>Use selection</button></div><label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginTop: 12, marginBottom: 5 }}>Chart title</label><input value={title} onChange={e => setTitle(e.target.value)} style={{ width: '100%', boxSizing: 'border-box', height: 32, border: '1px solid #aaa', borderRadius: 3, padding: '0 8px' }}/><div style={{ marginTop: 12, padding: 10, border: '1px solid #ddd', background: '#fafafa', fontSize: 11 }}><strong>Detected columns</strong><div style={{ marginTop: 5 }}>{preview.headers.map((h, i) => <span key={i} style={{ display: 'inline-block', padding: '3px 7px', margin: '2px', border: '1px solid #ddd', borderRadius: 12, background: '#fff' }}>{i + 1}. {h}</span>)}</div><div style={{ marginTop: 6 }}>Rows: {preview.rows.length}</div></div></div>
      </div>
      <div style={{ padding: '0 18px 18px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        {isPie ? <>
          <div style={{ border: '1px solid #ddd', borderRadius: 4, padding: 12 }}><div style={{ fontWeight: 600, fontSize: 12, marginBottom: 7 }}>Category / Legend</div><ChartColumnDropdown headers={preview.headers} selected={[categoryIndex]} onChange={next => setCategoryIndex(next[0] ?? 0)} placeholder="Select category column" singleSelect/><div style={{ fontSize: 10, color: '#777', marginTop: 6 }}>Each category becomes a pie/doughnut slice and legend item.</div></div>
          <div style={{ border: '1px solid #ddd', borderRadius: 4, padding: 12 }}><div style={{ fontWeight: 600, fontSize: 12, marginBottom: 7 }}>Values / Data Series</div><ChartColumnDropdown headers={preview.headers} selected={seriesIndices} onChange={next => setSeriesIndices(next.length ? [next[next.length - 1]] : [])} placeholder="Select values column" disabledIndices={[categoryIndex]} singleSelect/><div style={{ fontSize: 10, color: '#777', marginTop: 6 }}>Numeric values are aggregated by category.</div></div>
          <div style={{ border: '1px solid #ddd', borderRadius: 4, padding: 12 }}><div style={{ fontWeight: 600, fontSize: 12, marginBottom: 7 }}>Legend</div><label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}><input type="checkbox" checked={legend} onChange={e => setLegend(e.target.checked)}/> Show category legend</label><div style={{ marginTop: 8, fontSize: 10, color: '#777' }}>Legend is generated automatically from the Category column.</div></div>
        </> : <>
          <div style={{ border: '1px solid #ddd', borderRadius: 4, padding: 12 }}><div style={{ fontWeight: 600, fontSize: 12, marginBottom: 7 }}>X Axis</div><ChartColumnDropdown headers={preview.headers} selected={[categoryIndex]} onChange={next => setCategoryIndex(next[0] ?? 0)} placeholder="Select X-axis column" singleSelect/><div style={{ fontSize: 10, color: '#777', marginTop: 6 }}>Selected X-axis: <strong>{preview.headers[categoryIndex] || 'None'}</strong></div></div>
          <div style={{ border: '1px solid #ddd', borderRadius: 4, padding: 12 }}><div style={{ fontWeight: 600, fontSize: 12, marginBottom: 7 }}>Y Axis / Values</div><ChartColumnDropdown headers={preview.headers} selected={seriesIndices} onChange={next => setSeriesIndices(next.length ? [next[next.length - 1]] : [])} placeholder="Select Y-axis column" disabledIndices={[categoryIndex]} singleSelect/><div style={{ fontSize: 10, color: '#777', marginTop: 6 }}>Selected Y-axis: <strong>{preview.headers[seriesIndices[0]] || 'None'}</strong></div></div>
          <div style={{ border: '1px solid #ddd', borderRadius: 4, padding: 12 }}><div style={{ fontWeight: 600, fontSize: 12, marginBottom: 7 }}>Legend</div><ChartColumnDropdown headers={preview.headers} selected={legendIndices} onChange={next => setLegendIndices(next.length ? [next[next.length - 1]] : [])} placeholder="Select any legend column" disabledIndices={[categoryIndex]} singleSelect/><label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, marginTop: 9 }}><input type="checkbox" checked={legend} onChange={e => setLegend(e.target.checked)}/> Show legend</label><div style={{ marginTop: 8, fontSize: 10, color: '#777' }}>Legend is independent of X and Y.</div></div>
        </>}
      </div>
      <div style={{ padding: '0 18px 18px', fontSize: 10, color: '#666' }}>{isPie ? <>Category = <strong>{preview.headers[categoryIndex] || 'None'}</strong> · Values = <strong>{preview.headers[seriesIndices[0]] || 'None'}</strong></> : <>X = <strong>{preview.headers[categoryIndex] || 'None'}</strong> · Y = <strong>{preview.headers[seriesIndices[0]] || 'None'}</strong> · Legend = <strong>{preview.headers[legendIndices[0]] || 'None'}</strong></>}</div>
      {error && <div style={{ margin: '0 18px 12px', color: '#b42318', fontSize: 11 }}>{error}</div>}
      <div style={{ padding: '10px 18px', borderTop: '1px solid #ddd', display: 'flex', justifyContent: 'flex-end', gap: 8 }}><button type="button" onClick={onClose} style={{ height: 32, padding: '0 14px', border: '1px solid #aaa', background: '#fff', borderRadius: 3 }}>Cancel</button><button type="button" onClick={insert} style={{ height: 32, padding: '0 16px', border: '1px solid #217346', background: '#217346', color: '#fff', borderRadius: 3, fontWeight: 600 }}>Insert Chart</button></div>
    </div>
  </div>;
}
// Component or function: spreadsheet workspace
function SpreadsheetWorkspace(props) {
    // Value: 
    const { fileToImport, onImportConsumed, onSyncToAI, onSaveCellEdits, syncing = false, sessionId = '', rowCount = 0, columns = [], apiBase = 'http://localhost:8000', importMode = 'full', onImportModeChange, customImportRows = 1, onCustomImportRowsChange, } = props;
    // Value: 
    const { state, dispatch } = useSpreadsheet();
    // State: 
    const [message, setMessage] = useState('Ready');
    // State: 
    const [pageRows, setPageRows] = useState(props.initialRows || []);
    // State: 
    const [loadingPage, setLoadingPage] = useState(false);
    // State: 
    const [importLoading, setImportLoading] = useState(false);
    // State: 
    const [loadingProgress, setLoadingProgress] = useState(0);
    // State: 
    const [customRowCount, setCustomRowCount] = useState('');
    // Ref: custom row count ref
    const customRowCountRef = useRef(0);
    // State: 
    const [pendingImportFile, setPendingImportFile] = useState(null);
    // State: 
    const [showImportChoice, setShowImportChoice] = useState(false);
    // Ref: loading rows ref
    const loadingRowsRef = useRef(false);
    // Ref: loaded rows count ref
    const loadedRowsCountRef = useRef((props.initialRows || []).length);
    // Ref: loaded chunk set ref
    const loadedChunkSetRef = useRef(new Set());
    // Ref: baseline cell values ref
    const baselineCellValuesRef = useRef(new Map());
    // Ref: total dataset rows ref
    const totalDatasetRowsRef = useRef(rowCount);
    // Keep the selected import mode in a ref so a preview import can never
    // accidentally start loading chunk 2+ while React is still updating state.
    const importModeRef = useRef(importMode);
    // Ref: state ref
    const stateRef = useRef(state);
    // State: 
    const [showFindReplace, setShowFindReplace] = useState(false);
    // State: 
    const [findText, setFindText] = useState('');
    // State: 
    const [replaceText, setReplaceText] = useState('');
    // State: 
    const [matchCase, setMatchCase] = useState(false);
    // State: 
    const [matchWholeCell, setMatchWholeCell] = useState(false);
    // State: 
    const [replaceBusy, setReplaceBusy] = useState(false);
    // State: 
    const [selectedColumn, setSelectedColumn] = useState('');
    // State: 
    const [selectedDataType, setSelectedDataType] = useState('Text');
    // State: 
    const [columnActionBusy, setColumnActionBusy] = useState(false);
    // State: 
    const [refreshVersion, setRefreshVersion] = useState(0);
    // State: 
    const [activeRibbonTab, setActiveRibbonTab] = useState('Home');
    // State: 
    const [chartObjects, setChartObjects] = useState([]);
    // State: 
    const [showChartDialog, setShowChartDialog] = useState(false);
    // State: 
    const [chartDialogType, setChartDialogType] = useState('column');
    // State: 
    const [selectedChartId, setSelectedChartId] = useState(null);
    // Ref: baseline rows
    const baselineRows = useRef(props.initialRows || []);
    // Ref: baseline columns
    const baselineColumns = useRef(columns);
    // Ref: active session
    const activeSession = useRef(sessionId);
    // Value: is backend workbook
    const isBackendWorkbook = Boolean(sessionId);
    // Ref: grid ref
    const gridRef = useRef(null);
    // Ref: header selection ref
    const headerSelectionRef = useRef(null);
    // Ref: header undo ref
    const headerUndoRef = useRef([]);
    // Ref: header redo ref
    const headerRedoRef = useRef([]);
    // Run side effect when dependencies change
    useEffect(() => {
        stateRef.current = state;
    }, [state]);
    // Run side effect when dependencies change
    useEffect(() => {
        importModeRef.current = importMode;
    }, [importMode]);
    // While the user is dragging a cell/range selection, scroll the spreadsheet
    // automatically when the pointer reaches the top/bottom edge of the grid.
    // This makes large-range selection behave like Excel instead of stopping
    // at the currently visible rows.
    useEffect(() => {
        const grid = gridRef.current;
        if (!grid)
            return;
        let pointerDown = false;
        let animationFrame = 0;
        let lastPointerX = 0;
        let lastPointerY = 0;
        const isInsideGrid = (x, y) => {
            const rect = grid.getBoundingClientRect();
            const verticalMargin = 40;
            return (x >= rect.left &&
                x <= rect.right &&
                y >= rect.top - verticalMargin &&
                y <= rect.bottom + verticalMargin);
        };
        const findScrollableAncestor = (start) => {
            let element = start;
            while (element && element !== grid.parentElement) {
                const style = window.getComputedStyle(element);
                const canScrollY = (style.overflowY === 'auto' || style.overflowY === 'scroll') &&
                    element.scrollHeight > element.clientHeight + 1;
                if (canScrollY)
                    return element;
                element = element.parentElement;
            }
            const gridStyle = window.getComputedStyle(grid);
            if ((gridStyle.overflowY === 'auto' || gridStyle.overflowY === 'scroll') &&
                grid.scrollHeight > grid.clientHeight + 1) {
                return grid;
            }
            return null;
        };
        const scrollWhileSelecting = () => {
            animationFrame = 0;
            if (!pointerDown || !isInsideGrid(lastPointerX, lastPointerY))
                return;
            const rect = grid.getBoundingClientRect();
            const edgeSize = Math.min(90, Math.max(45, rect.height * 0.15));
            let delta = 0;
            if (lastPointerY < rect.top + edgeSize) {
                const distance = rect.top + edgeSize - lastPointerY;
                delta = -Math.max(2, Math.min(28, distance * 0.35));
            }
            else if (lastPointerY > rect.bottom - edgeSize) {
                const distance = lastPointerY - (rect.bottom - edgeSize);
                delta = Math.max(2, Math.min(28, distance * 0.35));
            }
            if (delta === 0)
                return;
            const elementAtPointer = document.elementFromPoint(lastPointerX, lastPointerY);
            const scrollContainer = findScrollableAncestor(elementAtPointer) ||
                findScrollableAncestor(grid);
            if (scrollContainer) {
                const previousTop = scrollContainer.scrollTop;
                scrollContainer.scrollTop += delta;
                // Keep scrolling while the pointer remains at the edge and the user
                // keeps holding the mouse button.
                if (scrollContainer.scrollTop !== previousTop) {
                    animationFrame = window.requestAnimationFrame(scrollWhileSelecting);
                }
            }
        };
        const onPointerDown = (event) => {
            if (event.button !== 0)
                return;
            if (!isInsideGrid(event.clientX, event.clientY))
                return;
            pointerDown = true;
            lastPointerX = event.clientX;
            lastPointerY = event.clientY;
        };
        const onPointerMove = (event) => {
            if (!pointerDown)
                return;
            lastPointerX = event.clientX;
            lastPointerY = event.clientY;
            if (!animationFrame) {
                animationFrame = window.requestAnimationFrame(scrollWhileSelecting);
            }
        };
        const stopPointerTracking = () => {
            pointerDown = false;
            if (animationFrame) {
                window.cancelAnimationFrame(animationFrame);
                animationFrame = 0;
            }
        };
        grid.addEventListener('pointerdown', onPointerDown, true);
        window.addEventListener('pointermove', onPointerMove, true);
        window.addEventListener('pointerup', stopPointerTracking, true);
        window.addEventListener('pointercancel', stopPointerTracking, true);
        return () => {
            stopPointerTracking();
            grid.removeEventListener('pointerdown', onPointerDown, true);
            window.removeEventListener('pointermove', onPointerMove, true);
            window.removeEventListener('pointerup', stopPointerTracking, true);
            window.removeEventListener('pointercancel', stopPointerTracking, true);
        };
    }, []);
    // Excel-style whole-row / whole-column selection. OpenSheets already owns the
    // normal cell selection, copy/paste and keyboard navigation; this adds the
    // missing header-click behavior without replacing OpenSheets' grid rendering.
    useEffect(() => {
        const grid = gridRef.current;
        if (!grid)
            return;
        const toZeroBasedIndex = (value, fallbackText) => {
            if (value != null && value !== '') {
                const n = Number(value);
                if (Number.isFinite(n))
                    return n >= 1 ? n - 1 : n;
            }
            const text = fallbackText.trim();
            if (/^\d+$/.test(text))
                return Math.max(0, Number(text) - 1);
            if (/^[A-Za-z]+$/.test(text)) {
                let n = 0;
                for (const char of text.toUpperCase())
                    n = n * 26 + (char.charCodeAt(0) - 64);
                return n - 1;
            }
            return null;
        };
        const findHeaderInfo = (target) => {
            let element = target;
            while (element && element !== grid) {
                const role = element.getAttribute('role') || '';
                const className = typeof element.className === 'string' ? element.className : '';
                const lowerClass = className.toLowerCase();
                const isColumnHeader = role === 'columnheader' || /column.?header|col.?header|header.?column/.test(lowerClass);
                const isRowHeader = role === 'rowheader' || /row.?header|header.?row/.test(lowerClass);
                if (isColumnHeader) {
                    const index = toZeroBasedIndex(element.getAttribute('data-col-index') || element.getAttribute('data-column-index') || element.getAttribute('aria-colindex'), element.textContent || '');
                    if (index !== null && index >= 0)
                        return { type: 'column', index };
                }
                if (isRowHeader) {
                    const index = toZeroBasedIndex(element.getAttribute('data-row-index') || element.getAttribute('aria-rowindex'), element.textContent || '');
                    if (index !== null && index >= 0)
                        return { type: 'row', index };
                }
                element = element.parentElement;
            }
            // OpenSheets versions can render the row/column headers without semantic
            // role/data attributes. Fall back to the header geometry used by the grid.
            // This keeps the behavior working across those DOM variants.
            const rect = grid.getBoundingClientRect();
            const x = target?.clientX ?? 0;
            const y = target?.clientY ?? 0;
            if (!x || !y || x < rect.left || x > rect.right || y < rect.top || y > rect.bottom)
                return null;
            const headerHeight = 32;
            const rowHeaderWidth = 42;
            const localX = x - rect.left;
            const localY = y - rect.top;
            // Find the actual scrollable element used by OpenSheets. The outer
            // wrapper is intentionally non-scrollable, so this resolves to the grid's
            // internal viewport rather than creating a second scrollbar.
            let viewport = grid;
            const descendants = Array.from(grid.querySelectorAll('*'));
            for (const candidate of descendants) {
                const style = window.getComputedStyle(candidate);
                const canScroll = (style.overflowY === 'auto' || style.overflowY === 'scroll') &&
                    candidate.scrollHeight > candidate.clientHeight + 1;
                if (canScroll) {
                    viewport = candidate;
                    break;
                }
            }
            const scrollLeft = viewport?.scrollLeft || 0;
            const scrollTop = viewport?.scrollTop || 0;
            const current = state;
            const maxCols = Math.max(1, Number(current.maxCols) || baselineColumns.current.length || 100);
            const maxRows = Math.max(1, Number(current.maxRows) || PAGE_SIZE + 1);
            const colWidths = Array.isArray(current.colWidths) ? current.colWidths : [];
            const rowHeights = Array.isArray(current.rowHeights) ? current.rowHeights : [];
            if (localY <= headerHeight && localX >= rowHeaderWidth) {
                let remaining = localX - rowHeaderWidth + scrollLeft;
                let columnIndex = 0;
                while (columnIndex < maxCols - 1) {
                    const width = Math.max(20, Number(colWidths[columnIndex]) || 140);
                    if (remaining < width)
                        break;
                    remaining -= width;
                    columnIndex += 1;
                }
                return { type: 'column', index: columnIndex };
            }
            if (localX <= rowHeaderWidth && localY >= headerHeight) {
                let remaining = localY - headerHeight + scrollTop;
                let rowIndex = 0;
                while (rowIndex < maxRows - 1) {
                    const height = Math.max(16, Number(rowHeights[rowIndex]) || 22);
                    if (remaining < height)
                        break;
                    remaining -= height;
                    rowIndex += 1;
                }
                return { type: 'row', index: rowIndex };
            }
            return null;
        };
        const selectHeader = (selection) => {
            const current = state;
            const maxRows = Math.max(1, Number(current.maxRows) || PAGE_SIZE + 1);
            const maxCols = Math.max(1, Number(current.maxCols) || baselineColumns.current.length || 100);
            if (selection.index < 0 || (selection.type === 'column' ? selection.index >= maxCols : selection.index >= maxRows))
                return;
            const range = selection.type === 'column'
                ? { startRow: 0, endRow: maxRows - 1, startCol: selection.index, endCol: selection.index }
                : { startRow: selection.index, endRow: selection.index, startCol: 0, endCol: maxCols - 1 };
            headerSelectionRef.current = selection;
            if (selection.type === 'column') {
                const header = baselineColumns.current[selection.index];
                if (header)
                    setSelectedColumn(header.field);
            }
            dispatch({
                type: 'LOAD_STATE',
                payload: {
                    ...current,
                    selection: {
                        ranges: [range],
                        active: {
                            row: selection.type === 'column' ? 0 : selection.index,
                            col: selection.type === 'column' ? selection.index : 0,
                        },
                    },
                },
            });
        };
        const clearHeaderMode = (event) => {
            const target = event.target;
            if (!target?.closest('.opensheets-grid'))
                return;
            if (findHeaderInfo(target))
                return;
            headerSelectionRef.current = null;
        };
        const onClick = (event) => {
            if (event.button !== 0)
                return;
            const target = event.target;
            if (!target || !grid.contains(target))
                return;
            const info = findHeaderInfo(target);
            if (!info)
                return;
            const targetClass = typeof target.className === 'string' ? target.className.toLowerCase() : '';
            if (/resize|resizer|handle/.test(targetClass))
                return;
            event.preventDefault();
            event.stopPropagation();
            selectHeader(info);
        };
        grid.addEventListener('pointerdown', clearHeaderMode, true);
        grid.addEventListener('click', onClick, true);
        return () => {
            grid.removeEventListener('pointerdown', clearHeaderMode, true);
            grid.removeEventListener('click', onClick, true);
        };
    }, [state, dispatch]);
    // Clear the selected cell/range when Delete or Backspace is pressed inside the grid.
    // Use LOAD_STATE (already used by this component) so React/OpenSheets re-renders.
    useEffect(() => {
        const getCoordinate = (value, names) => {
            for (const name of names) {
                const candidate = value?.[name];
                if (Number.isInteger(candidate) && candidate >= 0)
                    return candidate;
            }
            return null;
        };
        const readPoint = (value) => {
            if (!value || typeof value !== 'object')
                return null;
            const row = getCoordinate(value, ['row', 'rowIndex', 'r']);
            const col = getCoordinate(value, ['col', 'column', 'colIndex', 'columnIndex', 'c']);
            return row !== null && col !== null ? { row, col } : null;
        };
        const onDeleteSelectedCells = (event) => {
            if (event.key !== 'Delete' && event.key !== 'Backspace')
                return;
            if (event.ctrlKey || event.metaKey || event.altKey)
                return;
            const target = event.target;
            if (!target?.closest('.opensheets-grid'))
                return;
            if (target.closest('input, textarea, [contenteditable="true"]'))
                return;
            const current = state;
            const data = current?.data;
            if (!data || typeof data.get !== 'function' || typeof data.set !== 'function')
                return;
            const selection = current.selection;
            const ranges = Array.isArray(selection?.ranges) ? selection.ranges : [];
            const bounds = [];
            // OpenSheets SelectionRect uses startRow/startCol/endRow/endCol.
            // Normalize each range so dragging in any direction clears the full selection.
            for (const range of ranges) {
                const startRow = getCoordinate(range, ['startRow']);
                const endRow = getCoordinate(range, ['endRow']);
                const startCol = getCoordinate(range, ['startCol']);
                const endCol = getCoordinate(range, ['endCol']);
                if (startRow !== null && endRow !== null && startCol !== null && endCol !== null) {
                    bounds.push({
                        startRow: Math.min(startRow, endRow),
                        endRow: Math.max(startRow, endRow),
                        startCol: Math.min(startCol, endCol),
                        endCol: Math.max(startCol, endCol),
                    });
                }
            }
            if (!bounds.length) {
                const active = readPoint(selection?.active);
                if (active)
                    bounds.push({ startRow: active.row, endRow: active.row, startCol: active.col, endCol: active.col });
            }
            if (!bounds.length)
                return;
            event.preventDefault();
            event.stopPropagation();
            const beforeData = new Map(data);
            const nextData = new Map(data);
            let changed = false;
            for (const boundsItem of bounds) {
                for (let row = boundsItem.startRow; row <= boundsItem.endRow; row++) {
                    for (let col = boundsItem.startCol; col <= boundsItem.endCol; col++) {
                        const key = keyOf(row, col);
                        const cell = nextData.get(key);
                        if (cell && (cell.value !== undefined || cell.formula !== undefined)) {
                            const cleared = { ...cell, value: null };
                            delete cleared.formula;
                            nextData.set(key, cleared);
                            changed = true;
                        }
                    }
                }
            }
            if (!changed)
                return;
            if (headerSelectionRef.current) {
                headerUndoRef.current.push({ before: beforeData, after: nextData });
                if (headerUndoRef.current.length > 100)
                    headerUndoRef.current.shift();
                headerRedoRef.current = [];
            }
            dispatch({ type: 'LOAD_STATE', payload: { ...current, data: nextData } });
            setMessage(headerSelectionRef.current
                ? `Selected ${headerSelectionRef.current.type === 'column' ? 'column' : 'row'} contents cleared. Click Save cell edits to save the changes.`
                : 'Selected cell contents cleared. Click Save cell edits to save the changes.');
        };
        window.addEventListener('keydown', onDeleteSelectedCells, true);
        return () => window.removeEventListener('keydown', onDeleteSelectedCells, true);
    }, [state, dispatch]);
    // Excel-style shortcuts for whole-row / whole-column selections. Normal
    // cell-selection shortcuts remain owned by OpenSheets.
    useEffect(() => {
        const onHeaderShortcut = async (event) => {
            if (!(event.ctrlKey || event.metaKey))
                return;
            const key = event.key.toLowerCase();
            const target = event.target;
            if (!target?.closest('.opensheets-grid'))
                return;
            if (target.closest('input, textarea, [contenteditable="true"]'))
                return;
            if (!headerSelectionRef.current)
                return;
            const current = state;
            const data = current?.data;
            if (!data || typeof data.get !== 'function')
                return;
            if (key === 'c') {
                const selection = headerSelectionRef.current;
                const maxRows = Math.max(1, Number(current.maxRows) || PAGE_SIZE + 1);
                const maxCols = Math.max(1, Number(current.maxCols) || 100);
                const startRow = selection.type === 'row' ? selection.index : 0;
                const endRow = selection.type === 'row' ? selection.index : maxRows - 1;
                const startCol = selection.type === 'column' ? selection.index : 0;
                const endCol = selection.type === 'column' ? selection.index : maxCols - 1;
                const lines = [];
                for (let row = startRow; row <= endRow; row++) {
                    const values = [];
                    for (let col = startCol; col <= endCol; col++) {
                        const cell = data.get(keyOf(row, col));
                        let value = cell?.value ?? '';
                        if (cell?.formula && String(cell.formula).startsWith('='))
                            value = cell.formula;
                        values.push(String(value ?? '').replace(/\t/g, ' ').replace(/\r?\n/g, ' '));
                    }
                    lines.push(values.join('\t'));
                }
                event.preventDefault();
                event.stopPropagation();
                try {
                    await navigator.clipboard.writeText(lines.join('\n'));
                    setMessage(`Copied selected ${selection.type}.`);
                }
                catch {
                    setMessage('Copy failed. Check browser clipboard permission.');
                }
                return;
            }
            if (key === 'z' && !event.shiftKey) {
                const item = headerUndoRef.current.pop();
                if (!item)
                    return;
                event.preventDefault();
                event.stopPropagation();
                headerRedoRef.current.push(item);
                dispatch({ type: 'LOAD_STATE', payload: { ...current, data: new Map(item.before) } });
                setMessage('Undo applied to selected row/column.');
                return;
            }
            if (key === 'y' || (key === 'z' && event.shiftKey)) {
                const item = headerRedoRef.current.pop();
                if (!item)
                    return;
                event.preventDefault();
                event.stopPropagation();
                headerUndoRef.current.push(item);
                dispatch({ type: 'LOAD_STATE', payload: { ...current, data: new Map(item.after) } });
                setMessage('Redo applied to selected row/column.');
            }
        };
        window.addEventListener('keydown', onHeaderShortcut, true);
        return () => window.removeEventListener('keydown', onHeaderShortcut, true);
    }, [state, dispatch]);
    // Excel-style continuous worksheet loading. The backend still sends rows in
    // 500-row chunks, but the worksheet itself is one continuous virtual sheet.
    // OpenSheets virtualizes the visible cells, so maxRows can represent the
    // complete dataset without rendering millions of DOM nodes.
    const mergeRowsToState = useCallback((rows, loadedColumns, offset) => {
        if (!rows.length)
            return;
        const current = stateRef.current;
        const currentData = current?.data instanceof Map ? current.data : new Map();
        const nextData = dataRowsToMap(rows, loadedColumns, offset + 1, currentData);
        const importLimit = effectiveImportLimit(importModeRef.current);
        const total = Math.min(Math.max(0, totalDatasetRowsRef.current || rowCount), importLimit);
        const worksheetRows = Math.max(1, total + 1 + EXTRA_EMPTY_ROWS);
        const worksheetCols = Math.max(1, (loadedColumns.length || columns.length || 1) + EXTRA_EMPTY_COLUMNS);
        dispatch({
            type: 'LOAD_STATE',
            payload: {
                ...current,
                data: nextData,
                maxRows: worksheetRows,
                maxCols: Math.max(Number(current?.maxCols) || 0, worksheetCols),
                rowHeights: current?.rowHeights?.length >= worksheetRows
                    ? current.rowHeights
                    : makeSparseRowHeights(worksheetRows),
                colWidths: current?.colWidths?.length
                    ? current.colWidths
                    : Array(Math.max(loadedColumns.length || columns.length || 1, 1)).fill(140),
            },
        });
        const fields = loadedColumns.map(column => column.field);
        rows.forEach((row, rowOffset) => {
            const spreadsheetRow = offset + rowOffset + 1;
            fields.forEach((field, col) => {
                baselineCellValuesRef.current.set(keyOf(spreadsheetRow, col), row[field] ?? null);
            });
        });
    }, [columns, dispatch, rowCount]);
    // Function: load chunk
    const loadChunk = useCallback(async (chunkIndex) => {
        if (!sessionId || chunkIndex < 0 || loadedChunkSetRef.current.has(chunkIndex))
            return;
        const importLimit = effectiveImportLimit(importModeRef.current);
        const maxDataRows = Math.min(totalDatasetRowsRef.current || rowCount || 0, importLimit);
        const offset = chunkIndex * PAGE_SIZE;
        // Preview mode is intentionally capped at exactly 1,000 DATA rows.
        // The additional 200 worksheet rows are empty cells and are never fetched.
        if (offset >= maxDataRows || loadedRowsCountRef.current >= effectiveImportLimit(importModeRef.current))
            return;
        loadedChunkSetRef.current.add(chunkIndex);
        loadingRowsRef.current = true;
        setLoadingPage(true);
        try {
            const limit = Math.min(PAGE_SIZE, maxDataRows - offset);
            const response = await fetch(`${apiBase}/api/rows/${sessionId}?offset=${offset}&limit=${limit}`);
            const data = await response.json();
            if (!response.ok)
                throw new Error(data.detail || 'Could not load spreadsheet rows');
            const rows = Array.isArray(data.rows) ? data.rows : [];
            const loadedColumns = (Array.isArray(data.columns) ? data.columns : columns.map(c => c.field))
                .map((field) => columns.find(column => column.field === field) || { field, headerName: field, type: 'text' });
            if (rows.length) {
                const allowedRows = importModeRef.current === 'preview'
                    ? rows.slice(0, Math.max(0, IMPORT_PREVIEW_ROWS - loadedRowsCountRef.current))
                    : rows;
                if (!allowedRows.length)
                    return;
                mergeRowsToState(allowedRows, loadedColumns, offset);
                loadedRowsCountRef.current = Math.min(maxDataRows, loadedRowsCountRef.current + allowedRows.length);
                setPageRows(previous => {
                    const next = [...previous];
                    // Keep pageRows as a compatibility cache for existing save/export UI,
                    // but do not use it as the worksheet's row source.
                    for (let i = 0; i < allowedRows.length; i++)
                        next[offset + i] = allowedRows[i];
                    return next;
                });
                baselineColumns.current = loadedColumns;
            }
            activeSession.current = sessionId;
            const backendTotal = Number(data.rowCount) || maxDataRows || loadedRowsCountRef.current;
            const total = Math.min(backendTotal, effectiveImportLimit(importModeRef.current));
            totalDatasetRowsRef.current = total;
            setMessage(importModeRef.current === 'preview'
                ? `Loaded ${loadedRowsCountRef.current.toLocaleString()} of ${total.toLocaleString()} dataset rows. 200 empty worksheet rows are available below.`
                : `Loaded ${loadedRowsCountRef.current.toLocaleString()} of ${total.toLocaleString()} dataset rows. Scroll anywhere to load more.`);
        }
        catch (error) {
            loadedChunkSetRef.current.delete(chunkIndex);
            setMessage(error instanceof Error ? error.message : 'Could not load spreadsheet rows.');
        }
        finally {
            loadingRowsRef.current = false;
            setLoadingPage(false);
        }
    }, [apiBase, columns, mergeRowsToState, rowCount, sessionId]);
    // Function: load chunks for scroll position
    const loadChunksForScrollPosition = useCallback(async (target) => {
        if (!sessionId)
            return;
        const total = totalDatasetRowsRef.current || rowCount || 0;
        if (!total)
            return;
        // OpenSheets uses the default 22px row height in this workbook. Include a
        // safety window so fast wheel/drag scrolling never outruns the loader.
        const firstVisibleSpreadsheetRow = Math.max(0, Math.floor(target.scrollTop / DEFAULT_ROW_HEIGHT));
        const viewportRows = Math.ceil(target.clientHeight / DEFAULT_ROW_HEIGHT);
        const firstDataRow = Math.max(0, firstVisibleSpreadsheetRow - 50);
        const lastDataRow = Math.min(total - 1, firstVisibleSpreadsheetRow + viewportRows + 100);
        const firstChunk = Math.floor(firstDataRow / PAGE_SIZE);
        const lastChunk = Math.floor(Math.max(firstDataRow, lastDataRow) / PAGE_SIZE);
        const chunks = [];
        for (let chunk = firstChunk; chunk <= lastChunk; chunk++) {
            if (!loadedChunkSetRef.current.has(chunk))
                chunks.push(chunk);
        }
        for (const chunk of chunks.slice(0, 3)) {
            await loadChunk(chunk);
        }
    }, [loadChunk, rowCount, sessionId]);
    // Run side effect when dependencies change
    useEffect(() => {
        let cancelled = false;
        async function loadInitialRows() {
            loadingRowsRef.current = true;
            setLoadingPage(true);
            loadedChunkSetRef.current.clear();
            baselineCellValuesRef.current.clear();
            loadedRowsCountRef.current = 0;
            if (!sessionId) {
                const initialAll = props.initialRows || [];
                const initial = initialAll.slice(0, effectiveImportLimit(importMode));
                totalDatasetRowsRef.current = initial.length;
                loadedRowsCountRef.current = initial.length;
                setPageRows(initial);
                baselineRows.current = initial.map(row => ({ ...row }));
                baselineColumns.current = columns;
                activeSession.current = '';
                const initialData = makeInitialData(initial, columns);
                columns.forEach((column, col) => {
                    initialData.set(keyOf(0, col), { value: column.headerName || column.field, format: { bold: true } });
                });
                dispatch({
                    type: 'LOAD_STATE',
                    payload: {
                        data: initialData,
                        maxRows: initial.length + 1 + EXTRA_EMPTY_ROWS,
                        maxCols: Math.max(columns.length + EXTRA_EMPTY_COLUMNS, 1),
                        selection: { ranges: [], active: null },
                        editing: null, formulaInput: '', readOnly: false,
                        rowHeights: makeSparseRowHeights(initial.length + 1 + EXTRA_EMPTY_ROWS),
                        colWidths: Array(Math.max(columns.length + EXTRA_EMPTY_COLUMNS, 1)).fill(140),
                        validation: new Map(),
                    },
                });
                loadedChunkSetRef.current.add(0);
                loadingRowsRef.current = false;
                setLoadingPage(false);
                return;
            }
            try {
                const response = await fetch(`${apiBase}/api/rows/${sessionId}?offset=0&limit=${PAGE_SIZE}`);
                const data = await response.json();
                if (!response.ok)
                    throw new Error(data.detail || 'Could not load rows');
                if (cancelled)
                    return;
                const loadedRows = Array.isArray(data.rows) ? data.rows : [];
                const loadedColumns = (Array.isArray(data.columns) ? data.columns : columns.map(c => c.field))
                    .map((field) => columns.find(column => column.field === field) || { field, headerName: field, type: 'text' });
                totalDatasetRowsRef.current = Number(data.rowCount) || rowCount || loadedRows.length;
                const visibleTotal = Math.min(effectiveImportLimit(importModeRef.current), totalDatasetRowsRef.current);
                // In preview mode the backend dataset may contain millions of rows,
                // but this workbook exposes exactly the first 1,000 DATA rows.
                // The +200 rows below are empty worksheet rows, not imported records.
                totalDatasetRowsRef.current = visibleTotal;
                loadedRowsCountRef.current = Math.min(loadedRows.length, visibleTotal);
                setPageRows(loadedRows.slice(0, visibleTotal));
                baselineRows.current = loadedRows.slice(0, visibleTotal).map(row => ({ ...row }));
                baselineColumns.current = loadedColumns;
                activeSession.current = sessionId;
                loadedChunkSetRef.current.add(0);
                const currentData = dataRowsToMap(loadedRows.slice(0, visibleTotal), loadedColumns, 1);
                loadedColumns.forEach((column, col) => {
                    currentData.set(keyOf(0, col), { value: column.headerName || column.field, format: { bold: true } });
                });
                const worksheetRows = Math.max(1, visibleTotal + 1 + EXTRA_EMPTY_ROWS);
                dispatch({
                    type: 'LOAD_STATE',
                    payload: {
                        data: currentData,
                        maxRows: worksheetRows,
                        maxCols: Math.max(loadedColumns.length + EXTRA_EMPTY_COLUMNS, 1),
                        selection: { ranges: [], active: null },
                        editing: null,
                        formulaInput: '',
                        readOnly: false,
                        rowHeights: makeSparseRowHeights(worksheetRows),
                        colWidths: Array(Math.max(loadedColumns.length, 1)).fill(140),
                        validation: new Map(),
                    },
                });
                loadedRows.slice(0, visibleTotal).forEach((row, rowOffset) => {
                    loadedColumns.forEach((column, col) => {
                        baselineCellValuesRef.current.set(keyOf(rowOffset + 1, col), row[column.field] ?? null);
                    });
                });
                setMessage(importMode === 'preview'
                    ? `Loaded ${loadedRowsCountRef.current.toLocaleString()} of ${visibleTotal.toLocaleString()} dataset rows. 200 empty worksheet rows are available below.`
                    : `Loaded ${loadedRowsCountRef.current.toLocaleString()} of ${visibleTotal.toLocaleString()} dataset rows. Scroll anywhere to load more.`);
            }
            catch (error) {
                if (!cancelled)
                    setMessage(error instanceof Error ? error.message : 'Could not load rows.');
            }
            finally {
                if (!cancelled) {
                    loadingRowsRef.current = false;
                    setLoadingPage(false);
                }
            }
        }
        void loadInitialRows();
        return () => {
            cancelled = true;
            loadingRowsRef.current = false;
        };
    }, [sessionId, apiBase, dispatch, refreshVersion, columns, props.initialRows, importMode, rowCount]);
    // Capture scrolling from the actual OpenSheets scroll container. Unlike the
    // old implementation, this is position-based: jumping directly to row
    // 10,000,000 loads the chunk containing that row instead of requiring the
    // user to scroll through every preceding 500-row chunk.
    useEffect(() => {
        const grid = gridRef.current;
        if (!grid)
            return;
        const onScroll = (event) => {
            const target = event.target;
            if (!target || !target.clientHeight)
                return;
            void loadChunksForScrollPosition(target);
        };
        grid.addEventListener('scroll', onScroll, true);
        return () => grid.removeEventListener('scroll', onScroll, true);
    }, [loadChunksForScrollPosition]);
    // Function: effective import limit
    const effectiveImportLimit = (mode) => {
        if (mode === 'preview')
            return IMPORT_PREVIEW_ROWS;
        if (mode === 'custom')
            return Math.max(1, Number(customRowCountRef.current || 1));
        return Number.MAX_SAFE_INTEGER;
    };
    // Component or function: perform import
    async function performImport(file, mode) {
        let progressTimer;
        try {
            importModeRef.current = mode;
            const requestedRows = mode === 'custom'
                ? Math.max(1, Math.floor(Number(customRowCountRef.current || 1)))
                : effectiveImportLimit(mode);
            totalDatasetRowsRef.current = mode === 'preview'
                ? Math.min(IMPORT_PREVIEW_ROWS, rowCount || IMPORT_PREVIEW_ROWS)
                : mode === 'custom'
                    ? requestedRows
                    : (rowCount || 0);
            loadedRowsCountRef.current = 0;
            loadedChunkSetRef.current.clear();
            onImportModeChange?.(mode);
            setShowImportChoice(false);
            setPendingImportFile(null);
            setImportLoading(true);
            setLoadingPage(true);
            setLoadingProgress(1);
            const label = mode === 'full'
                ? 'Importing whole dataset'
                : mode === 'custom'
                    ? `Importing first ${requestedRows.toLocaleString()} rows`
                    : 'Importing first 1,000 rows';
            setMessage(`${label}: ${file.name}...`);
            // Visual progress only. It provides feedback while the real upload/workbook
            // loading is happening; it is intentionally not a byte-accurate percentage.
            let visual = 1;
            progressTimer = window.setInterval(() => {
                visual = Math.min(92, visual + (visual < 30 ? 5 : visual < 70 ? 3 : 1));
                setLoadingProgress(visual);
            }, 180);
            await props.onUploadFile(file);
            setLoadingProgress(100);
            setMessage(`Uploaded ${file.name}. Loading workbook...`);
            window.setTimeout(() => {
                setImportLoading(false);
                setLoadingPage(false);
            }, 350);
        }
        catch (error) {
            if (progressTimer !== undefined)
                window.clearInterval(progressTimer);
            setLoadingProgress(100);
            setImportLoading(false);
            setLoadingPage(false);
            console.error('File upload failed:', error);
            setMessage(error instanceof Error
                ? `Upload failed: ${error.message}`
                : 'Upload failed. Check the browser console.');
        }
        finally {
            if (progressTimer !== undefined)
                window.clearInterval(progressTimer);
        }
    }
    // Component or function: handle import
    async function handleImport(file) {
        if (!file)
            return;
        // CSV row counts can be estimated without uploading the workbook. For CSV,
        // show the import choice only when the file actually exceeds 1,000 data rows.
        // XLSX/XLS files are opened by the backend, so we show the same safe choice
        // before upload rather than guessing their row count from file size.
        const lowerName = file.name.toLowerCase();
        if (lowerName.endsWith('.csv')) {
            try {
                const text = await file.text();
                const estimatedRows = Math.max(0, text.split(/\r?\n/).filter(line => line.trim() !== '').length - 1);
                if (estimatedRows <= IMPORT_PREVIEW_ROWS) {
                    onImportModeChange?.('full');
                    await performImport(file, 'full');
                    return;
                }
            }
            catch {
                // Fall back to the explicit choice if the CSV cannot be read locally.
            }
        }
        setPendingImportFile(file);
        setCustomRowCount('');
        customRowCountRef.current = 0;
        onCustomImportRowsChange?.(1);
        setShowImportChoice(true);
    }
    // Run side effect when dependencies change
    useEffect(() => {
        if (!fileToImport)
            return;
        void handleImport(fileToImport);
        onImportConsumed?.();
    }, [fileToImport]);
    // Component or function: handle replace all
    async function handleReplaceAll() {
        if (!sessionId) {
            setMessage('Find & Replace across the full dataset requires a workbook uploaded to AI Analyst.');
            return;
        }
        if (!findText) {
            setMessage('Enter text to find.');
            return;
        }
        if (!window.confirm(`Replace all occurrences of "${findText}" with "${replaceText}" across the entire dataset? This can be undone using the backend Undo action.`))
            return;
        setReplaceBusy(true);
        try {
            const response = await fetch(`${apiBase}/api/replace`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sessionId,
                    find: findText,
                    replaceWith: replaceText,
                    matchCase,
                    matchWholeCell,
                }),
            });
            const result = await response.json();
            if (!response.ok)
                throw new Error(result.detail || 'Find & Replace failed.');
            // The backend changed the complete dataset. Reset the continuous
            // worksheet so the first chunk reflects the new server-side values.
            setRefreshVersion(value => value + 1);
            setMessage(result.message || `Replaced ${result.cellsChanged ?? 0} cell(s) across the dataset.`);
        }
        catch (error) {
            setMessage(error instanceof Error ? `Find & Replace failed: ${error.message}` : 'Find & Replace failed.');
        }
        finally {
            setReplaceBusy(false);
        }
    }
    // Component or function: run column action
    async function runColumnAction(action) {
        if (!sessionId) {
            setMessage('Upload this workbook to AI Analyst before sorting or changing column types.');
            return;
        }
        if (!selectedColumn) {
            setMessage('Choose a column first.');
            return;
        }
        setColumnActionBusy(true);
        try {
            const isType = action === 'type';
            const response = await fetch(`${apiBase}/api/${isType ? 'type' : 'sort'}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(isType
                    ? { sessionId, column: selectedColumn, dataType: selectedDataType }
                    : { sessionId, column: selectedColumn, ascending: action === 'sort-asc' }),
            });
            const result = await response.json();
            if (!response.ok)
                throw new Error(result.detail || `Could not ${isType ? 'convert column type' : 'sort column'}.`);
            // The backend applies these actions to the entire dataset. Reload the visible page afterwards.
            setRefreshVersion(value => value + 1);
            setMessage(result.message || (isType
                ? `Changed ${selectedColumn} to ${selectedDataType}.`
                : `Sorted the full dataset by ${selectedColumn} (${action === 'sort-asc' ? 'ascending' : 'descending'}).`));
        }
        catch (error) {
            setMessage(error instanceof Error ? error.message : 'Column operation failed.');
        }
        finally {
            setColumnActionBusy(false);
        }
    }
    // Component or function: handle save page
    async function handleSavePage() {
        if (!sessionId || !onSaveCellEdits) {
            setMessage('Upload this workbook to AI Analyst before saving backend edits.');
            return;
        }
        try {
            setMessage('Checking edits...');
            const data = state?.data;
            if (!data || typeof data.get !== 'function')
                throw new Error('Spreadsheet data is not ready.');
            const edits = [];
            const fields = baselineColumns.current.map(column => column.field);
            for (let row = 0; row < baselineRows.current.length; row++) {
                for (let col = 0; col < fields.length; col++) {
                    const cell = data.get(keyOf(row + 1, col));
                    const nextValue = cell?.formula && String(cell.formula).startsWith('=')
                        ? evaluateFormula(cell.formula, (sourceRow, sourceCol) => data.get(keyOf(sourceRow, sourceCol)))
                        : (cell?.value ?? null);
                    const oldValue = baselineRows.current[row]?.[fields[col]] ?? null;
                    if (!Object.is(nextValue, oldValue)) {
                        edits.push({ rowIndex: row, column: fields[col], value: nextValue });
                    }
                }
            }
            if (!edits.length) {
                setMessage('No cell changes to save.');
                return;
            }
            await onSaveCellEdits(edits);
            // Re-baseline the current page after a successful save.
            const updatedRows = baselineRows.current.map(row => ({ ...row }));
            for (const edit of edits) {
                const localIndex = edit.rowIndex;
                if (updatedRows[localIndex])
                    updatedRows[localIndex][edit.column] = edit.value;
            }
            baselineRows.current = updatedRows;
            setPageRows(updatedRows);
            setMessage(`Saved ${edits.length} cell edit(s).`);
        }
        catch (error) {
            setMessage(error instanceof Error ? `Save failed: ${error.message}` : 'Save failed.');
        }
    }
    // Component or function: handle sync to ai
    async function handleSyncToAI() {
        try {
            setMessage('Sending current spreadsheet to AI Analyst...');
            const rows = readRowsFromState(state);
            if (!rows.length) {
                setMessage('No tabular data found. Make sure the first row contains column headers.');
                return;
            }
            await onSyncToAI(rows);
            setMessage(`Sent ${rows.length} data rows to AI Analyst.`);
        }
        catch (error) {
            console.error('OpenSheets sync failed:', error);
            setMessage(error instanceof Error ? `Sync failed: ${error.message}` : 'Sync failed. Check the browser console.');
        }
    }
    // Component or function: handle export
    function handleExport() {
        try {
            const sourceData = state?.data;
            if (!sourceData || typeof sourceData.entries !== 'function') {
                throw new Error('Spreadsheet data is not ready.');
            }
            /*
             * IMPORTANT:
             * OpenSheets keeps formulas in the cell object as `formula`. Some
             * versions of the OpenSheets Excel exporter can still write that
             * formula metadata into the XLSX even when includeFormulas=false.
             *
             * For this export button we want an Excel workbook containing the
             * CURRENT DISPLAYED VALUES, not OpenSheets formula strings.
             *
             * Build a separate export-only Map and remove formula metadata from
             * every cell. Formula cells are evaluated first so the exported XLSX
             * contains the calculated result.
             *
             * The live spreadsheet state is never modified.
             */
            const exportData = new Map();
            for (const [cellKey, rawCell] of sourceData.entries()) {
                if (!rawCell || typeof rawCell !== 'object') {
                    exportData.set(cellKey, rawCell);
                    continue;
                }
                const cell = { ...rawCell };
                if (cell.formula && String(cell.formula).trim().startsWith('=')) {
                    try {
                        const evaluatedValue = evaluateFormula(String(cell.formula), (sourceRow, sourceCol) => sourceData.get(keyOf(sourceRow, sourceCol)));
                        cell.value =
                            evaluatedValue === undefined || evaluatedValue === null
                                ? (cell.value ?? null)
                                : evaluatedValue;
                    }
                    catch (formulaError) {
                        // If a formula cannot be evaluated by OpenSheets, preserve its
                        // current cached value rather than exporting the formula text.
                        console.warn('Could not evaluate formula during Excel export:', formulaError);
                        cell.value = cell.value ?? null;
                    }
                }
                // Never send formula metadata to the XLSX exporter.
                delete cell.formula;
                exportData.set(cellKey, cell);
            }
            exportToExcel(exportData, 'spreadsheet.xlsx', {
                sheetName: 'Sheet1',
                includeFormulas: false,
                includeFormatting: true,
                title: 'AI Analyst Workbook',
            });
            setMessage('Excel export started with calculated values.');
        }
        catch (error) {
            console.error('Excel export failed:', error);
            setMessage(error instanceof Error
                ? `Export failed: ${error.message}`
                : 'Export failed. Check the browser console.');
        }
    }
    // Function: open chart dialog
    const openChartDialog = (type) => {
        setSelectedChartId(null);
        setChartDialogType(type || 'column');
        setShowChartDialog(true);
    };
    return (<div className="opensheets-page" style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
      <ExcelRibbon activeTab={activeRibbonTab} setActiveTab={setActiveRibbonTab} state={state} dispatch={dispatch} setMessage={setMessage} selectedColumn={selectedColumn} setSelectedColumn={setSelectedColumn} selectedDataType={selectedDataType} setSelectedDataType={setSelectedDataType} columnActionBusy={columnActionBusy} loadingPage={loadingPage} isBackendWorkbook={isBackendWorkbook} syncing={syncing} showFindReplace={showFindReplace} setShowFindReplace={setShowFindReplace} handleImport={handleImport} handleExport={handleExport} handleSavePage={handleSavePage} handleSyncToAI={handleSyncToAI} handleReplaceAll={handleReplaceAll} replaceBusy={replaceBusy} findText={findText} setFindText={setFindText} replaceText={replaceText} setReplaceText={setReplaceText} matchCase={matchCase} setMatchCase={setMatchCase} matchWholeCell={matchWholeCell} setMatchWholeCell={setMatchWholeCell} runColumnAction={runColumnAction} onOpenChartDialog={openChartDialog} onRowsChanged={(rows) => {
            setPageRows(rows);
            baselineRows.current = rows.map(row => ({ ...row }));
        }}/>

      {showFindReplace && (<div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                flexWrap: 'wrap',
                padding: '7px 12px',
                borderBottom: '1px solid #ddd',
                background: '#fff',
                fontSize: 12,
            }}>
          <strong style={{ fontSize: 11, color: '#444' }}>Find & Replace</strong>
          <label style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            Find
            <input value={findText} onChange={event => setFindText(event.target.value)} placeholder="Text to find" style={{ width: 180, height: 28, border: '1px solid #bbb', borderRadius: 3, padding: '0 8px' }}/>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            Replace with
            <input value={replaceText} onChange={event => setReplaceText(event.target.value)} placeholder="Replacement text" style={{ width: 180, height: 28, border: '1px solid #bbb', borderRadius: 3, padding: '0 8px' }}/>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={matchCase} onChange={event => setMatchCase(event.target.checked)}/>
            Match case
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={matchWholeCell} onChange={event => setMatchWholeCell(event.target.checked)}/>
            Match whole cell
          </label>
          <button type="button" disabled={replaceBusy || loadingPage || !findText || !isBackendWorkbook} onClick={() => void handleReplaceAll()} style={{ height: 28, padding: '0 12px', border: '1px solid #107c41', background: '#107c41', color: '#fff', borderRadius: 3, cursor: 'pointer' }}>
            {replaceBusy ? 'Replacing…' : 'Replace all'}
          </button>
          <span style={{ fontSize: 10, color: '#777' }}>
            {isBackendWorkbook ? 'Runs across the complete dataset.' : 'Upload to AI Analyst to use full-dataset replace.'}
          </span>
        </div>)}

      {isBackendWorkbook && (<div className="excel-statusbar">
          <span className="status-main">{loadingPage ? 'Loading rows…' : message}</span>
          <span>{rowCount ? `${Math.min(loadedRowsCountRef.current, importMode === 'preview' ? IMPORT_PREVIEW_ROWS : (totalDatasetRowsRef.current || rowCount)).toLocaleString()} of ${(importMode === 'preview' ? Math.min(IMPORT_PREVIEW_ROWS, rowCount || totalDatasetRowsRef.current) : (totalDatasetRowsRef.current || rowCount)).toLocaleString()} dataset rows loaded` : `${loadedRowsCountRef.current} dataset rows`}</span>
          {importMode === 'full' && (totalDatasetRowsRef.current || rowCount) > loadedRowsCountRef.current && (<span style={{ color: '#666' }}>Scroll anywhere to load more rows</span>)}
          {importMode === 'preview' && (<span style={{ color: '#666' }}>1,000 imported rows + 200 empty worksheet rows</span>)}
        </div>)}

      <FormulaBar />

      <div style={{ position: 'relative', flex: '1 1 auto', minHeight: 0, overflow: 'hidden' }}>
        <div ref={gridRef} className="opensheets-grid" style={{ width: '100%', height: '100%', overflow: 'hidden', minHeight: 0 }}>
          <SpreadsheetGrid />
        </div>
        {chartObjects.map(chart => (<ChartPreview key={chart.id} chart={chart} state={state} selected={selectedChartId === chart.id} onSelect={() => setSelectedChartId(chart.id)} onMove={(x, y) => setChartObjects(items => items.map(item => item.id === chart.id ? { ...item, x: Math.max(0, x), y: Math.max(0, y) } : item))}/>))}
        {selectedChartId && (<div style={{ position: 'absolute', left: 12, top: 12, zIndex: 41, display: 'flex', gap: 4, background: '#fff', border: '1px solid #bbb', borderRadius: 3, padding: 5, boxShadow: '0 2px 8px rgba(0,0,0,.12)' }}>
            <button type="button" onClick={() => setShowChartDialog(true)} style={{ height: 28, border: '1px solid #bbb', background: '#fff', borderRadius: 3 }}>Select Data</button>
            <button type="button" onClick={() => setShowChartDialog(true)} style={{ height: 28, border: '1px solid #bbb', background: '#fff', borderRadius: 3 }}>Change Chart Type</button>
            <button type="button" onClick={() => setChartObjects(items => items.map(item => item.id === selectedChartId ? { ...item, legend: !item.legend } : item))} style={{ height: 28, border: '1px solid #bbb', background: '#fff', borderRadius: 3 }}>Legend</button>
            <button type="button" onClick={() => setSelectedChartId(null)} style={{ height: 28, border: '1px solid #bbb', background: '#fff', borderRadius: 3 }}>Done</button>
          </div>)}
        {selectedChartId && (<div style={{ position: 'absolute', right: 12, top: 12, zIndex: 40, display: 'flex', gap: 5, background: '#fff', border: '1px solid #bbb', borderRadius: 3, padding: 5, boxShadow: '0 2px 8px rgba(0,0,0,.12)' }}>
            <button type="button" onClick={() => setShowChartDialog(true)} style={{ height: 28, border: '1px solid #bbb', background: '#fff', borderRadius: 3 }}>Change Chart</button>
            <button type="button" onClick={() => { setChartObjects(items => items.filter(item => item.id !== selectedChartId)); setSelectedChartId(null); }} style={{ height: 28, border: '1px solid #c00', color: '#b00000', background: '#fff', borderRadius: 3 }}>Delete</button>
          </div>)}
      </div>
      {importLoading && (<div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(255,255,255,.58)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ width: 430, maxWidth: 'calc(100vw - 32px)', background: '#fff', border: '1px solid #d0d7de', borderRadius: 10, boxShadow: '0 12px 40px rgba(0,0,0,.18)', padding: 24, fontFamily: 'Segoe UI, Arial, sans-serif' }}>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 8 }}>Loading dataset</div>
            <div style={{ fontSize: 12, color: '#666', marginBottom: 16 }}>Please wait while the workbook is being prepared.</div>
            <div style={{ height: 10, background: '#e9ecef', borderRadius: 999, overflow: 'hidden' }}>
              <div style={{ width: `${Math.max(1, Math.min(100, loadingProgress))}%`, height: '100%', background: '#107c41', transition: 'width .18s ease' }}/>
            </div>
            <div style={{ textAlign: 'center', marginTop: 12, fontSize: 22, fontWeight: 700, color: '#107c41' }}>
              {Math.round(loadingProgress)}%
            </div>
          </div>
        </div>)}

      {showImportChoice && pendingImportFile && (<div style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(0,0,0,.28)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ width: 460, maxWidth: 'calc(100vw - 32px)', background: '#fff', borderRadius: 8, boxShadow: '0 12px 40px rgba(0,0,0,.25)', border: '1px solid #d6d6d6', padding: 20, fontFamily: 'Segoe UI, Arial, sans-serif' }}>
            <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 6 }}>Import Dataset</div>
            <div style={{ fontSize: 12, color: '#666', marginBottom: 18, wordBreak: 'break-word' }}>{pendingImportFile.name}</div>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>How would you like to import this data?</div>
            <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: 11, border: '1px solid #d8d8d8', borderRadius: 6, marginBottom: 8, cursor: 'pointer' }}>
              <input type="radio" name="opensheets-import-mode" checked={importMode === 'preview'} onChange={() => onImportModeChange?.('preview')}/>
              <span><strong>Import first 1,000 rows</strong><br /><span style={{ color: '#666', fontSize: 11 }}>Fast preview mode. Only the first 1,000 dataset rows are made available in the worksheet.</span></span>
            </label>
            <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: 11, border: '1px solid #d8d8d8', borderRadius: 6, cursor: 'pointer' }}>
              <input type="radio" name="opensheets-import-mode" checked={importMode === 'full'} onChange={() => onImportModeChange?.('full')}/>
              <span><strong>Import whole data</strong><br /><span style={{ color: '#666', fontSize: 11 }}>Keep the complete dataset available with continuous virtual scrolling.</span></span>
            </label>
            <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: 11, border: '1px solid #d8d8d8', borderRadius: 6, cursor: 'pointer', marginTop: 8 }}>
              <input type="radio" name="opensheets-import-mode" checked={importMode === 'custom'} onChange={() => onImportModeChange?.('custom')}/>
              <span style={{ flex: 1 }}>
                <strong>Import custom number of rows</strong><br />
                <span style={{ color: '#666', fontSize: 11 }}>
                  Choose exactly how many dataset rows you want available in the worksheet.
                </span>
                {importMode === 'custom' && (<input type="number" min={1} step={1} value={customRowCount} onChange={event => {
                    const value = event.target.value;
                    setCustomRowCount(value);
                    const parsed = Math.max(0, Math.floor(Number(value || 0)));
                    customRowCountRef.current = parsed;
                    onCustomImportRowsChange?.(parsed);
                }} placeholder="e.g. 5000" style={{ marginTop: 8, width: 130, height: 30, border: '1px solid #bbb', borderRadius: 4, padding: '0 8px' }} autoFocus/>)}
              </span>
            </label>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}>
              <button type="button" onClick={() => { setShowImportChoice(false); setPendingImportFile(null); }} style={{ height: 34, padding: '0 14px', border: '1px solid #bbb', background: '#fff', borderRadius: 4 }}>Cancel</button>
              <button type="button" onClick={() => {
                if (importMode === 'custom') {
                    const count = Math.floor(Number(customRowCount));
                    if (!Number.isFinite(count) || count < 1) {
                        setMessage('Enter a valid custom row count (at least 1).');
                        return;
                    }
                    customRowCountRef.current = count;
                    onCustomImportRowsChange?.(count);
                }
                void performImport(pendingImportFile, importMode);
            }} style={{ height: 34, padding: '0 16px', border: '1px solid #107c41', background: '#107c41', color: '#fff', borderRadius: 4, fontWeight: 600 }}>
                Import
              </button>
            </div>
          </div>
        </div>)}

      {showChartDialog && (<ChartInsertDialog state={state} initialRange={selectedChartId ? (chartObjects.find(item => item.id === selectedChartId)?.range || selectionToChartRange(state.selection)) : selectionToChartRange(state.selection)} initialType={chartDialogType} initialChart={selectedChartId ? (chartObjects.find(item => item.id === selectedChartId) || null) : null} onClose={() => setShowChartDialog(false)} onInsert={chart => {
                setChartObjects(items => selectedChartId ? items.map(item => item.id === selectedChartId ? { ...item, ...chart, id: item.id } : item) : [...items, chart]);
                setSelectedChartId(null);
                setShowChartDialog(false);
                setMessage(selectedChartId ? 'Chart updated.' : 'Chart inserted on the worksheet.');
            }}/>)}
    </div>);
}
// Component or function: open sheets view
export default function OpenSheetsView(props) {
    // State: 
    const [importMode, setImportMode] = useState('full');
    // State: 
    const [customImportRows, setCustomImportRows] = useState(1);
    // Computed value: initial data
    const initialData = useMemo(() => makeInitialData(props.initialRows || [], props.columns), [props.initialRows, props.columns]);
    return (<SpreadsheetProvider spreadsheetId="ai-analyst-opensheets-workbook-v3" persistence="local" autoSave initialData={initialData} maxRows={Math.max((importMode === 'preview'
            ? Math.min(IMPORT_PREVIEW_ROWS, props.rowCount || IMPORT_PREVIEW_ROWS)
            : (props.rowCount || IMPORT_PREVIEW_ROWS)) + 1 + EXTRA_EMPTY_ROWS, 1 + EXTRA_EMPTY_ROWS)} maxCols={Math.max((props.columns?.length || 1) + EXTRA_EMPTY_COLUMNS, 1)}>
      <SpreadsheetWorkspace {...props} importMode={importMode} onImportModeChange={setImportMode} customImportRows={customImportRows} onCustomImportRowsChange={setCustomImportRows}/>
    </SpreadsheetProvider>);
}
