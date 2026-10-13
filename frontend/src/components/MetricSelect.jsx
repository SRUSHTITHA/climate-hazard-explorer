import { readParams, writeParams } from '../urlState.js';

export const METRICS = {
  heatwave_days: ['Heatwave days per year', 'Heatwave days'],
  event_count: ['Heatwave events per year', 'Events'],
  mean_intensity: ['Mean intensity, degrees C above threshold', 'Degrees C'],
  max_duration: ['Longest event, days', 'Days'],
};

export function initialMetric() {
  const selected = readParams().metric;
  return METRICS[selected] ? selected : 'heatwave_days';
}

export default function MetricSelect({ metric, onChange }) {
  return (
    <label>
      Metric{' '}
      <select value={metric} onChange={(event) => {
        onChange(event.target.value);
        writeParams({ ...readParams(), metric: event.target.value });
      }}>
        {Object.entries(METRICS).map(([key, meta]) => (
          <option key={key} value={key}>{meta[0]}</option>
        ))}
      </select>
    </label>
  );
}
