import { useState } from 'react';
import { FIRST_YEAR, lastFullYear } from '../urlState.js';

function validate(start, end) {
  const first = Number(start);
  const last = Number(end);
  if (!start.trim() || !end.trim() || !Number.isInteger(first) || !Number.isInteger(last)) {
    return 'Enter whole years.';
  }
  const maximum = lastFullYear();
  if (first < FIRST_YEAR || first > maximum || last < FIRST_YEAR || last > maximum) {
    return `Years must be between ${FIRST_YEAR} and ${maximum}.`;
  }
  if (last < first) return 'End year must be on or after start year.';
  if (last - first + 1 < 10) return 'Choose at least 10 years.';
  return null;
}

export default function YearControls({ selection, onApply }) {
  const [start, setStart] = useState(String(selection.startYear));
  const [end, setEnd] = useState(String(selection.endYear));
  const [error, setError] = useState(null);

  function submit(event) {
    event.preventDefault();
    const message = validate(start, end);
    setError(message);
    if (!message) onApply({ startYear: Number(start), endYear: Number(end) });
  }

  return (
    <form className="year-controls" onSubmit={submit}>
      <YearField id="start-year" label="Start" value={start} onChange={setStart}
        onBlur={() => setError(validate(start, end))} />
      <YearField id="end-year" label="End" value={end} onChange={setEnd}
        onBlur={() => setError(validate(start, end))} />
      <button type="submit">Apply years</button>
      {error ? <p className="error" role="alert">{error}</p> : null}
    </form>
  );
}

function YearField({ id, label, value, onChange, onBlur }) {
  return (
    <label htmlFor={id}>{label}
      <input id={id} name={label.toLowerCase()} type="number" step="1" value={value}
        onChange={(event) => onChange(event.target.value)} onBlur={onBlur} />
    </label>
  );
}
