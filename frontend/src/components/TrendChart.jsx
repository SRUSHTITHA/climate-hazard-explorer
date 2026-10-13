import {
  BarController, BarElement, CategoryScale, Chart, Legend, LinearScale,
  LineController, LineElement, PointElement, Tooltip } from 'chart.js';
import { useState } from 'react';
import { Chart as ChartCanvas } from 'react-chartjs-2';
import MetricSelect, { METRICS, initialMetric } from './MetricSelect.jsx';
import { mannKendall } from '../trendStats.js';

Chart.register(BarController, BarElement, CategoryScale, Legend, LinearScale,
  LineController, LineElement, PointElement, Tooltip);

function datasets(metric, series) {
  const bars = {
    type: 'bar',
    label: METRICS[metric][0],
    data: series.map((point) => point[metric] ?? null),
    backgroundColor: 'rgba(13, 148, 136, 0.72)',
    borderColor: '#0d9488',
    borderWidth: 1,
    borderRadius: 4,
    maxBarThickness: 24,
    order: 1,
    spanGaps: false,
  };
  if (metric !== 'heatwave_days') return [bars];
  const mean = series.map((point) => point.rolling_heatwave_days ?? null);
  return [bars, { type: 'line', label: '5-year centered mean', data: mean,
    borderColor: '#ea580c', backgroundColor: '#ea580c', borderWidth: 2, pointRadius: 2, pointHoverRadius: 5, tension: 0.28, spanGaps: false }];
}

function tooltipLabel(item) {
  const value = item.parsed.y;
  return `${item.dataset.label}: ${value == null ? 'No data' : value.toFixed(1)}`;
}

function trendText(trend) {
  if (!trend) return null;
  if (trend.slope_per_decade == null) return `Trend: ${trend.evidence} (${trend.n_years} valid years).`;
  const sign = trend.slope_per_decade >= 0 ? '+' : '';
  return `Trend: ${sign}${trend.slope_per_decade.toFixed(1)} per decade, ${trend.evidence} evidence.`;
}

function chartOptions(metric) {
  return {
    animation: false,
    scales: {
      x: { title: { display: true, text: 'Year', color: '#718096', font: { size: 11, weight: '600' } }, grid: { display: false }, ticks: { color: '#718096', maxRotation: 0, autoSkip: true }, border: { display: false } },
      y: { beginAtZero: true, title: { display: true, text: METRICS[metric][1], color: '#718096', font: { size: 11, weight: '600' } }, grid: { color: '#edf1f4' }, ticks: { color: '#718096', precision: 0 }, border: { display: false } },
    },
    maintainAspectRatio: true,
    interaction: { mode: 'index', intersect: false },
    plugins: { legend: { display: true, position: 'top', align: 'start', labels: { usePointStyle: true, pointStyle: 'circle', boxWidth: 7, boxHeight: 7, color: '#526675', padding: 18, font: { size: 11 } } }, tooltip: { backgroundColor: '#173b4f', padding: 12, cornerRadius: 8, callbacks: { label: tooltipLabel } } },
  };
}

export default function TrendChart({ series, trend: trends }) {
  const [metric, setMetric] = useState(initialMetric);
  const years = series.map((point) => point.year);
  const excluded = series.filter((point) => !point.valid).length;
  const text = trendText(trends[metric]);
  const statisticalTrend = mannKendall(series, metric);
  return (
    <section className="trend" aria-label="Trend chart">
      <MetricSelect metric={metric} onChange={setMetric} />
      {excluded > 0 ? <p className="subtitle">{excluded} years excluded: insufficient data</p> : null}
      <ChartCanvas type="bar"
        data={{ labels: years, datasets: datasets(metric, series) }}
        options={chartOptions(metric)}
        aria-label={`${METRICS[metric][0]} by year from ${years[0]} to ${years[years.length - 1]}`} />
      {text ? <p className="trend-text">{text}</p> : null}
      <div className="stat-test"><div><strong>Mann–Kendall trend test</strong><p className="subtitle">Non-parametric monotonic trend test · α = 0.05</p></div>{statisticalTrend.insufficient ? <p className="subtitle">Not enough valid annual values (at least 8 required; found {statisticalTrend.n}).</p> : <><div className="stat-test-grid"><span><small>Direction</small><strong>{statisticalTrend.direction}</strong></span><span><small>p-value</small><strong>{statisticalTrend.p.toFixed(4)}</strong></span><span><small>Kendall τ</small><strong>{statisticalTrend.tau.toFixed(3)}</strong></span><span><small>Sen slope</small><strong>{statisticalTrend.senSlope >= 0 ? '+' : ''}{statisticalTrend.senSlope.toFixed(2)} / decade</strong></span></div><p className="subtitle">{statisticalTrend.significant ? `Statistically significant monotonic trend (p < 0.05): ${statisticalTrend.direction}.` : 'No statistically significant monotonic trend detected at the 0.05 level.'} This client-side estimate uses valid annual values and is not a causal attribution.</p></>}</div>
    </section>
  );
}
