// Imports
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import OpenSheetsView from './components/OpenSheetsView';
import DataPilotHome from './pages/DataPilotHome';
import DataQualityPage from './pages/DataQualityPage';
import { FileSpreadsheet, Search, Save, Upload, Download, Trash2, Bot, Send, Sparkles, Database, ChevronDown, X, Check, PlusCircle, Settings, Paperclip, Copy, ShieldCheck } from 'lucide-react';
// Value: api
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
// Start with an empty workbook. Users choose when to import their own data.
const initialWorkbook = {
    sessionId: '',
    filename: 'Untitled workbook',
    columns: [],
    rows: [],
    rowCount: 0,
    columnCount: 0,
    missingCount: 0,
    duplicateCount: 0,
    history: [],
    formulas: {}
};
// Component or function: load saved workbook
function loadSavedWorkbook() {
    // Workbook sessions are intentionally tab-scoped and RAM-only on the backend.
    return initialWorkbook;
}
// Component or function: notify session closed
function notifySessionClosed(sessionId) {
    if (!sessionId || typeof navigator === 'undefined')
        return;
    // Value: url
    const url = `${API}/api/session/${encodeURIComponent(sessionId)}/close`;
    try {
        const body = new Blob([], { type: 'text/plain' });
        const queued = navigator.sendBeacon ? navigator.sendBeacon(url, body) : false;
        if (!queued) {
            void fetch(url, { method: 'POST', body, keepalive: true });
        }
    }
    catch (error) {
        // The backend's 30-minute inactivity cleanup is the fallback.
        console.warn('Could not notify backend that workbook tab closed:', error);
    }
}
// Component or function: post
async function post(path, body) {
    // Value: response
    const response = await fetch(`${API}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    // Value: data
    const data = await response.json();
    if (!response.ok)
        throw new Error(data.detail || 'Request failed');
    return data;
}
// Render AI responses as safe Markdown without adding a frontend dependency.
// Raw HTML is escaped; only Markdown-generated tags are inserted.
function escapeMarkdownHtml(value) {
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
// Component or function: render inline markdown
function renderInlineMarkdown(source) {
    // Value: code
    const code = [];
    let value = escapeMarkdownHtml(source).replace(/`([^`]+)`/g, (_match, text) => {
        const token = `@@INLINECODE${code.length}@@`;
        code.push(`<code>${text}</code>`);
        return token;
    });
    value = value.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|mailto:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    value = value.replace(/\*\*(.+?)\*\*|__(.+?)__/g, '<strong>$1$2</strong>');
    value = value.replace(/~~(.+?)~~/g, '<del>$1</del>');
    value = value.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!_)_([^_\n]+)_(?!_)/g, '<em>$1$2</em>');
    value = value.replace(/@@INLINECODE(\d+)@@/g, (_match, index) => code[Number(index)] || '');
    // Defensive cleanup: never expose internal inline-code placeholders in the UI.
    value = value.replace(/@@INLINE\*CODE\*(\d+)@@/g, (_match, index) => code[Number(index)] || '');
    value = value.replace(/@@INLINE_CODE_(\d+)@@/g, (_match, index) => code[Number(index)] || '');
    return value;
}
// Component or function: markdown to html
function markdownToHtml(markdown) {
    // Value: lines
    const lines = String(markdown || '').replace(/\r\n?/g, '\n').split('\n');
    // Value: output
    const output = [];
    let paragraph = [];
    let listType = null;
    let codeLines = null;
    // Function: flush paragraph
    const flushParagraph = () => {
        if (paragraph.length) {
            output.push(`<p>${paragraph.map(renderInlineMarkdown).join('<br />')}</p>`);
            paragraph = [];
        }
    };
    // Function: close list
    const closeList = () => {
        if (listType) {
            output.push(`</${listType}>`);
            listType = null;
        }
    };
    // Function: is table row
    const isTableRow = (line) => line.trim().startsWith('|') && line.trim().endsWith('|');
    // Function: cells
    const cells = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '')
        .split(/(?<!\\)\|/).map(cell => cell.replace(/\\\|/g, '|').trim());
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (line.trim().startsWith('```') || line.trim().startsWith('~~~')) {
            flushParagraph();
            closeList();
            if (codeLines) {
                output.push(`<pre><code>${escapeMarkdownHtml(codeLines.join('\n'))}</code></pre>`);
                codeLines = null;
            }
            else
                codeLines = [];
            continue;
        }
        if (codeLines) {
            codeLines.push(line);
            continue;
        }
        if (isTableRow(line) && i + 1 < lines.length && /^\|?\s*:?-{3,}/.test(lines[i + 1].trim())) {
            flushParagraph();
            closeList();
            const headers = cells(line);
            i += 1;
            const rows = [];
            while (i + 1 < lines.length && isTableRow(lines[i + 1])) {
                rows.push(cells(lines[++i]));
            }
            output.push(`<div class="ai-markdown-table-wrap"><table><thead><tr>${headers.map(cell => `<th>${renderInlineMarkdown(cell)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${headers.map((_h, index) => `<td>${renderInlineMarkdown(row[index] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
            continue;
        }
        const heading = line.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
            flushParagraph();
            closeList();
            const level = heading[1].length;
            output.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
            continue;
        }
        if (/^\s*([-*_]\s*){3,}$/.test(line)) {
            flushParagraph();
            closeList();
            output.push('<hr />');
            continue;
        }
        const listMatch = line.match(/^\s*(?:([-*+]|\d+[.)]))\s+(.+)$/);
        if (listMatch) {
            flushParagraph();
            const nextType = /^\d/.test(listMatch[1]) ? 'ol' : 'ul';
            if (listType !== nextType) {
                closeList();
                output.push(`<${nextType}>`);
                listType = nextType;
            }
            output.push(`<li>${renderInlineMarkdown(listMatch[2])}</li>`);
            continue;
        }
        if (!line.trim()) {
            flushParagraph();
            closeList();
            continue;
        }
        closeList();
        paragraph.push(line);
    }
    if (codeLines)
        output.push(`<pre><code>${escapeMarkdownHtml(codeLines.join('\n'))}</code></pre>`);
    flushParagraph();
    closeList();
    return output.join('');
}
// Component or function: markdown message
function MarkdownMessage({ text }) {
    // Computed value: html
    const html = useMemo(() => markdownToHtml(text), [text]);
    return <div className="ai-markdown" dangerouslySetInnerHTML={{ __html: html }}/>;
}
// Component or function: extract monthly revenue
function extractMonthlyRevenue(text) {
    // Value: points
    const points = [];
    // Value: row pattern
    const rowPattern = /^\|\s*(\d{4}-\d{2})\s*\|\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*\|/;
    for (const line of String(text || '').split(/\r?\n/)) {
        const match = line.trim().match(rowPattern);
        if (!match)
            continue;
        const revenue = Number(match[2].replace(/,/g, ''));
        if (Number.isFinite(revenue))
            points.push({ month: match[1], revenue });
    }
    return points;
}
// Component or function: monthly revenue trend chart
function MonthlyRevenueTrendChart({ text }) {
    // Computed value: points
    const points = useMemo(() => extractMonthlyRevenue(text), [text]);
    if (points.length < 2)
        return null;
    // Value: width
    const width = 760, height = 290, left = 76, right = 22, top = 24, bottom = 54;
    // Value: plot width
    const plotWidth = width - left - right, plotHeight = height - top - bottom;
    // Function: values
    const values = points.map(point => point.revenue);
    // Value: min value
    const minValue = Math.min(0, ...values), maxValue = Math.max(...values);
    // Value: range
    const range = Math.max(1, maxValue - minValue);
    // Function: x
    const x = (index) => left + (index / (points.length - 1)) * plotWidth;
    // Function: y
    const y = (value) => top + ((maxValue - value) / range) * plotHeight;
    // Function: line points
    const linePoints = points.map((point, index) => `${x(index)},${y(point.revenue)}`).join(' ');
    // Function: ticks
    const ticks = Array.from({ length: 5 }, (_, index) => maxValue - (range * index) / 4);
    // Function: compact
    const compact = (value) => Math.abs(value) >= 1_000_000
        ? `${(value / 1_000_000).toFixed(1)}M`
        : Math.abs(value) >= 1_000 ? `${(value / 1_000).toFixed(0)}K` : value.toFixed(0);
    // Value: label step
    const labelStep = Math.max(1, Math.ceil(points.length / 8));
    // Function: highest
    const highest = points.reduce((best, point) => point.revenue > best.revenue ? point : best, points[0]);
    return (<section className="ai-trend-chart" aria-label="Monthly revenue trend chart">
      <div className="ai-trend-chart-heading">
        <div><strong>Monthly revenue trend</strong><span>{points.length} months · values from the table above</span></div>
        <div className="ai-trend-chart-peak"><small>Peak month</small><b>{highest.month}</b></div>
      </div>
      <div className="ai-trend-chart-scroll">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Line chart of monthly revenue">
          {ticks.map((tick, index) => (<g key={`tick-${index}`}>
              <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} className="ai-trend-gridline"/>
              <text x={left - 10} y={y(tick) + 4} textAnchor="end" className="ai-trend-axis-label">{compact(tick)}</text>
            </g>))}
          <polyline points={linePoints} className="ai-trend-line"/>
          {points.map((point, index) => (<circle key={point.month} cx={x(index)} cy={y(point.revenue)} r="3.5" className="ai-trend-point">
              <title>{`${point.month}: ${point.revenue.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}</title>
            </circle>))}
          {points.map((point, index) => ((index === 0 || index === points.length - 1 || index % labelStep === 0) &&
            <text key={`month-${point.month}`} x={x(index)} y={height - 20} textAnchor="middle" className="ai-trend-axis-label">{point.month}</text>))}
        </svg>
      </div>
      <div className="ai-trend-chart-footnote">
        Highest: {highest.month} · {highest.revenue.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
      </div>
    </section>);
}
// Component or function: app
export default function App() {
    // State: 
    const [wb, setWb] = useState(loadSavedWorkbook);
    // State: 
    const [formulaMap, setFormulaMap] = useState(() => loadSavedWorkbook().formulas || {});
    // State: 
    const [search, setSearch] = useState('');
    // State: 
    const [question, setQuestion] = useState('');
    // State: 
    const [chat, setChat] = useState([]);
    // State: 
    const [copiedMessageIndex, setCopiedMessageIndex] = useState(null);
    // Provider selection is sent with every AI request. Auto preserves the backend fallback chain.
    const [selectedProvider, setSelectedProvider] = useState('auto');
    // State: 
    const [busy, setBusy] = useState(false);
    // State: 
    const [, setNotice] = useState('Ready');
    // State: 
    const [dialog, setDialog] = useState('');
    // State: 
    const [col, setCol] = useState('UnitPrice');
    // State: 
    const [newName, setNewName] = useState('');
    // State: 
    const [newValue, setNewValue] = useState('');
    // State: 
    const [expr, setExpr] = useState('Quantity * UnitPrice');
    // State: 
    const [type, setType] = useState('Decimal number');
    // State: 
    const [editedRows, setEditedRows] = useState(null);
    // State: 
    const [, setExtraRows] = useState(100);
    // State: 
    const [, setExtraCols] = useState(20);
    // OpenSheets is the primary spreadsheet editor. The previous AG Grid remains
    // available as a legacy view while its transformation tools are retained.
    const [activePage, setActivePage] = useState('ai');
    // State: 
    const [fileToImport, setFileToImport] = useState(null);
    // AI Settings: the API key exists only in React memory while editing.
    // It is never written to localStorage/sessionStorage or returned by the backend.
    const [aiMode, setAiMode] = useState('current');
    // State: 
    const [aiSettingsProvider, setAiSettingsProvider] = useState('gemini');
    // State: 
    const [aiSettingsApiKey, setAiSettingsApiKey] = useState('');
    // State: 
    const [aiSettingsModel, setAiSettingsModel] = useState('');
    // State: 
    const [aiSettingsModels, setAiSettingsModels] = useState([]);
    // State: 
    const [aiSettingsHasKey, setAiSettingsHasKey] = useState(false);
    // State: 
    const [aiSettingsLoading, setAiSettingsLoading] = useState(false);
    // State: 
    const [aiSettingsTesting, setAiSettingsTesting] = useState(false);
    // State: 
    const [aiSettingsSaving, setAiSettingsSaving] = useState(false);
    // State: 
    const [aiSettingsMessage, setAiSettingsMessage] = useState('');
    // State: 
    const [aiSettingsError, setAiSettingsError] = useState('');
    // Ref: file ref
    const fileRef = useRef(null);
    // App-level history is required because AG Grid's internal undo stack does not
    // know about formula recalculation or React-managed row data.
    const undoStack = useRef([]);
    // Ref: redo stack
    const redoStack = useRef([]);
    // Ref: rename header handler
    const renameHeaderHandler = useRef(async () => { });
    // Clear the active workbook without deleting the original file on the user's device
    // or disturbing the separate AI conversation history.
    const clearDataset = () => {
        if (!wb.sessionId && wb.columns.length === 0 && wb.rows.length === 0)
            return;
        const confirmed = window.confirm(`Clear ${wb.filename || 'the current workbook'} and return to a blank sheet? Your original file will not be deleted.`);
        if (!confirmed)
            return;
        notifySessionClosed(wb.sessionId);
        const emptyWorkbook = { ...initialWorkbook, columns: [], rows: [], formulas: {} };
        setWb(emptyWorkbook);
        setFormulaMap({});
        setEditedRows(null);
        setFileToImport(null);
        undoStack.current = [];
        redoStack.current = [];
        setNotice('Dataset cleared. The blank workbook is ready.');
    };
    // Function: snapshot current
    const snapshotCurrent = () => ({
        rows: (editedRows || wb.rows).map(row => ({ ...row })),
        formulas: { ...formulaMap }
    });
    // Function: apply history snapshot
    const applyHistorySnapshot = (snapshot) => {
        const rows = snapshot.rows.map(row => ({ ...row }));
        setEditedRows(rows);
        setFormulaMap({ ...snapshot.formulas });
        setWb(current => ({ ...current, formulas: { ...snapshot.formulas } }));
        setNotice('Edit history restored. Click Apply grid edits to save.');
    };
    // Function: undo workbook edit
    const undoWorkbookEdit = () => {
        const previous = undoStack.current.pop();
        if (!previous) {
            setNotice('Nothing to undo.');
            return;
        }
        redoStack.current.push(snapshotCurrent());
        applyHistorySnapshot(previous);
    };
    // Function: redo workbook edit
    const redoWorkbookEdit = () => {
        const next = redoStack.current.pop();
        if (!next) {
            setNotice('Nothing to redo.');
            return;
        }
        undoStack.current.push(snapshotCurrent());
        applyHistorySnapshot(next);
    };
    // Function: refresh
    const refresh = (next) => {
        setWb(next);
        setFormulaMap(next.formulas || {});
        setEditedRows(null);
        setNotice(next.message || 'Changes saved to working dataset');
    };
    // Workbook sessions belong to this browser tab. Notify the backend on tab close
    // or navigation; the backend also expires abandoned sessions after 30 minutes.
    useEffect(() => {
        if (!wb.sessionId)
            return;
        const closeThisTabSession = () => notifySessionClosed(wb.sessionId);
        window.addEventListener('pagehide', closeThisTabSession);
        return () => window.removeEventListener('pagehide', closeThisTabSession);
    }, [wb.sessionId]);
    // Function: load aisettings
    const loadAISettings = useCallback(async () => {
        try {
            const response = await fetch(`${API}/api/settings/ai`);
            const data = await response.json();
            if (!response.ok)
                throw new Error(data.detail || 'Could not load AI settings.');
            const mode = data.mode === 'custom' ? 'custom' : 'current';
            setAiMode(mode);
            setAiSettingsProvider(['gemini', 'groq', 'openrouter', 'deepseek', 'perplexity', 'openai', 'anthropic'].includes(data.provider) ? data.provider : 'gemini');
            setAiSettingsModel(String(data.model || ''));
            setAiSettingsHasKey(Boolean(data.has_api_key));
            // Never hydrate the API key from the backend.
            setAiSettingsApiKey('');
        }
        catch (error) {
            setAiSettingsError(error instanceof Error ? error.message : 'Could not load AI settings.');
        }
    }, []);
    // Run side effect when dependencies change
    useEffect(() => {
        void loadAISettings();
    }, [loadAISettings]);
    // Function: fetch aisettings models
    const fetchAISettingsModels = async () => {
        if (!aiSettingsApiKey.trim()) {
            setAiSettingsError('Enter the API key first.');
            return;
        }
        setAiSettingsLoading(true);
        setAiSettingsError('');
        setAiSettingsMessage('');
        try {
            const data = await post('/api/settings/ai/models', { provider: aiSettingsProvider, api_key: aiSettingsApiKey.trim() });
            setAiSettingsModels(Array.isArray(data.models) ? data.models : []);
            if (!aiSettingsModel && data.models?.[0]?.id)
                setAiSettingsModel(data.models[0].id);
            setAiSettingsMessage(`${data.models?.length || 0} compatible model(s) found.`);
        }
        catch (error) {
            setAiSettingsError(error instanceof Error ? error.message : 'Could not fetch models.');
        }
        finally {
            setAiSettingsLoading(false);
        }
    };
    // Function: test aisettings connection
    const testAISettingsConnection = async () => {
        if (!aiSettingsApiKey.trim() || !aiSettingsModel.trim()) {
            setAiSettingsError('Enter an API key and model ID before testing.');
            return;
        }
        setAiSettingsTesting(true);
        setAiSettingsError('');
        setAiSettingsMessage('');
        try {
            const data = await post('/api/settings/ai/test', {
                provider: aiSettingsProvider,
                model: aiSettingsModel.trim(),
                api_key: aiSettingsApiKey.trim()
            });
            setAiSettingsMessage(data.message || 'Connection successful.');
        }
        catch (error) {
            setAiSettingsError(error instanceof Error ? error.message : 'Connection test failed.');
        }
        finally {
            setAiSettingsTesting(false);
        }
    };
    // Function: save aisettings
    const saveAISettings = async (mode) => {
        setAiSettingsSaving(true);
        setAiSettingsError('');
        setAiSettingsMessage('');
        try {
            if (mode === 'custom') {
                if (!aiSettingsApiKey.trim()) {
                    setAiSettingsError(aiSettingsHasKey
                        ? 'Enter the API key again to save this custom configuration.'
                        : 'Enter an API key before saving custom mode.');
                    return;
                }
                if (!aiSettingsModel.trim()) {
                    setAiSettingsError('Enter or select a model ID before saving.');
                    return;
                }
            }
            const data = await post('/api/settings/ai', {
                mode,
                provider: mode === 'custom' ? aiSettingsProvider : '',
                model: mode === 'custom' ? aiSettingsModel.trim() : '',
                api_key: mode === 'custom' ? aiSettingsApiKey.trim() : ''
            });
            setAiMode(data.mode);
            setAiSettingsHasKey(Boolean(data.has_api_key));
            if (mode === 'current') {
                setAiSettingsApiKey('');
                setAiSettingsModel('');
                setAiSettingsModels([]);
            }
            setAiSettingsMessage(mode === 'custom'
                ? `Custom ${data.provider || aiSettingsProvider} model saved.`
                : 'Our Current Project mode is active.');
        }
        catch (error) {
            setAiSettingsError(error instanceof Error ? error.message : 'Could not save AI settings.');
        }
        finally {
            setAiSettingsSaving(false);
        }
    };
    // Use one window-level handler so Ctrl+Z works even when AG Grid, the formula
    // bar, or a cell editor owns focus. The application history is authoritative.
    useEffect(() => {
        const onWorkbookShortcut = (event) => {
            const target = event.target;
            const inGrid = !!target?.closest('.ag-root-wrapper');
            const inFormulaBar = !!target?.closest('.formula-row');
            if (!inGrid && !inFormulaBar)
                return;
            if (!(event.ctrlKey || event.metaKey) || event.altKey)
                return;
            const key = event.key.toLowerCase();
            if (key === 'z' && !event.shiftKey) {
                event.preventDefault();
                event.stopPropagation();
                event.stopImmediatePropagation();
                undoWorkbookEdit();
            }
            else if (key === 'y' || (key === 'z' && event.shiftKey)) {
                event.preventDefault();
                event.stopPropagation();
                event.stopImmediatePropagation();
                redoWorkbookEdit();
            }
        };
        window.addEventListener('keydown', onWorkbookShortcut, true);
        return () => window.removeEventListener('keydown', onWorkbookShortcut, true);
    }, [editedRows, wb, formulaMap]);
    // Function: upload
    const upload = async (file) => {
        if (!file)
            return;
        setBusy(true);
        try {
            const form = new FormData();
            form.append('file', file);
            const response = await fetch(`${API}/api/upload`, {
                method: 'POST',
                body: form
            });
            const data = await response.json();
            if (!response.ok)
                throw new Error(data.detail || 'Upload failed');
            if (wb.sessionId)
                notifySessionClosed(wb.sessionId);
            refresh(data);
            setExtraRows(100);
            setExtraCols(20);
            setNotice(`Loaded ${file.name}`);
        }
        catch (error) {
            setNotice(`Upload error: ${error instanceof Error ? error.message : String(error)}`);
        }
        finally {
            setBusy(false);
        }
    };
    // Function: action
    const action = async (path, body = {}) => {
        if (!wb.sessionId) {
            setNotice('Upload a dataset to enable transformations.');
            return;
        }
        setBusy(true);
        try {
            refresh(await post(path, {
                sessionId: wb.sessionId,
                ...body
            }));
        }
        catch (error) {
            setNotice(error instanceof Error ? error.message : 'Action failed');
        }
        finally {
            setBusy(false);
        }
    };
    renameHeaderHandler.current = async (field, nextName) => {
        if (!field || !nextName.trim())
            return;
        await action('/api/rename', { oldName: field, newName: nextName.trim() });
    };
    // Function: save cell edits
    const saveCellEdits = async (edits) => {
        if (!wb.sessionId)
            throw new Error('Upload a dataset before saving cell edits.');
        if (!edits.length)
            return;
        // The endpoint patches the named cells in the full backend DataFrame.
        // Row indexes are absolute dataset indexes, not page-local indexes.
        const updated = await post('/api/edit-cells', {
            sessionId: wb.sessionId,
            edits,
        });
        refresh(updated);
    };
    // Send the current OpenSheets workbook to the existing Python backend as CSV.
    // This creates/updates the backend session used by the existing AI chat.
    const syncOpenSheetsToAI = async (rows) => {
        if (!rows.length) {
            setNotice('The OpenSheets workbook is empty. Import data first.');
            throw new Error('No data rows found in the spreadsheet.');
        }
        const headers = Object.keys(rows[0]);
        if (!headers.length) {
            setNotice('No column headers were found in the OpenSheets workbook.');
            throw new Error('No column headers were found.');
        }
        // Escape commas, quotation marks, and actual line breaks in CSV values.
        const csvValue = (value) => {
            if (value === null || value === undefined)
                return '';
            const raw = String(value);
            return /[",\r\n]/.test(raw)
                ? `"${raw.replace(/"/g, '""')}"`
                : raw;
        };
        // Use real CRLF line endings so the backend CSV parser sees each row separately.
        const csv = [
            headers.map(csvValue).join(','),
            ...rows.map(row => headers.map(header => csvValue(row[header])).join(','))
        ].join('\r\n');
        const hasData = rows.some(row => headers.some(header => {
            const value = row[header];
            return value !== null && value !== undefined && String(value).trim() !== '';
        }));
        if (!csv.trim() || !hasData) {
            setNotice('The spreadsheet has headers but no non-empty data rows.');
            throw new Error('Dataset has no data rows.');
        }
        setBusy(true);
        setNotice('Sending OpenSheets data to AI Analyst...');
        try {
            const form = new FormData();
            form.append('file', new File([csv], 'opensheets-workbook.csv', { type: 'text/csv' }));
            const response = await fetch(`${API}/api/upload`, {
                method: 'POST',
                body: form
            });
            const responseText = await response.text();
            let data = {};
            try {
                data = responseText ? JSON.parse(responseText) : {};
            }
            catch {
                throw new Error(`Backend returned an unreadable response (HTTP ${response.status}).`);
            }
            if (!response.ok) {
                const detail = typeof data.detail === 'string'
                    ? data.detail
                    : `Upload failed (HTTP ${response.status})`;
                throw new Error(detail);
            }
            if (wb.sessionId)
                notifySessionClosed(wb.sessionId);
            refresh(data);
            setNotice(`OpenSheets data synced to AI Analyst (${rows.length} rows). You can now ask questions in the AI Analyst.`);
        }
        catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            setNotice(`Sync failed: ${message}`);
            throw error;
        }
        finally {
            setBusy(false);
        }
    };
    // Function: copy airesponse
    const copyAIResponse = async (text, messageIndex) => {
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(text);
            }
            else {
                const textArea = document.createElement('textarea');
                textArea.value = text;
                textArea.setAttribute('readonly', '');
                textArea.style.position = 'fixed';
                textArea.style.opacity = '0';
                document.body.appendChild(textArea);
                textArea.select();
                const copied = document.execCommand('copy');
                document.body.removeChild(textArea);
                if (!copied)
                    throw new Error('Copy command was not successful');
            }
            setCopiedMessageIndex(messageIndex);
            window.setTimeout(() => {
                setCopiedMessageIndex(current => current === messageIndex ? null : current);
            }, 1800);
        }
        catch (error) {
            console.error('Could not copy AI response:', error);
            setNotice('Could not copy the response. Please select and copy the text manually.');
        }
    };
    // Function: ask ai
    const askAI = async (text = question) => {
        if (!text.trim() || busy)
            return;
        const requestStartedAt = performance.now();
        const previousHistory = chat.slice(-12).map(message => ({
            role: message.role === 'user' ? 'user' : 'assistant',
            content: message.text
        }));
        setChat(c => [...c, { role: 'user', text }]);
        setQuestion('');
        setBusy(true);
        try {
            const requestBody = {
                question: text,
                history: previousHistory,
                // Custom mode is strict: the backend uses only the saved custom provider/model.
                // Current mode keeps the existing provider dropdown and fallback chain unchanged.
                provider: aiMode === 'custom' ? 'custom' : selectedProvider
            };
            // Validate the tab's in-memory workbook session before attaching it to chat.
            // The backend may have removed it after the inactivity timeout.
            let activeSessionId = wb.sessionId;
            if (activeSessionId) {
                const sessionCheck = await fetch(`${API}/api/session/${encodeURIComponent(activeSessionId)}`);
                if (sessionCheck.status === 404) {
                    activeSessionId = '';
                    const emptyWorkbook = { ...initialWorkbook };
                    setWb(emptyWorkbook);
                    setFormulaMap({});
                    setEditedRows(null);
                    setNotice('The previous dataset session expired. General AI chat is still available; upload the dataset again for data analysis.');
                }
                else if (!sessionCheck.ok) {
                    throw new Error(`Could not validate the dataset session (HTTP ${sessionCheck.status}). Please check the backend connection.`);
                }
            }
            // No valid workbook session means this is general AI chat. Do not send
            // an expired ID, otherwise the backend tries dataset analysis and returns 404.
            if (activeSessionId)
                requestBody.sessionId = activeSessionId;
            const data = await post('/api/ask', requestBody);
            setChat(c => [
                ...c,
                {
                    role: 'assistant',
                    text: data.details?.error
                        ? `${data.answer}\n\nTechnical details: ${data.details.error}`
                        : data.answer,
                    elapsedMs: Math.round(performance.now() - requestStartedAt),
                    provider: data.details?.provider_result?.provider || data.details?.provider || data.provider,
                },
            ]);
        }
        catch (error) {
            setChat(c => [...c, {
                    role: 'assistant',
                    text: error instanceof Error ? error.message : 'AI request failed',
                    elapsedMs: Math.round(performance.now() - requestStartedAt),
                }]);
        }
        finally {
            setBusy(false);
        }
    };
    // Function: apply dialog
    const applyDialog = async () => {
        if (dialog === 'rename')
            await action('/api/rename', { oldName: col, newName });
        if (dialog === 'remove')
            await action('/api/remove-column', { column: col });
        if (dialog === 'type')
            await action('/api/type', { column: col, dataType: type });
        if (dialog === 'formula')
            await action('/api/add-column', { name: newName, expression: expr });
        if (dialog === 'missing')
            await action('/api/replace-missing', { column: col, value: newValue });
        setDialog('');
    };
    // Function: export file
    const exportFile = (format) => {
        if (!wb.sessionId) {
            const blob = new Blob([JSON.stringify(wb.rows, null, 2)], {
                type: 'application/json'
            });
            const anchor = document.createElement('a');
            anchor.href = URL.createObjectURL(blob);
            anchor.download = 'sample-preview.json';
            anchor.click();
            URL.revokeObjectURL(anchor.href);
            return;
        }
        window.open(`${API}/api/download/${wb.sessionId}?format=${format}`, '_blank');
    };
    if (window.location.pathname === '/' || window.location.pathname === '/index.html') {
        return <DataPilotHome />;
    }
    return (<div className="app-shell">
      <style>{`
        /* Excel worksheet coordinates: column letters above the real field headers. */
        .ag-theme-quartz .excel-letter-header .ag-header-group-cell-label { justify-content:center; }
        .ag-theme-quartz .excel-letter-header { background:var(--ag-header-background-color, #f8f9fa); border-right:1px solid var(--ag-border-color, #d9d9d9); font-weight:500; }
        .ag-theme-quartz .excel-row-number-header { background:var(--ag-header-background-color, #f8f9fa); }
        .ag-theme-quartz .excel-row-number { text-align:center; color:var(--ag-secondary-foreground-color, #666); background:var(--ag-header-background-color, #f8f9fa); border-right:1px solid var(--ag-border-color, #d9d9d9); }
        /* Header labels rename inline on double-click; sorting remains in the menu. */
        .ag-theme-quartz .ag-sort-indicator-container { display: none !important; }
        .ag-theme-quartz .inline-rename-header { display:flex; align-items:center; gap:4px; width:100%; min-width:0; height:100%; }
        .ag-theme-quartz .inline-rename-header-label { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:default; }
        .ag-theme-quartz .inline-rename-header-input { flex:1; min-width:0; width:100%; height:24px; box-sizing:border-box; border:1px solid #16834a; border-radius:2px; padding:2px 4px; font:inherit; outline:none; }
        .ag-theme-quartz .inline-header-icon { display:flex; align-items:center; justify-content:center; flex:0 0 18px; width:18px; height:24px; padding:0; border:0; background:transparent; color:var(--ag-secondary-foreground-color, #666); cursor:pointer; font-size:15px; }
        .ag-theme-quartz .inline-header-icon:hover { background:var(--ag-row-hover-color, #eee); }
        .formula-input-wrap { position:relative; display:flex; flex:1 1 auto; min-width:0; height:100%; }
        .formula-input-wrap > input { width:100%; min-width:0; }
        .formula-suggestions { position:absolute; z-index:1000; top:calc(100% + 4px); left:0; width:min(420px, 90vw); max-height:280px; overflow:auto; background:var(--ag-background-color, #fff); color:var(--ag-foreground-color, #222); border:1px solid var(--ag-border-color, #d0d7de); border-radius:6px; box-shadow:0 8px 24px rgba(0,0,0,.16); padding:4px; }
        .formula-suggestions button { display:grid; grid-template-columns:100px 1fr; gap:2px 10px; width:100%; text-align:left; padding:8px 10px; border:0; border-radius:4px; background:transparent; color:inherit; cursor:pointer; }
        .formula-suggestions button.active, .formula-suggestions button:hover { background:var(--ag-row-hover-color, #eef5ff); }
        .formula-suggestion-name { font-weight:600; }
        .formula-suggestion-description { font-size:12px; opacity:.8; }
        .formula-suggestions small { grid-column:1 / -1; font-size:11px; opacity:.7; }
        .workspace-page-nav { display:flex; align-items:center; gap:8px; padding:10px 22px; background:#fff; border-bottom:1px solid #e5e7eb; }
        .workspace-page-nav button { display:flex; align-items:center; gap:8px; border:0; border-radius:8px; background:transparent; color:#374151; padding:10px 16px; cursor:pointer; font-weight:500; }
        .workspace-page-nav button.active { background:#e8f5ed; color:#087b43; }
        .ai-chat-page,.dashboard-page { min-height:0; height:calc(100vh - 185px); overflow:auto; background:#f7f8fa; padding:24px; box-sizing:border-box; }
        .ai-chat-shell { max-width:1000px; height:100%; min-height:420px; margin:0 auto; display:flex; flex-direction:column; background:white; border:1px solid #e5e7eb; border-radius:16px; overflow:hidden; }
        .ai-chat-header { display:flex; align-items:center; gap:12px; padding:18px 22px; border-bottom:1px solid #e5e7eb; }
        .ai-chat-avatar { width:42px; height:42px; display:grid; place-items:center; border-radius:12px; background:#e8f5ed; color:#087b43; }
        .ai-chat-header h1,.dashboard-heading h1 { margin:0; font-size:22px; } .ai-chat-header p,.dashboard-heading p { margin:5px 0 0; color:#6b7280; font-size:13px; }
        .ai-chat-messages { flex:1; overflow:auto; padding:22px; }
        .ai-empty-state,.dashboard-empty { text-align:center; max-width:560px; margin:70px auto; color:#4b5563; }
        .ai-empty-state h2,.dashboard-empty h2 { color:#111827; } .ai-suggestions { display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin-top:18px; }
        .ai-suggestions button { padding:10px 12px; background:#fff; border:1px solid #d1d5db; border-radius:10px; cursor:pointer; }
        .ai-message { max-width:82%; padding:12px 16px; margin:0 0 14px; border-radius:12px; white-space:pre-wrap; overflow-wrap:anywhere; }
        .ai-message.user { margin-left:auto; background:#e8f5ed; }
        .ai-message.assistant { background:#f3f4f6; }
        .ai-message-meta { display:flex; align-items:center; gap:9px; margin-bottom:8px; }
        .ai-response-actions { display:flex; align-items:center; gap:8px; margin-top:10px; }
        .ai-copy-button { display:inline-flex; align-items:center; gap:6px; padding:5px 7px; border:0; border-radius:6px; background:transparent; color:#6b7280; font-size:12px; cursor:pointer; }
        .ai-copy-button:hover { background:#f3f4f6; color:#202123; }
        .ai-copy-button svg { flex:none; }
        .ai-provider-badge { display:inline-flex; padding:3px 8px; border-radius:999px; background:#e8f5ed; color:#087b43; font-size:11px; font-weight:600; }
        .ai-trend-chart { margin:16px 0 8px; padding:14px; background:#fff; border:1px solid #e5e7eb; border-radius:12px; white-space:normal; }
        .ai-trend-chart-heading { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:8px; }
        .ai-trend-chart-heading > div:first-child { display:flex; flex-direction:column; gap:3px; }
        .ai-trend-chart-heading strong { color:#111827; font-size:14px; }
        .ai-trend-chart-heading span,.ai-trend-chart-peak small,.ai-trend-chart-footnote { color:#6b7280; font-size:11px; }
        .ai-trend-chart-peak { display:flex; flex-direction:column; align-items:flex-end; gap:2px; }
        .ai-trend-chart-peak b { color:#087b43; font-size:12px; }
        .ai-trend-chart-scroll { width:100%; overflow-x:auto; }
        .ai-trend-chart svg { display:block; width:100%; min-width:560px; height:auto; }
        .ai-trend-gridline { stroke:#e5e7eb; stroke-width:1; }
        .ai-trend-axis-label { fill:#6b7280; font-size:10px; }
        .ai-trend-line { fill:none; stroke:#16834a; stroke-width:3; stroke-linecap:round; stroke-linejoin:round; }
        .ai-trend-point { fill:#16834a; stroke:#fff; stroke-width:1.5; }
        .ai-trend-chart-footnote { margin-top:4px; }

        .ai-markdown { margin-top:6px; line-height:1.6; white-space:normal; overflow-wrap:anywhere; }
        .ai-markdown > :first-child { margin-top:0; }
        .ai-markdown > :last-child { margin-bottom:0; }
        .ai-markdown p { margin:8px 0; }
        .ai-markdown h1,.ai-markdown h2,.ai-markdown h3,.ai-markdown h4 { margin:16px 0 8px; line-height:1.3; color:#111827; }
        .ai-markdown h1 { font-size:1.35em; } .ai-markdown h2 { font-size:1.2em; } .ai-markdown h3,.ai-markdown h4 { font-size:1.08em; }
        .ai-markdown ul,.ai-markdown ol { margin:8px 0; padding-left:24px; }
        .ai-markdown li { margin:4px 0; }
        .ai-markdown code { padding:2px 5px; border-radius:4px; background:#e5e7eb; font-family:Consolas,monospace; font-size:.92em; }
        .ai-markdown pre { margin:10px 0; padding:12px; overflow:auto; border-radius:8px; background:#111827; color:#f9fafb; white-space:pre; }
        .ai-markdown pre code { padding:0; background:transparent; color:inherit; }
        .ai-markdown a { color:#087bca; text-decoration:underline; }
        .ai-markdown blockquote { margin:10px 0; padding:4px 12px; border-left:3px solid #9ca3af; color:#4b5563; }
        .ai-markdown hr { border:0; border-top:1px solid #d1d5db; margin:14px 0; }
        .ai-markdown-table-wrap { max-width:100%; overflow-x:auto; margin:10px 0; }
        .ai-markdown table { width:100%; border-collapse:collapse; font-size:13px; white-space:normal; }
        .ai-markdown th,.ai-markdown td { border:1px solid #d1d5db; padding:7px 9px; text-align:left; vertical-align:top; }
        .ai-markdown th { background:#e5e7eb; font-weight:600; }
        .ai-markdown tr:nth-child(even) td { background:rgba(0,0,0,.025); }
        .ai-chat-composer { display:flex; gap:10px; align-items:flex-end; padding:14px; border-top:1px solid #e5e7eb; }
        .ai-chat-composer textarea { flex:1; resize:vertical; min-height:48px; max-height:140px; padding:12px; border:1px solid #d1d5db; border-radius:10px; font:inherit; }
        .ai-chat-composer button { display:flex; align-items:center; gap:8px; padding:12px 16px; }
        .dashboard-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:22px; } .dashboard-heading button { padding:10px 14px; border:1px solid #d1d5db; background:white; border-radius:8px; cursor:pointer; }
        .dashboard-kpis { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; }
        .dashboard-kpis article,.dashboard-section { background:white; border:1px solid #e5e7eb; border-radius:12px; padding:20px; }
        .dashboard-kpis article span,.dashboard-kpis article small { display:block; color:#6b7280; } .dashboard-kpis article strong { display:block; margin:12px 0; font-size:30px; color:#111827; }
        .dashboard-section { margin-top:20px; } .dashboard-fields { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; } .dashboard-fields span { padding:10px 12px; border:1px solid #e5e7eb; border-radius:8px; background:#f9fafb; } .dashboard-fields small { display:block; color:#6b7280; margin-top:4px; }
        @media(max-width:800px) { .dashboard-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } .ai-chat-page,.dashboard-page { padding:12px; } }
        /* Fiesta-inspired dark workspace shell */
        .app-shell { min-height:100vh; background:#0b0d12; color:#e5e7eb; }
        .titlebar { background:#10131b !important; color:#f8fafc !important; border-bottom:1px solid #252a36 !important; }
        .titlebar .filename,.titlebar .saved { color:#a1a1aa !important; }
        .titlebar .top-search input { background:#191e29 !important; color:#e5e7eb !important; border:1px solid #303747 !important; }
        .workspace-page-nav { background:#10131b !important; border-bottom:1px solid #252a36 !important; }
        .workspace-page-nav button { color:#aeb6c5 !important; }
        .workspace-page-nav button.active { background:#26203b !important; color:#c4b5fd !important; }
        .ai-chat-page { height:calc(100vh - 126px) !important; padding:0 !important; background:#0b0d12 !important; }
        .ai-chat-shell { max-width:none !important; height:100% !important; min-height:0 !important; border:0 !important; border-radius:0 !important; background:#0b0d12 !important; display:grid !important; grid-template-columns:248px minmax(0,1fr) !important; overflow:hidden !important; }
        .fiesta-chat-sidebar { background:#10131b; border-right:1px solid #252a36; padding:16px 12px; display:flex; flex-direction:column; gap:16px; min-width:0; }
        .fiesta-new-chat { display:flex; align-items:center; gap:10px; width:100%; border:1px solid #343b4b; background:#191e29; color:#f8fafc; border-radius:10px; padding:11px 12px; cursor:pointer; font-weight:600; }
        .fiesta-new-chat:hover,.fiesta-history-item:hover { background:#222938; }
        .fiesta-sidebar-label { color:#747f91; text-transform:uppercase; font-size:10px; letter-spacing:.12em; padding:4px 8px; }
        .fiesta-history-item { width:100%; text-align:left; border:0; background:transparent; color:#c1c8d4; border-radius:8px; padding:10px 9px; font-size:12px; cursor:pointer; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .fiesta-sidebar-bottom { margin-top:auto; border-top:1px solid #252a36; padding-top:12px; color:#8d96a6; font-size:12px; display:flex; align-items:center; gap:8px; }
        .ai-chat-main { display:flex; flex-direction:column; min-width:0; min-height:0; background:#0b0d12; }
        .ai-chat-header { padding:15px 24px !important; border-bottom:1px solid #252a36 !important; color:#f8fafc; }
        .ai-chat-avatar { background:#29213f !important; color:#c4b5fd !important; }
        .ai-chat-header h1 { color:#f8fafc; font-size:16px !important; }
        .ai-chat-header p { color:#8791a2 !important; }
        .fiesta-model-select { margin-left:auto; display:flex; align-items:center; gap:8px; background:#171c27; border:1px solid #303747; color:#d8deea; border-radius:9px; padding:8px 10px; font-size:12px; }
        .fiesta-model-select select { background:transparent; color:inherit; border:0; outline:none; font:inherit; max-width:190px; }
        .fiesta-model-select option { background:#171c27; }
        .ai-chat-messages { padding:28px 6vw !important; color:#dbe1eb; }
        .ai-empty-state { margin:10vh auto !important; color:#9ba5b5 !important; }
        .ai-empty-state h2 { color:#f4f5f8 !important; font-size:24px; }
        .ai-empty-state p { color:#8993a4; }
        .ai-suggestions button { background:#151a24 !important; color:#c8d0dc !important; border:1px solid #303747 !important; border-radius:12px !important; }
        .ai-suggestions button:hover { background:#222938 !important; border-color:#7060a7 !important; }
        .ai-message { color:#e5e7eb; }
        .ai-message.user { background:#252039 !important; color:#f4f0ff; }
        .ai-message.assistant { background:#151a24 !important; border:1px solid #252c39; }
        .ai-copy-button { color:#9ba5b5 !important; }
        .ai-copy-button:hover { background:#252c39 !important; color:#f3f4f6 !important; }
        .ai-markdown h1,.ai-markdown h2,.ai-markdown h3,.ai-markdown h4 { color:#f3f4f6 !important; }
        .ai-markdown code { background:#252c39 !important; color:#e5e7eb; }
        .ai-chat-composer { margin:0 auto 18px; width:min(900px,calc(100% - 48px)); border:1px solid #353d4c !important; border-radius:16px; background:#151a24; padding:10px !important; box-shadow:0 10px 40px #0005; }
        .ai-chat-composer textarea { background:transparent !important; color:#f8fafc !important; border:0 !important; outline:none; min-height:48px; }
        .ai-chat-composer textarea::placeholder { color:#758094; }
        .ai-chat-composer button.primary { background:#8b5cf6 !important; border:0; border-radius:10px; color:white; }
        .dashboard-page { height:calc(100vh - 126px) !important; background:#0b0d12 !important; color:#e5e7eb; }
        .dashboard-heading h1 { color:#f8fafc; }
        .dashboard-heading p { color:#8993a4 !important; }
        .dashboard-heading button { background:#171c27 !important; border-color:#303747 !important; color:#dce2ec; }
        .dashboard-kpis article,.dashboard-section,.fiesta-chart-card { background:#121722 !important; border:1px solid #283141 !important; color:#e5e7eb; border-radius:14px !important; }
        .dashboard-kpis article span,.dashboard-kpis article small { color:#8791a2 !important; }
        .dashboard-kpis article strong { color:#f8fafc !important; }
        .dashboard-section h2,.fiesta-chart-card h3 { color:#f3f4f6; }
        .dashboard-section p,.fiesta-chart-title p { color:#8791a2; }
        .dashboard-fields span { background:#191f2b !important; border-color:#303747 !important; color:#dce2ec; }
        .dashboard-fields small { color:#8791a2 !important; }
        .fiesta-dashboard-grid { display:grid; grid-template-columns:1.5fr 1fr; gap:16px; margin-top:16px; }
        .fiesta-chart-card { padding:18px; min-width:0; }
        .fiesta-chart-title { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }
        .fiesta-chart-title h3 { margin:0; font-size:14px; font-weight:650; }
        .fiesta-chart-title p { margin:5px 0 0; font-size:11px; }
        .fiesta-chart-title button { background:#1b2230; border:1px solid #303747; color:#aeb8c8; border-radius:7px; padding:5px; }
        .fiesta-bars { height:210px; display:flex; align-items:stretch; gap:12px; padding:18px 4px 0; overflow-x:auto; }
        .fiesta-bar-col { min-width:42px; flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; gap:7px; }
        .fiesta-bar-col strong { color:#9ba6b8; font-size:9px; font-weight:500; white-space:nowrap; }
        .fiesta-bar-track { height:145px; width:min(34px,100%); background:#1d2634; border-radius:7px 7px 3px 3px; display:flex; align-items:flex-end; overflow:hidden; }
        .fiesta-bar-track i { display:block; width:100%; min-height:3px; border-radius:7px 7px 2px 2px; background:linear-gradient(180deg,#a78bfa,#6d4bd1); }
        .fiesta-bar-col span { color:#8791a2; font-size:9px; max-width:68px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .fiesta-donut-layout { display:flex; align-items:center; gap:24px; padding:20px 8px 8px; }
        .fiesta-donut { width:142px; height:142px; border-radius:50%; display:grid; place-items:center; flex:none; }
        .fiesta-donut > div { width:88px; height:88px; border-radius:50%; background:#121722; display:flex; flex-direction:column; align-items:center; justify-content:center; }
        .fiesta-donut b { font-size:23px; color:#f8fafc; }.fiesta-donut small { color:#8791a2; font-size:10px; }
        .fiesta-legend { flex:1; min-width:0; display:grid; gap:10px; }
        .fiesta-legend div { display:grid; grid-template-columns:9px minmax(0,1fr) auto; gap:8px; align-items:center; font-size:10px; color:#aeb8c8; }
        .fiesta-legend i { width:8px; height:8px; border-radius:3px; }.fiesta-legend span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.fiesta-legend b { color:#e5e7eb; }
        .fiesta-chart-empty { padding:55px 12px; color:#8791a2; font-size:12px; text-align:center; }
        .fiesta-data-note { margin-top:12px; color:#8791a2; font-size:11px; }
        @media(max-width:900px) { .ai-chat-shell { grid-template-columns:1fr !important; } .fiesta-chat-sidebar { display:none; } .fiesta-dashboard-grid { grid-template-columns:1fr; } }
        @media(max-width:800px) { .dashboard-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); } .ai-chat-page,.dashboard-page { padding:12px; } .fiesta-model-select { display:none; } }
        /* Layout correction: use the full viewport and remove the duplicate page tabs in chat mode. */
        html, body, #root { width:100%; min-width:0; min-height:100%; margin:0; }
        .app-shell { width:100% !important; min-width:0 !important; min-height:100vh !important; overflow:hidden; }
        .ai-chat-page { display:block !important; position:relative !important; inset:auto !important; width:100% !important; max-width:none !important; height:calc(100vh - 62px) !important; min-height:0 !important; margin:0 !important; padding:0 !important; box-sizing:border-box !important; }
        .ai-chat-shell { display:grid !important; position:relative !important; inset:auto !important; width:100% !important; max-width:none !important; height:100% !important; min-height:0 !important; margin:0 !important; padding:0 !important; grid-template-columns:260px minmax(0,1fr) !important; }
        .fiesta-chat-sidebar { width:auto !important; min-width:0 !important; }
        .ai-chat-main { width:100% !important; min-width:0 !important; max-width:none !important; }
        .ai-chat-header { width:100% !important; box-sizing:border-box !important; padding:18px 26px !important; }
        .ai-chat-messages { width:100% !important; min-width:0 !important; box-sizing:border-box !important; padding:28px clamp(20px,5vw,72px) !important; }
        .ai-chat-composer { width:min(1100px,calc(100% - 64px)) !important; max-width:1100px !important; box-sizing:border-box !important; }
        @media(max-width:900px) { .ai-chat-shell { grid-template-columns:1fr !important; } .fiesta-chat-sidebar { display:none !important; } .ai-chat-composer { width:calc(100% - 24px) !important; } }

        /* ChatGPT-inspired light theme: white canvas, soft gray surfaces, subtle borders. */
        .app-shell { background:#ffffff !important; color:#202123 !important; }
        .titlebar { background:#ffffff !important; color:#202123 !important; border-bottom:1px solid #e5e7eb !important; }
        .titlebar .filename,.titlebar .saved { color:#6b7280 !important; }
        .titlebar .top-search input { background:#f9fafb !important; color:#202123 !important; border:1px solid #e5e7eb !important; }
        .workspace-page-nav { background:#ffffff !important; border-bottom:1px solid #e5e7eb !important; }
        .workspace-page-nav button { color:#4b5563 !important; }
        .workspace-page-nav button.active { background:#f3f4f6 !important; color:#111827 !important; }
        .ai-chat-page { background:#ffffff !important; }
        .ai-chat-shell { background:#ffffff !important; }
        .fiesta-chat-sidebar { background:#f9fafb !important; border-right:1px solid #e5e7eb !important; color:#202123 !important; }
        .fiesta-new-chat { background:#ffffff !important; color:#202123 !important; border:1px solid #d1d5db !important; }
        .fiesta-new-chat:hover,.fiesta-history-item:hover { background:#f3f4f6 !important; }
        .fiesta-sidebar-label { color:#6b7280 !important; }
        .fiesta-history-item { color:#374151 !important; }
        .fiesta-sidebar-bottom { border-top:1px solid #e5e7eb !important; color:#6b7280 !important; }
        .ai-chat-main { background:#ffffff !important; }
        .ai-chat-header { background:#ffffff !important; color:#202123 !important; border-bottom:1px solid #f0f0f0 !important; }
        .ai-chat-avatar { background:#f3f4f6 !important; color:#374151 !important; }
        .ai-chat-header h1 { color:#202123 !important; }
        .ai-chat-header p { color:#6b7280 !important; }
        .fiesta-model-select { background:#ffffff !important; border:1px solid #e5e7eb !important; color:#374151 !important; }
        .fiesta-model-select select,.fiesta-model-select option { background:#ffffff !important; color:#374151 !important; }
        .ai-chat-messages { background:#ffffff !important; color:#202123 !important; }
        .ai-empty-state { color:#4b5563 !important; }
        .ai-empty-state h2 { color:#202123 !important; }
        .ai-empty-state p { color:#6b7280 !important; }
        .ai-suggestions button { background:#ffffff !important; color:#374151 !important; border:1px solid #e5e7eb !important; border-radius:999px !important; }
        .ai-suggestions button:hover { background:#f9fafb !important; border-color:#cbd5e1 !important; }
        .ai-message { color:#202123 !important; }
        .ai-message.user { background:#f4f4f4 !important; color:#202123 !important; border-radius:18px !important; }
        .ai-message.assistant { background:transparent !important; border:0 !important; color:#202123 !important; }
        .ai-copy-button { color:#6b7280 !important; }
        .ai-copy-button:hover { background:#f3f4f6 !important; color:#202123 !important; }
        .ai-markdown h1,.ai-markdown h2,.ai-markdown h3,.ai-markdown h4 { color:#202123 !important; }
        .ai-markdown code { background:#f3f4f6 !important; color:#202123 !important; }
        .ai-markdown pre { background:#111827 !important; color:#f9fafb !important; }
        .ai-markdown th { background:#f3f4f6 !important; }
        .ai-chat-composer { background:#ffffff !important; border:1px solid #d1d5db !important; box-shadow:0 2px 8px rgba(0,0,0,.06) !important; border-radius:24px !important; }
        .ai-chat-composer textarea { background:transparent !important; color:#202123 !important; }
        .ai-chat-composer textarea::placeholder { color:#9ca3af !important; }
        .ai-chat-composer button { color:#4b5563 !important; }
        .ai-chat-composer button.primary { background:#202123 !important; color:#ffffff !important; border:0 !important; border-radius:50% !important; }
        .dashboard-page { background:#f9fafb !important; color:#202123 !important; }
        .dashboard-heading h1 { color:#202123 !important; }
        .dashboard-heading p { color:#6b7280 !important; }
        .dashboard-heading button { background:#ffffff !important; border-color:#e5e7eb !important; color:#374151 !important; }
        .dashboard-kpis article,.dashboard-section,.fiesta-chart-card { background:#ffffff !important; border:1px solid #e5e7eb !important; color:#202123 !important; }
        .dashboard-kpis article span,.dashboard-kpis article small,.dashboard-section p,.fiesta-chart-title p { color:#6b7280 !important; }
        .dashboard-kpis article strong,.dashboard-section h2,.fiesta-chart-card h3 { color:#202123 !important; }
        .dashboard-fields span { background:#f9fafb !important; border-color:#e5e7eb !important; color:#374151 !important; }
        .dashboard-fields small,.fiesta-data-note { color:#6b7280 !important; }
        .fiesta-chart-title button { background:#ffffff !important; border-color:#e5e7eb !important; color:#4b5563 !important; }
        .fiesta-bar-track { background:#f3f4f6 !important; }
        .fiesta-bar-col strong,.fiesta-bar-col span { color:#6b7280 !important; }
        .fiesta-donut > div { background:#ffffff !important; }
        .fiesta-donut b,.fiesta-legend b { color:#202123 !important; }
        .fiesta-donut small,.fiesta-legend div { color:#6b7280 !important; }
        .fiesta-chart-empty,.dashboard-empty { color:#6b7280 !important; }
        @media(max-width:900px) { .fiesta-chat-sidebar { background:#f9fafb !important; } }

         .fiesta-sidebar-bottom { border:0; background:transparent; width:100%; text-align:left; cursor:pointer; }
         .fiesta-sidebar-bottom:hover { background:#f3f4f6 !important; border-radius:7px; }
         .ai-settings-page { min-height:calc(100vh - 46px); overflow:auto; background:#f7f7f8; padding:38px 28px 70px; color:#202123; }
         .ai-settings-shell { width:min(920px,100%); margin:0 auto; }
         .ai-settings-header { display:flex; align-items:flex-start; gap:18px; margin-bottom:28px; }
         .ai-settings-back { display:inline-flex; align-items:center; gap:7px; border:1px solid #e5e7eb; background:#fff; border-radius:8px; padding:8px 11px; color:#374151; font-size:12px; }
         .ai-settings-header h1 { margin:0 0 6px; font-size:25px; font-weight:650; color:#202123; }
         .ai-settings-header p { margin:0; color:#6b7280; font-size:12px; }
         .ai-settings-mode-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:18px; }
         .ai-settings-mode-card { position:relative; display:flex; align-items:flex-start; gap:14px; text-align:left; min-height:126px; padding:19px; border:1px solid #e5e7eb; border-radius:12px; background:#fff; color:#202123; }
         .ai-settings-mode-card:hover { border-color:#cbd5e1; }
         .ai-settings-mode-card.active { border-color:#202123; box-shadow:0 0 0 1px #202123; }
         .ai-settings-mode-icon { width:38px; height:38px; flex:none; display:grid; place-items:center; border-radius:10px; background:#f3f4f6; color:#374151; }
         .ai-settings-mode-card strong { display:block; font-size:14px; margin-bottom:6px; }
         .ai-settings-mode-card p { margin:0 0 7px; color:#6b7280; font-size:11px; line-height:1.5; }
         .ai-settings-mode-card small { color:#9ca3af; font-size:10px; line-height:1.4; }
         .ai-settings-check { position:absolute; top:18px; right:18px; color:#111827; }
         .ai-settings-card { background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:24px; }
         .ai-settings-card-title { display:flex; justify-content:space-between; gap:18px; align-items:flex-start; padding-bottom:18px; border-bottom:1px solid #f0f0f0; }
         .ai-settings-card-title h2 { margin:0 0 5px; font-size:16px; color:#202123; }
         .ai-settings-card-title p { margin:0; color:#6b7280; font-size:11px; line-height:1.5; }
         .ai-settings-status { display:inline-flex; align-items:center; gap:5px; white-space:nowrap; padding:6px 9px; border-radius:999px; background:#f0fdf4; color:#166534; font-size:10px; }
         .ai-settings-chain { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin:22px 0 10px; }
         .ai-settings-chain span { padding:8px 11px; background:#f8fafc; border:1px solid #e5e7eb; border-radius:7px; font-size:11px; color:#374151; }
         .ai-settings-chain i { font-style:normal; color:#9ca3af; }
         .ai-settings-form { padding-top:18px; display:grid; gap:16px; }
         .ai-settings-form label { display:block; color:#374151; font-size:11px; font-weight:600; }
         .ai-settings-form input,.ai-settings-form select { display:block; width:100%; height:38px; margin-top:7px; padding:0 10px; border:1px solid #d1d5db; border-radius:7px; background:#fff; color:#202123; outline-color:#111827; }
         .ai-settings-form input:focus,.ai-settings-form select:focus { border-color:#9ca3af; }
         .ai-settings-model-row { display:grid; grid-template-columns:minmax(0,1fr) 150px; gap:10px; align-items:end; }
         .ai-settings-fetch { height:38px; margin-top:0; }
         .ai-settings-actions { display:flex; justify-content:flex-end; gap:9px; margin-top:20px; }
         .ai-settings-actions .wide-button { min-width:145px; }
         .ai-settings-save { margin-top:20px; }
         .ai-settings-note { margin:18px 0 0; color:#6b7280; font-size:10px; line-height:1.6; }
         .ai-settings-error { margin-top:16px; padding:10px 12px; border-radius:7px; background:#fef2f2; border:1px solid #fecaca; color:#991b1b; font-size:11px; line-height:1.45; }
         .ai-settings-success { margin-top:16px; padding:10px 12px; border-radius:7px; background:#f0fdf4; border:1px solid #bbf7d0; color:#166534; font-size:11px; line-height:1.45; }
         @media(max-width:760px) { .ai-settings-mode-grid { grid-template-columns:1fr; } .ai-settings-model-row { grid-template-columns:1fr; } .ai-settings-actions { flex-direction:column; } .ai-settings-actions .wide-button { width:100%; } }

      `}</style>
      <header className="titlebar">
        <div className="appmark"><FileSpreadsheet size={25}/></div>
        <strong>AI Analyst</strong>
        <div className="filename">{wb.filename}<ChevronDown size={14}/></div>
        <div className="saved"><Save size={14}/>{wb.sessionId ? 'Loaded' : 'No dataset uploaded'}</div>
        <div className="top-search">
          <Search size={17}/>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search"/>
        </div>
        <label className="fiesta-model-select" title="Choose which AI provider handles your next message">
          <Bot size={15}/>
          <span>AI model</span>
          <select aria-label="Choose AI model" value={selectedProvider} onChange={e => setSelectedProvider(e.target.value)} disabled={busy}>
            <option value="auto">Auto</option>
            <option value="gemini">Gemini</option>
            <option value="gemini2">Gemini 2</option>
            <option value="groq">Groq</option>
            <option value="openrouter">OpenRouter · DeepSeek V4.1 Flash</option>
            <option value="ollama">Ollama · Qwen 2.5:3b</option>
          </select>
        </label>
        <div className="title-actions">
          <button title="Upload dataset" onClick={() => fileRef.current?.click()}><Upload size={16}/></button>
          <button type="button" title="Clear dataset and return to a blank sheet" aria-label="Clear dataset" disabled={!wb.sessionId && wb.columns.length === 0 && wb.rows.length === 0} onClick={clearDataset} style={{ opacity: (!wb.sessionId && wb.columns.length === 0 && wb.rows.length === 0) ? 0.45 : 1, cursor: (!wb.sessionId && wb.columns.length === 0 && wb.rows.length === 0) ? 'not-allowed' : 'pointer' }}><Trash2 size={16}/></button>
          <button title="Download CSV" onClick={() => exportFile('csv')}><Download size={16}/></button>
          <button type="button" className="avatar" title="Go to DataPilot AI Home" aria-label="Go to DataPilot AI Home" onClick={() => {
            window.location.href = '/';
        }}>
            S
          </button>
        </div>
        <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" hidden onChange={e => {
            const file = e.target.files?.[0];
            if (file) {
                setFileToImport(file);
            }
            e.target.value = '';
        }}/>
      </header>

      <nav className="workspace-page-nav" aria-label="Main pages">
          <button type="button" className={activePage === 'excel' ? 'active' : ''} onClick={() => setActivePage('excel')}><FileSpreadsheet size={16}/> Excel</button>
          <button type="button" className={activePage === 'ai' ? 'active' : ''} onClick={() => setActivePage('ai')}><Bot size={16}/> AI Analyst</button>
          <button type="button" className={activePage === 'cleaning' ? 'active' : ''} onClick={() => setActivePage('cleaning')}><ShieldCheck size={16}/> Data Quality</button>
        </nav>

      {activePage === 'excel' && <>
      <main className="workarea no-panel">
        <section className="worksheet">
            <OpenSheetsView initialRows={wb.rows} sessionId={wb.sessionId} rowCount={wb.rowCount} columns={wb.columns} apiBase={API} onUploadFile={async (file) => { await upload(file); }} fileToImport={fileToImport} onImportConsumed={() => setFileToImport(null)} onSyncToAI={syncOpenSheetsToAI} onSaveCellEdits={saveCellEdits} syncing={busy}/>
        </section>
      </main>

      {dialog && <div className="modal-backdrop" onClick={() => setDialog('')}>
        <div className="modal" onClick={e => e.stopPropagation()}>
          <div className="modal-header">
            <strong>{{
                    rename: 'Rename column',
                    remove: 'Remove column',
                    type: 'Change data type',
                    formula: 'Add calculated column',
                    missing: 'Handle missing values'
                }[dialog]}</strong>
            <button onClick={() => setDialog('')}><X size={17}/></button>
          </div>

          {(dialog === 'rename' || dialog === 'remove' || dialog === 'type' || dialog === 'missing') && <>
            <label>Column</label>
            <select value={col} onChange={e => setCol(e.target.value)}>
              {wb.columns.map(c => <option key={c.field} value={c.field}>{c.field}</option>)}
            </select>
          </>}

          {dialog === 'rename' && <>
            <label>New name</label>
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="New column name"/>
          </>}

          {dialog === 'remove' && <p className="warning-text">This removes the selected column from the working dataset.</p>}

          {dialog === 'type' && <>
            <label>New data type</label>
            <select value={type} onChange={e => setType(e.target.value)}>
              {['Text', 'Whole number', 'Decimal number', 'Percentage', 'Date', 'Date/Time', 'True/False'].map(t => <option key={t}>{t}</option>)}
            </select>
          </>}

          {dialog === 'formula' && <>
            <label>New column name</label>
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="e.g. Revenue"/>
            <label>Expression</label>
            <input value={expr} onChange={e => setExpr(e.target.value)} placeholder="Quantity * UnitPrice"/>
            <small>Uses dataframe column names and basic arithmetic, not full Excel formulas.</small>
          </>}

          {dialog === 'missing' && <>
            <label>Replacement value</label>
            <input value={newValue} onChange={e => setNewValue(e.target.value)} placeholder="Not Available or 0"/>
          </>}

          <div className="modal-actions">
            <button onClick={() => setDialog('')}>Cancel</button>
            <button className="primary" onClick={applyDialog}>Apply</button>
          </div>
        </div>
      </div>}
      </>}

      {activePage === 'ai' && (<main className="ai-chat-page">
          <section className="ai-chat-shell">
            <aside className="fiesta-chat-sidebar">
              <button className="fiesta-new-chat" onClick={() => { setChat([]); setQuestion(''); }}><PlusCircle size={17}/> New chat</button>
              <div><div className="fiesta-sidebar-label">Workspace</div>
                <button className="fiesta-history-item" onClick={() => setActivePage('excel')}><FileSpreadsheet size={14} style={{ display: 'inline', marginRight: 8 }}/> Spreadsheet</button>
                <button className="fiesta-history-item" onClick={() => setActivePage('cleaning')}><ShieldCheck size={14} style={{ display: 'inline', marginRight: 8 }}/> Data Quality</button>
              </div>
              <div><div className="fiesta-sidebar-label">Recent chats</div>
                {chat.length ? <button className="fiesta-history-item">{chat.find(m => m.role === 'user')?.text?.slice(0, 34) || 'Current conversation'}</button> : <div className="fiesta-history-item" style={{ opacity: .55 }}>No conversations yet</div>}
              </div>
              <button type="button" className="fiesta-sidebar-bottom" onClick={() => setActivePage('settings')} title="AI Settings">
                <Settings size={15}/> Settings <span style={{ marginLeft: 'auto' }}>AI Analyst</span>
              </button>
            </aside>
            <div className="ai-chat-main">
              <header className="ai-chat-header">
                <div className="ai-chat-avatar"><Bot size={22}/></div>
                <div><h1>AI Analyst</h1><p>{wb.sessionId ? `${wb.filename} · ${wb.rowCount.toLocaleString()} rows connected` : 'Your business and data analysis workspace'}</p></div>
              </header>
              <div className="ai-chat-messages">
                {chat.length === 0 && <div className="ai-empty-state"><div className="ai-chat-avatar" style={{ margin: '0 auto 20px', width: 54, height: 54, borderRadius: 18 }}><Sparkles size={25}/></div><h2>What would you like to explore?</h2><p>{wb.sessionId ? `Your dataset ${wb.filename} is ready. Ask a question or create a dashboard.` : 'Chat with AI, analyze datasets, and build interactive business dashboards.'}</p><div className="ai-suggestions">{(wb.sessionId ? ['Summarize this dataset', 'Show monthly revenue trend', 'Which products sell the most?', 'Find data quality issues'] : ['Explain a business metric', 'Help me write a SQL query', 'How do I build a Power BI dashboard?', 'Analyze my dataset']).map(prompt => <button key={prompt} onClick={() => void askAI(prompt)}>{prompt}</button>)}</div>{!wb.sessionId && <button className="primary" onClick={() => setActivePage('excel')}>Upload a dataset</button>}</div>}
                {chat.map((message, index) => <div key={`${index}-${message.role}`} className={`ai-message ${message.role === 'user' ? 'user' : 'assistant'}`}><div className="ai-message-meta"><strong>{message.role === 'user' ? 'You' : 'AI Analyst'}</strong>{message.role !== 'user' && message.provider && <small className="ai-provider-badge">{message.provider.startsWith('Groq') ? 'Groq' : message.provider.startsWith('Ollama') ? 'Ollama · Qwen 2.5:3b' : message.provider}</small>}</div><MarkdownMessage text={message.text}/>{message.role !== 'user' && <MonthlyRevenueTrendChart text={message.text}/>}{message.role !== 'user' && <div className="ai-response-actions"><button type="button" className="ai-copy-button" title={copiedMessageIndex === index ? 'Copied' : 'Copy response'} aria-label={copiedMessageIndex === index ? 'Response copied' : 'Copy AI response'} onClick={() => void copyAIResponse(message.text, index)}>{copiedMessageIndex === index ? <Check size={17}/> : <Copy size={17}/>}<span>{copiedMessageIndex === index ? 'Copied' : 'Copy'}</span></button></div>}{message.role !== 'user' && message.elapsedMs !== undefined && <small className="ai-response-time">Response time: {(message.elapsedMs / 1000).toFixed(2)}s</small>}</div>)}
                {busy && <div className="ai-message assistant"><strong>AI Analyst</strong><p>Analyzing your data…</p></div>}
              </div>
              <form className="ai-chat-composer" onSubmit={event => { event.preventDefault(); if (!busy)
            void askAI(); }}>
                <textarea value={question} onChange={e => setQuestion(e.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            if (!busy && question.trim())
                void askAI();
        } }} placeholder={wb.sessionId ? 'Message AI Analyst about your data…' : 'Ask anything or upload a dataset…'} disabled={busy}/>
                <button type="button" title="Upload dataset" onClick={() => fileRef.current?.click()}><Paperclip size={17}/></button>
                <button type="submit" className="primary" disabled={busy || !question.trim()}><Send size={17}/></button>
              </form>
            </div>
          </section>
        </main>)}

      {activePage === 'settings' && (<main className="ai-settings-page">
          <div className="ai-settings-shell">
            <div className="ai-settings-header">
              <button type="button" className="ai-settings-back" onClick={() => setActivePage('ai')}>
                <Bot size={16}/> AI Analyst
              </button>
              <div>
                <h1>AI Settings</h1>
                <p>Choose how AI Analyst connects to your models.</p>
              </div>
            </div>

            <div className="ai-settings-mode-grid">
              <button type="button" className={`ai-settings-mode-card ${aiMode === 'current' ? 'active' : ''}`} onClick={() => {
                setAiMode('current');
                setAiSettingsError('');
                setAiSettingsMessage('');
            }}>
                <div className="ai-settings-mode-icon"><Database size={20}/></div>
                <div>
                  <strong>Our Current Project</strong>
                  <p>Use the existing .env configuration and fallback chain.</p>
                  <small>Gemini 1 â†’ Gemini 2 â†’ Groq â†’ OpenRouter â†’ Ollama</small>
                </div>
                {aiMode === 'current' && <Check size={18} className="ai-settings-check"/>}
              </button>

              <button type="button" className={`ai-settings-mode-card ${aiMode === 'custom' ? 'active' : ''}`} onClick={() => {
                setAiMode('custom');
                setAiSettingsError('');
                setAiSettingsMessage('');
            }}>
                <div className="ai-settings-mode-icon"><Settings size={20}/></div>
                <div>
                  <strong>Select Model &amp; Add API Key</strong>
                  <p>Use one provider and one model only. No fallback.</p>
                  <small>Gemini, Groq, or OpenRouter</small>
                </div>
                {aiMode === 'custom' && <Check size={18} className="ai-settings-check"/>}
              </button>
            </div>

            {aiMode === 'current' ? (<section className="ai-settings-card">
                <div className="ai-settings-card-title">
                  <div>
                    <h2>Our Current Project</h2>
                    <p>Your existing backend configuration stays unchanged.</p>
                  </div>
                  <span className="ai-settings-status"><Check size={14}/> Active</span>
                </div>
                <div className="ai-settings-chain">
                  <span>Gemini 1</span><i>â†’</i><span>Gemini 2</span><i>â†’</i><span>Groq</span><i>â†’</i><span>OpenRouter</span><i>â†’</i><span>Ollama</span>
                </div>
                <p className="ai-settings-note">
                  The normal AI model dropdown remains available in the header. Python deterministic calculations continue to run locally and do not require an API key.
                </p>
                <button type="button" className="primary ai-settings-save" onClick={() => void saveAISettings('current')} disabled={aiSettingsSaving}>
                  {aiSettingsSaving ? 'Savingâ€¦' : 'Use Our Current Project'}
                </button>
              </section>) : (<section className="ai-settings-card">
                <div className="ai-settings-card-title">
                  <div>
                    <h2>Select Model &amp; Add API Key</h2>
                    <p>Credentials are sent directly to the backend and are never stored in browser storage.</p>
                  </div>
                  {aiSettingsHasKey && <span className="ai-settings-status"><ShieldCheck size={14}/> Key saved</span>}
                </div>

                <div className="ai-settings-form">
                  <label>
                    Provider
                    <select value={aiSettingsProvider} onChange={e => {
                    setAiSettingsProvider(e.target.value);
                    setAiSettingsModels([]);
                    setAiSettingsModel('');
                    setAiSettingsMessage('');
                    setAiSettingsError('');
                }} disabled={aiSettingsLoading || aiSettingsTesting || aiSettingsSaving}>
                      <option value="gemini">Gemini â€” Google</option>
                      <option value="groq">Groq</option>
                      <option value="openrouter">OpenRouter</option>
                      <option value="deepseek">DeepSeek</option>
                      <option value="perplexity">Perplexity</option>
                      <option value="openai">ChatGPT / OpenAI</option>
                      <option value="anthropic">Claude â€” Anthropic</option>
                    </select>
                  </label>

                  <label>
                    API key
                    <input type="password" value={aiSettingsApiKey} onChange={e => setAiSettingsApiKey(e.target.value)} placeholder={aiSettingsHasKey ? 'Enter key to test or replace saved key' : 'Paste API key'} autoComplete="new-password"/>
                  </label>

                  <div className="ai-settings-model-row">
                    <label>
                      Model ID
                      <input value={aiSettingsModel} onChange={e => setAiSettingsModel(e.target.value)} placeholder="Enter model ID manually or fetch models"/>
                    </label>
                    <button type="button" className="wide-button ai-settings-fetch" onClick={() => void fetchAISettingsModels()} disabled={aiSettingsLoading || !aiSettingsApiKey.trim()}>
                      {aiSettingsLoading ? 'Fetchingâ€¦' : 'Fetch Models'}
                    </button>
                  </div>

                  {aiSettingsModels.length > 0 && (<label>
                      Available models
                      <select value={aiSettingsModel} onChange={e => setAiSettingsModel(e.target.value)}>
                        <option value="">Select a model</option>
                        {aiSettingsModels.map(model => (<option key={model.id} value={model.id}>{model.name} â€” {model.id}</option>))}
                      </select>
                    </label>)}
                </div>

                {aiSettingsError && <div className="ai-settings-error">{aiSettingsError}</div>}
                {aiSettingsMessage && <div className="ai-settings-success">{aiSettingsMessage}</div>}

                <div className="ai-settings-actions">
                  <button type="button" className="wide-button" onClick={() => void testAISettingsConnection()} disabled={aiSettingsTesting || aiSettingsSaving || !aiSettingsApiKey.trim() || !aiSettingsModel.trim()}>
                    {aiSettingsTesting ? 'Testingâ€¦' : 'Test Connection'}
                  </button>
                  <button type="button" className="primary wide-button" onClick={() => void saveAISettings('custom')} disabled={aiSettingsSaving || aiSettingsTesting || !aiSettingsApiKey.trim() || !aiSettingsModel.trim()}>
                    {aiSettingsSaving ? 'Savingâ€¦' : 'Save Configuration'}
                  </button>
                </div>

                <p className="ai-settings-note">
                  Custom mode uses only the selected provider and model. If that provider fails, the actual provider error is shown instead of silently falling back.
                </p>
              </section>)}
          </div>
        </main>)}

      {activePage === 'cleaning' && (<DataQualityPage sessionId={wb.sessionId} apiBase={API} onNavigate={page => setActivePage(page)}/>)}

    </div>);
}
