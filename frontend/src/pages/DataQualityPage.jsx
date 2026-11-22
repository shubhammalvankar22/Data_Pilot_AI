// Imports
import { useEffect, useMemo, useState } from 'react';
import { BarChart3, CheckCircle2, FileSpreadsheet, Info, Loader2, ShieldCheck, TriangleAlert, Search, PlusCircle, Settings } from 'lucide-react';
// Imports
import './DataQualityPage.css';
// Function: number
const number = (value) => value.toLocaleString('en-IN');
// Function: compact
const compact = (value) => value.toLocaleString('en-IN', { maximumFractionDigits: 2 });
// Function: date label
const dateLabel = (value) => value ? value.slice(0, 10) : '—';
// Function: percent
const percent = (value, total) => total > 0 ? `${(value / total * 100).toFixed(2)}%` : '0.00%';
// Component or function: donut
function Donut({ profile }) {
    // Value: parts
    const parts = [
        { label: 'Missing values', value: profile.missingCells, color: '#ff5d68' },
        { label: 'Duplicate rows', value: profile.duplicateRows, color: '#ff9f43' },
        { label: 'Invalid dates', value: profile.invalidDates, color: '#ffd34e' },
        { label: 'Date order violations', value: profile.dateOrderViolations || 0, color: '#e05a47' },
        { label: 'Whitespace / case', value: profile.whitespaceCells + profile.categoryVariations, color: '#a879ff' },
        { label: 'Potential outliers', value: profile.numericOutliers, color: '#35c7f3' },
    ];
    // Function: total
    const total = parts.reduce((sum, item) => sum + item.value, 0);
    let start = 0;
    // Function: stops
    const stops = parts.map(item => {
        const end = total ? start + item.value / total * 100 : start;
        const segment = `${item.color} ${start}% ${end}%`;
        start = end;
        return segment;
    }).join(',');
    return <div className="dq-donut-layout">
    <div className="dq-donut" style={{ background: total ? `conic-gradient(${stops})` : '#26374d' }}>
      <div><small>Issues found</small><b>{number(total)}</b></div>
    </div>
    <div className="dq-legend">{parts.map(item => <div key={item.label}><i style={{ background: item.color }}/><span>{item.label}</span><b>{number(item.value)}</b></div>)}</div>
  </div>;
}
// Component or function: data quality page
export default function DataQualityPage({ sessionId, apiBase, onNavigate }) {
    // State: 
    const [profile, setProfile] = useState(null);
    // State: 
    const [filename, setFilename] = useState('');
    // State: 
    const [loading, setLoading] = useState(true);
    // State: 
    const [error, setError] = useState('');
    // State: 
    const [selectedTextColumn, setSelectedTextColumn] = useState('');
    // State: 
    const [issueSearch, setIssueSearch] = useState('');
    // Run side effect when dependencies change
    useEffect(() => {
        let cancelled = false;
        async function load() {
            if (!sessionId) {
                setError('Upload a dataset in Excel Workspace before opening Data Quality.');
                setLoading(false);
                return;
            }
            setLoading(true);
            setError('');
            try {
                const response = await fetch(`${apiBase}/api/data-quality/${encodeURIComponent(sessionId)}`);
                const data = await response.json();
                if (!response.ok)
                    throw new Error(data.detail || `Request failed (${response.status})`);
                if (!cancelled) {
                    setProfile(data.profile);
                    setFilename(data.filename || 'Uploaded dataset');
                }
            }
            catch (e) {
                if (!cancelled)
                    setError(e instanceof Error ? e.message : 'Could not load data quality profile.');
            }
            finally {
                if (!cancelled)
                    setLoading(false);
            }
        }
        void load();
        return () => { cancelled = true; };
    }, [sessionId, apiBase]);
    // Run side effect when dependencies change
    useEffect(() => {
        if (profile?.textAnalysis.length && !selectedTextColumn)
            setSelectedTextColumn(profile.textAnalysis[0].column);
    }, [profile, selectedTextColumn]);
    // Computed value: selected text
    const selectedText = useMemo(() => profile?.textAnalysis.find(c => c.column === selectedTextColumn), [profile, selectedTextColumn]);
    // Computed value: duplicate columns
    const duplicateColumns = useMemo(() => {
        if (!profile)
            return [];
        const cols = profile.columns.map(c => c.column);
        return cols;
    }, [profile]);
    if (loading)
        return <div className="dq-loading"><Loader2 className="dq-spin"/> Analysing the complete dataset with Python…</div>;
    if (error || !profile)
        return <div className="dq-error"><TriangleAlert /><h2>Data Quality is unavailable</h2><p>{error || 'No profile returned by the backend.'}</p><button onClick={() => onNavigate('excel')}>Open Excel Workspace</button></div>;
    // Completeness is calculated at cell level; row-level completeness is shown separately.
    // Issue counts are not added together because the same row/cell can trigger multiple checks.
    const totalCells = profile.rowCount * profile.columnCount;
    // Function: date value count
    const dateValueCount = profile.dateAnalysis.reduce((sum, c) => sum + c.valid + c.invalid, 0);
    // Function: numeric value count
    const numericValueCount = profile.numericSummary.reduce((sum, c) => sum + c.count, 0);
    // Value: issue total
    const issueTotal = profile.missingCells + profile.duplicateRows + profile.invalidDates + (profile.dateOrderViolations || 0) + profile.whitespaceCells + profile.numericOutliers + profile.categoryVariations;
    // Function: filtered duplicates
    const filteredDuplicates = profile.duplicateSample.filter(row => !issueSearch || Object.values(row.values).some(v => String(v ?? '').toLowerCase().includes(issueSearch.toLowerCase())));
    // One overall score combines the checks below by quality dimension.
    // Each dimension is normalized to its own population; unavailable dimensions are excluded.
    const qualityDimensions = [
        { score: totalCells > 0 ? 100 * (1 - profile.missingCells / totalCells) : null, weight: 0.30 },
        { score: profile.rowCount > 0 ? 100 * (1 - profile.duplicateRows / profile.rowCount) : null, weight: 0.15 },
        { score: (() => {
                const checks = [];
                if (dateValueCount > 0)
                    checks.push(100 * (1 - profile.invalidDates / dateValueCount));
                if ((profile.dateOrderComparisons || 0) > 0)
                    checks.push(100 * (1 - (profile.dateOrderViolations || 0) / profile.dateOrderComparisons));
                return checks.length ? checks.reduce((sum, value) => sum + value, 0) / checks.length : null;
            })(), weight: 0.15 },
        { score: totalCells > 0 ? 100 * (1 - profile.mixedTypeCells / totalCells) : null, weight: 0.15 },
        { score: totalCells > 0 ? 100 * (1 - Math.min(1, (profile.whitespaceCells + profile.categoryVariations) / totalCells)) : null, weight: 0.15 },
        { score: numericValueCount > 0 ? 100 * (1 - Math.min(1, profile.numericOutliers / numericValueCount)) : null, weight: 0.10 },
    ].filter((dimension) => dimension.score !== null);
    // Function: total weight
    const totalWeight = qualityDimensions.reduce((sum, dimension) => sum + dimension.weight, 0);
    // Value: overall quality
    const overallQuality = totalWeight > 0
        ? Math.max(0, Math.min(100, qualityDimensions.reduce((sum, dimension) => sum + dimension.score * dimension.weight, 0) / totalWeight))
        : 0;
    // Value: quality label
    const qualityLabel = overallQuality >= 90 ? 'Excellent' : overallQuality >= 75 ? 'Good' : overallQuality >= 60 ? 'Fair' : 'Needs attention';
    // Value: quality tone
    const qualityTone = overallQuality >= 90 ? 'excellent' : overallQuality >= 75 ? 'good' : overallQuality >= 60 ? 'fair' : 'poor';
    return <div className="dq-page">
    <aside className="fiesta-chat-sidebar dq-chat-sidebar">
      <button className="fiesta-new-chat" onClick={() => onNavigate('ai')}><PlusCircle size={17}/> New chat</button>
      <div>
        <div className="fiesta-sidebar-label">Workspace</div>
        <button className="fiesta-history-item" onClick={() => onNavigate('excel')}><FileSpreadsheet size={14} style={{ display: 'inline', marginRight: 8 }}/> Spreadsheet</button>
        <button className="fiesta-history-item active" aria-current="page"><ShieldCheck size={14} style={{ display: 'inline', marginRight: 8 }}/> Data Quality</button>
      </div>
      <div>
        <div className="fiesta-sidebar-label">Recent chats</div>
        <button className="fiesta-history-item dq-no-chats" onClick={() => onNavigate('ai')}>Open AI Analyst to view chats</button>
      </div>
      <div className="fiesta-sidebar-bottom"><Settings size={15}/> Settings <span style={{ marginLeft: 'auto' }}>AI Analyst</span></div>
    </aside>
    <main className="dq-main">
      <header className="dq-heading">
        <div><h1><BarChart3 />Data Quality &amp; Profiling</h1><p>Inspect the dataset's structure, quality and statistical summary (Read-Only)</p></div>
        <span className="dq-readonly"><Info />Page 3 – Data Quality (Read-Only)</span>
      </header>
      <section className="dq-filebar"><span className="dq-file-icon">CSV</span><div><b>{filename}</b><small>{number(profile.rowCount)} rows × {number(profile.columnCount)} columns <i /> Size in memory: {(profile.memoryBytes / 1024 / 1024).toFixed(1)} MB</small></div><span className="dq-analysed"><CheckCircle2 />Dataset Analysed</span></section>
      <section className="dq-overall-quality" aria-label="Overall dataset quality">
        <div className="dq-overall-copy"><span>Overall Dataset Quality</span><small>Composite score based on completeness, validity, consistency, uniqueness and numeric anomaly checks</small></div>
        <div className="dq-overall-value"><strong>{overallQuality.toFixed(2)}%</strong><span className={`dq-quality-label ${qualityTone}`}>{qualityLabel}</span></div>
        <div className="dq-overall-track"><i className={qualityTone} style={{ width: `${overallQuality}%` }}/></div>
        <small className="dq-overall-note">One weighted score · applicable checks only · overlapping issue flags are not added together</small>
      </section>

      <section className="dq-grid dq-top-grid">
        <article className="dq-panel dq-info-panel"><h2><span>⌘</span>Dataset Information (df.info())</h2>
          <div className="dq-table-scroll"><table><thead><tr><th>#</th><th>Column</th><th>Non-Null Count</th><th>Dtype</th></tr></thead><tbody>{profile.columns.map((c, i) => <tr key={c.column}><td>{i}</td><td>{c.column}</td><td>{number(c.nonNull)} non-null</td><td>{c.dtype}</td></tr>)}</tbody></table></div>
          <div className="dq-code-note">dtypes: {Object.entries(profile.columns.reduce((acc, c) => (acc[c.dtype] = (acc[c.dtype] || 0) + 1, acc), {})).map(([dtype, count]) => `${dtype}(${count})`).join(', ')}<br />memory usage: {(profile.memoryBytes / 1024 / 1024).toFixed(2)} MB</div>
        </article>
        <article className="dq-panel"><h2><span>▦</span>Column Summary &amp; Data Types</h2>
          <div className="dq-table-scroll"><table><thead><tr><th>Column</th><th>Data Type</th><th>Non-Null Count</th><th>Missing Values</th><th>Missing %</th><th>Unique Values</th></tr></thead><tbody>{profile.columns.map(c => <tr key={c.column}><td>{c.column}</td><td><em className={`dq-type dq-${c.detectedType.includes('numeric') ? 'numeric' : c.detectedType === 'date-like' || c.detectedType === 'datetime' ? 'date' : c.detectedType === 'empty' ? 'empty' : 'text'}`}>{c.dtype}</em></td><td>{number(c.nonNull)}</td><td>{number(c.missing)}</td><td>{c.missingPercent.toFixed(2)}%</td><td>{number(c.unique)}</td></tr>)}</tbody></table></div>
        </article>
      </section>

      <section className="dq-grid dq-middle-grid">
        <article className="dq-panel"><h2><span>⬡</span>Data Quality Checks (Overview)</h2><Donut profile={profile}/><p className="dq-footnote">Detailed issue counts use their relevant row, cell or value denominators. The overall score above weights quality dimensions; overlapping flags are not simply added together.</p></article>
        <article className="dq-panel"><h2><span>▦</span>Statistical Summary (df.describe()) – Numeric Columns</h2>
          <div className="dq-table-scroll"><table className="dq-stat-table"><thead><tr><th>Column</th><th>Count</th><th>Mean</th><th>Std</th><th>Min</th><th>25%</th><th>50% (Median)</th><th>75%</th><th>Max</th></tr></thead><tbody>{profile.numericSummary.map(c => <tr key={c.column}><td>{c.column}</td><td>{number(c.count)}</td><td>{c.mean === null ? '—' : compact(c.mean)}</td><td>{c.std === null ? '—' : compact(c.std)}</td><td>{c.min === null ? '—' : compact(c.min)}</td><td>{c.q25 === null ? '—' : compact(c.q25)}</td><td>{c.median === null ? '—' : compact(c.median)}</td><td>{c.q75 === null ? '—' : compact(c.q75)}</td><td>{c.max === null ? '—' : compact(c.max)}</td></tr>)}{!profile.numericSummary.length && <tr><td colSpan={9}>No numeric columns were detected.</td></tr>}</tbody></table></div>
        </article>
      </section>

      <section className="dq-grid dq-bottom-grid">
        <article className="dq-panel"><h2><span>▣</span>Date Column Analysis</h2>
          <div className="dq-table-scroll"><table><thead><tr><th>Column</th><th>Valid Dates</th><th>Invalid Dates</th><th>Missing Dates</th><th>Unique Dates</th></tr></thead><tbody>{profile.dateAnalysis.map(c => <tr key={c.column}><td>{c.column}</td><td>{number(c.valid)}</td><td className={c.invalid ? 'dq-danger' : ''}>{number(c.invalid)}</td><td>{number(c.missing)}</td><td>{number(c.unique)}</td></tr>)}</tbody></table></div>
          {profile.dateAnalysis.map(c => <p className="dq-range" key={`${c.column}-range`}>{c.column}: {dateLabel(c.min)} → {dateLabel(c.max)}</p>)}
          {profile.dateOrderPairs?.map(pair => <p className={`dq-range ${pair.violations ? 'dq-danger' : ''}`} key={`${pair.startColumn}-${pair.endColumn}`}>
            {pair.endColumn} before {pair.startColumn}: <b>{number(pair.violations)}</b> of {number(pair.comparisons)} records ({percent(pair.violations, pair.comparisons)})
          </p>)}
          {!profile.dateAnalysis.length && <p className="dq-empty">No date-like columns identified from the data.</p>}
        </article>
        <article className="dq-panel"><h2><span>⌕</span>Text / Categorical Columns (Top Values)</h2>
          {profile.textAnalysis.length ? <><label className="dq-select-label">Column: <select value={selectedTextColumn} onChange={e => setSelectedTextColumn(e.target.value)}>{profile.textAnalysis.map(c => <option key={c.column} value={c.column}>{c.column}</option>)}</select></label>
          {selectedText?.topValues.map(v => <div className="dq-bar-row" key={v.value}><span title={v.value}>{v.value}</span><div><i style={{ width: `${Math.max(2, v.count / Math.max(1, selectedText.topValues[0]?.count || 1) * 100)}%` }}/></div><b>{number(v.count)}</b></div>)}
          <p className="dq-footnote">{number(selectedText?.unique || 0)} unique values · {number(selectedText?.blank || 0)} missing / blank values</p></> : <p className="dq-empty">No text or categorical columns detected.</p>}
        </article>
        <article className="dq-panel"><h2><span>▢</span>Sample of Duplicate Rows <small>Showing {filteredDuplicates.length} of {number(profile.duplicateRows)} duplicate rows (sample)</small></h2>
          <div className="dq-duplicate-search"><Search /><input value={issueSearch} onChange={e => setIssueSearch(e.target.value)} placeholder="Search duplicate sample"/></div>
          <div className="dq-table-scroll"><table><thead><tr><th>#</th>{duplicateColumns.slice(0, 6).map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{filteredDuplicates.map((row, i) => <tr key={`${row.rowNumber}-${i}`}><td>{row.rowNumber}</td>{duplicateColumns.slice(0, 6).map(c => <td key={c} title={String(row.values[c] ?? '')}>{String(row.values[c] ?? '—').slice(0, 35)}</td>)}</tr>)}{!filteredDuplicates.length && <tr><td colSpan={7}>No duplicate rows in the returned sample.</td></tr>}</tbody></table></div>
        </article>
      </section>
      <footer className="dq-footer"><Info /> Read-only profile · {number(issueTotal)} issue flags across independent checks (overlaps possible) · Chronology checks compare semantically paired date columns · No records have been changed, removed or cleaned.</footer>
    </main>
  </div>;
}
