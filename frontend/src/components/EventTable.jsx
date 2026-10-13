import { useState } from 'react';

const DATE = { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' };
const format = (iso) => new Date(iso).toLocaleDateString(undefined, DATE);
const number = (value) => (value == null ? 'No data' : value.toFixed(1));

const SORTS = {
  newest: (a, b) => b.start.localeCompare(a.start),
  longest: (a, b) => b.duration_days - a.duration_days || b.start.localeCompare(a.start),
  intense: (a, b) => (b.intensity ?? -1) - (a.intensity ?? -1) || b.start.localeCompare(a.start),
};

function Select({ label, value, options, onChange }) {
  return (
    <label>
      {label}{' '}<select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}
      </select>
    </label>
  );
}

function Table({ rows, multi }) {
  const columns = [
    ['Start', (event) => format(event.start)],
    ['End', (event) => format(event.end)],
    ['Days', (event) => event.duration_days],
    ['Peak (deg C)', (event) => number(event.peak_tmax)],
    ['Intensity (deg C above threshold)', (event) => number(event.intensity)],
    ['Cell', (event) => event.cell_id, true],
  ];
  const shown = columns.filter(([, , cellOnly]) => !cellOnly || multi);
  return (
    <table>
      <thead>
        <tr>{shown.map(([label]) => <th key={label} scope="col">{label}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((event) => (
          <tr key={`${event.cell_id}-${event.start}`}>
            {shown.map(([label, cell]) => <td key={label}>{cell(event)}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Body({ events, rows, visible, total, multi }) {
  if (rows.length === 0) return <p>No heatwave events in the selected range.</p>;
  const caption = events.length < total ? ` Showing ${events.length} of ${total} events.` : '';
  return (
    <>
      <p className="table-caption">Events are listed for years with sufficient data.{caption}</p>
      <Table rows={rows.slice(0, visible)} multi={multi} />
    </>
  );
}

export default function EventTable({ events, total }) {
  const [sort, setSort] = useState('newest');
  const [year, setYear] = useState('all');
  const [visible, setVisible] = useState(25);
  const multi = new Set(events.map((event) => event.cell_id)).size > 1;
  const years = [...new Set(events.map((event) => event.year))].sort((a, b) => b - a);
  const rows = events.filter((e) => year === 'all' || e.year === Number(year)).sort(SORTS[sort]);
  return (
    <section className="events" aria-label="Heatwave events">
      <h2>Events</h2>
      <Select label="Sort" value={sort} onChange={(v) => { setSort(v); setVisible(25); }}
        options={[['newest', 'Newest'], ['longest', 'Longest'], ['intense', 'Most intense']]} />
      <Select label="Year" value={year} onChange={(v) => { setYear(v); setVisible(25); }}
        options={[['all', 'All years'], ...years.map((item) => [item, item])]} />
      <Body events={events} rows={rows} visible={visible} total={total} multi={multi} />
      {visible < rows.length ? (
        <button type="button" onClick={() => setVisible(visible + 25)}>Show more</button>
      ) : null}
    </section>
  );
}
