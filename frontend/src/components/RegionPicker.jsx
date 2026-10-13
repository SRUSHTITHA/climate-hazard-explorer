import { useState } from 'react';

const BOX_KEYS = ['south', 'west', 'north', 'east'];
const FIELDS = {
  point: [['lat', 'Latitude'], ['lon', 'Longitude']],
  box: [['south', 'South'], ['west', 'West'], ['north', 'North'], ['east', 'East']],
};
const GROUPS = [
  ['Indian cities', (item) => item.kind === 'city' && item.country === 'India'],
  ['Indian states and UTs', (item) => item.kind === 'state'],
  ['Global cities', (item) => item.kind === 'global' || item.country !== 'India'],
];
const STATE_NOTE = 'State presets cover a representative 0.75 degree box around the capital, not the whole state.';
const BOX_NOTE = 'Boxes are limited to 9 grid cells (about 0.75 degrees square).';
const COLD_NOTE = 'First request for a new region can take several minutes';
const text = (value) => (value == null ? '' : String(value));
const initialMode = (region) => (!region || region.id ? 'preset' : region.lat != null ? 'point' : 'box');
const initialDraft = (region) => Object.fromEntries([...BOX_KEYS, 'lat', 'lon'].map((key) => [key, text(region?.[key])]));

function validate(mode, draft) {
  const values = FIELDS[mode].map(([key]) => Number(draft[key]));
  if (FIELDS[mode].some(([key], index) => !draft[key].trim() || !Number.isFinite(values[index]))) return 'Enter a finite number in every field.';
  if (mode === 'point' && (values[0] < -90 || values[0] > 90)) return 'Latitude must be between -90 and 90.';
  if (mode === 'point' && (values[1] < -180 || values[1] > 180)) return 'Longitude must be between -180 and 180.';
  if (mode === 'box' && values[0] >= values[2]) return 'South must be less than north.';
  if (mode === 'box' && values[1] >= values[3]) return 'West must be less than east.';
  return null;
}

export default function RegionPicker({ regions, selection, loading, onApply }) {
  const [mode, setMode] = useState(() => initialMode(selection.region));
  const [draft, setDraft] = useState(() => initialDraft(selection.region));
  const [error, setError] = useState(null);
  const change = (key) => (event) => setDraft((prev) => ({ ...prev, [key]: event.target.value }));

  function submit(event) {
    event.preventDefault();
    const message = validate(mode, draft);
    if (message) setError(message);
    else {
      setError(null);
      onApply({
        region: mode === 'point'
          ? { lat: Number(draft.lat), lon: Number(draft.lon) }
          : Object.fromEntries(BOX_KEYS.map((key) => [key, Number(draft[key])])),
      });
    }
  }

  return (
    <section className="picker" aria-label="Region selection">
      <label>Mode{' '}
        <select value={mode} onChange={(event) => { setMode(event.target.value); setError(null); }}>
          <option value="preset">Preset</option>
          <option value="point">Point</option>
          <option value="box">Box</option>
        </select>
      </label>
      {mode === 'preset'
        ? <label>Preset <select value={selection.region?.id ?? ''} onChange={(event) => onApply({ region: { id: event.target.value } })}>
            <option value="">Choose a region...</option>
            {GROUPS.map(([label, test]) => {
              const items = regions.filter(test);
              return items.length ? <optgroup key={label} label={label}>
                {items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </optgroup> : null;
            })}
          </select></label>
        : <form onSubmit={submit}>
            <div className="fields">
              {FIELDS[mode].map(([key, label]) => <label key={key} htmlFor={`region-${key}`}>{label}
                <input id={`region-${key}`} name={key} type="text" inputMode="decimal" value={draft[key]}
                  onChange={change(key)} aria-describedby={error ? 'region-error' : undefined}
                  aria-invalid={Boolean(error)} /></label>)}
            </div>
            <button type="submit">Apply</button>
            {error ? <p id="region-error" className="error" role="alert">{error}</p> : null}
          </form>}
      <p className="subtitle">{mode === 'box' ? `${STATE_NOTE} ${BOX_NOTE}` : STATE_NOTE}</p>
      {loading ? <p className="subtitle" aria-live="polite">{COLD_NOTE}</p> : null}
    </section>
  );
}
