export const HAZARD_DEFAULT = 'heatwave';
export const METRIC_DEFAULT = 'heatwave_days';
export const FIRST_YEAR = 1990;
const BOX_KEYS = ['south', 'west', 'north', 'east'];

export function lastFullYear() {
  return new Date().getUTCFullYear() - 1;
}

function defaults() {
  return {
    hazard: HAZARD_DEFAULT,
    metric: METRIC_DEFAULT,
    startYear: FIRST_YEAR,
    endYear: lastFullYear(),
    region: null,
  };
}

function toNumber(value) {
  const number = Number(value);
  return value === null || value === '' || !Number.isFinite(number) ? null : number;
}

function toYear(value) {
  const year = toNumber(value);
  return Number.isInteger(year) ? year : null;
}

function readRegion(params) {
  const id = params.get('region');
  if (id) return { id };
  const lat = toNumber(params.get('lat'));
  const lon = toNumber(params.get('lon'));
  if (lat !== null && lon !== null) return { lat, lon };
  const box = Object.fromEntries(BOX_KEYS.map((key) => [key, toNumber(params.get(key))]));
  return BOX_KEYS.every((key) => box[key] !== null) ? box : null;
}

function writeRegion(params, region) {
  if (!region) return;
  if (region.id) params.set('region', region.id);
  else if (Number.isFinite(region.lat) && Number.isFinite(region.lon)) {
    params.set('lat', region.lat);
    params.set('lon', region.lon);
  } else if (BOX_KEYS.every((key) => Number.isFinite(region[key]))) {
    for (const key of BOX_KEYS) params.set(key, region[key]);
  }
}

export function readParams() {
  const base = defaults();
  const params = new URLSearchParams(window.location.search);
  return {
    hazard: params.get('hazard') || base.hazard,
    metric: params.get('metric') || base.metric,
    startYear: toYear(params.get('start')) ?? base.startYear,
    endYear: toYear(params.get('end')) ?? base.endYear,
    region: readRegion(params),
  };
}

export function writeParams(state) {
  const base = defaults();
  const params = new URLSearchParams();
  if (state.hazard && state.hazard !== base.hazard) params.set('hazard', state.hazard);
  if (state.metric && state.metric !== base.metric) params.set('metric', state.metric);
  if (state.startYear && state.startYear !== base.startYear) params.set('start', state.startYear);
  if (state.endYear && state.endYear !== base.endYear) params.set('end', state.endYear);
  writeRegion(params, state.region);
  const query = params.toString();
  window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`);
}
