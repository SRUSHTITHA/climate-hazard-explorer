import { useEffect, useState } from 'react';
import EventTable from './components/EventTable.jsx';
import InsightCard from './components/InsightCard.jsx';
import QualityPanel from './components/QualityPanel.jsx';
import RegionPicker from './components/RegionPicker.jsx';
import TrendChart from './components/TrendChart.jsx';
import YearControls from './components/YearControls.jsx';
import { readParams, writeParams } from './urlState.js';
import { useAnalysis } from './useAnalysis.js';
import { exportCsv, exportPdf } from './export.js';

function SummaryCards({ data }) {
  const validSeries = data.series.filter((point) => point.valid && point.heatwave_days != null);
  const peak = validSeries.reduce((best, point) =>
    !best || point.heatwave_days > best.heatwave_days ? point : best, null);
  const trend = data.trends?.heatwave_days;
  const trendLabel = !trend || trend.slope_per_decade == null
    ? 'Inconclusive'
    : trend.evidence === 'strong' || trend.evidence === 'moderate'
      ? `${trend.slope_per_decade > 0 ? '+' : ''}${trend.slope_per_decade.toFixed(1)} / decade`
      : 'No clear trend';

  return (
    <section className="summary-grid" aria-label="Analysis summary">
      <article className="summary-card">
        <span className="summary-icon icon-teal" aria-hidden="true">◷</span>
        <div><p className="summary-label">Valid years</p>
          <p className="summary-value">{data.quality.valid_years}<span> / {data.quality.total_years}</span></p>
          <p className="summary-detail">Annual data coverage</p></div>
      </article>
      <article className="summary-card">
        <span className="summary-icon icon-heat" aria-hidden="true">♨</span>
        <div><p className="summary-label">Peak annual heatwave days</p>
          <p className="summary-value">{peak ? peak.heatwave_days : '—'}</p>
          <p className="summary-detail">{peak ? `Recorded in ${peak.year}` : 'No valid annual values'}</p></div>
      </article>
      <article className="summary-card">
        <span className="summary-icon icon-blue" aria-hidden="true">▤</span>
        <div><p className="summary-label">Events detected</p>
          <p className="summary-value">{data.quality.events_total ?? data.events.length}</p>
          <p className="summary-detail">Across selected years</p></div>
      </article>
      <article className="summary-card">
        <span className="summary-icon icon-violet" aria-hidden="true">↗</span>
        <div><p className="summary-label">Frequency trend</p>
          <p className="summary-value summary-value-small">{trendLabel}</p>
          <p className="summary-detail">{trend?.n_years != null ? `${trend.n_years} qualifying years` : 'Based on available data'}</p></div>
      </article>
    </section>
  );
}

function AnalysisView({ data, selection }) {
  if (data.series.length === 0) return <div className="empty-state"><h2>No data available</h2><p>Try a different region or time range.</p></div>;
  return (
    <>
      <div className="export-toolbar no-print"><div><p className="eyebrow">YOUR RESULTS</p><p className="export-hint">Export the selected analysis for reporting or further work.</p></div><div className="export-actions"><button type="button" className="button-secondary" onClick={() => exportCsv(data, selection)}>Export CSV</button><button type="button" onClick={exportPdf}>Export PDF / Print</button></div></div>
      <SummaryCards data={data} />
      <div className="analysis-grid">
        <InsightCard insights={data.insights} />
        <TrendChart series={data.series} trend={data.trends} />
        <EventTable events={data.events} total={data.quality.events_total} />
        <QualityPanel quality={data.quality} attribution={data.attribution} cellIds={data.cell_ids} />
      </div>
    </>
  );
}

function applySelection(patch, setSelection) {
  const current = readParams();
  const changed = Object.entries(patch).some(([key, value]) => (
    JSON.stringify(current[key]) !== JSON.stringify(value)
  ));
  if (changed) window.history.pushState(null, '', window.location.href);
  writeParams({ ...current, ...patch });
  setSelection(readParams());
}

function getStatus(regions, params, analysis, selection) {
  if (regions.isPending) return <div className="status-card"><span className="loading-dot" />Loading available regions…</div>;
  if (regions.isError) return <p className="error status-card" role="alert">{regions.error.message}</p>;
  if (!params) return <div className="status-card">Choose a region and apply your analysis settings to get started.</div>;
  if (analysis.isPending) return <div className="status-card"><span className="loading-dot" />Loading climate analysis… This may take a few minutes for a new region.</div>;
  if (analysis.isError) return <p className="error status-card" role="alert">{analysis.error.message}</p>;
  return <AnalysisView data={analysis.data} selection={selection} />;
}

function AppShell({ selection, regions, analysis, params, onApply }) {
  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand-mark" aria-hidden="true"><span>◒</span></div>
        <div className="brand-copy"><p className="eyebrow">CLIMATE INTELLIGENCE</p><h1>Climate Hazard Explorer</h1>
          <p className="header-subtitle">Explore historical heatwave activity, intensity, and long-term patterns.</p></div>
        <div className="header-status"><span className="status-indicator" /> ERA5 · Historical analysis</div>
      </header>

      <section className="configuration-panel" aria-label="Analysis configuration">
        <div className="section-heading"><div><p className="eyebrow">WORKSPACE</p><h2>Configure your analysis</h2></div>
          <p className="section-hint">Choose a region and time period</p></div>
        <div className="configuration-controls">
          <RegionPicker
            key={JSON.stringify(selection.region)}
            regions={regions.data ?? []}
            selection={selection}
            loading={analysis.isFetching}
            onApply={onApply}
          />
          <YearControls key={JSON.stringify(selection)} selection={selection} onApply={onApply} />
        </div>
      </section>

      <section className="analysis-status" aria-live="polite">
        {getStatus(regions, params, analysis, selection)}
      </section>
      <footer className="app-footer"><span>Climate Hazard Explorer</span><span>Evidence-led insights · Data limitations shown transparently</span></footer>
    </main>
  );
}

export default function App() {
  const [selection, setSelection] = useState(readParams);
  const { regions, params, analysis } = useAnalysis(selection);
  useEffect(() => {
    const restore = () => setSelection(readParams());
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  const onApply = (patch) => applySelection(patch, setSelection);
  return <AppShell {...{ selection, regions, analysis, params, onApply }} />;
}
