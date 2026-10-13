import { useQuery } from '@tanstack/react-query';

import { fetchAnalysis, fetchRegions } from './api.js';
import { FIRST_YEAR, lastFullYear } from './urlState.js';

const BOX_KEYS = ['south', 'west', 'north', 'east'];

function regionQuery(selection, presets) {
  const { region } = selection;
  if (!region) return null;
  const source = region.id ? presets.find((item) => item.id === region.id) : region;
  if (!source) return null;
  if (source.lat != null && source.lon != null) return { lat: source.lat, lon: source.lon };
  if (BOX_KEYS.every((key) => source[key] != null)) {
    return Object.fromEntries(BOX_KEYS.map((key) => [key, source[key]]));
  }
  return null;
}

function validYears(selection) {
  const { startYear, endYear } = selection;
  return Number.isInteger(startYear) && Number.isInteger(endYear)
    && startYear >= FIRST_YEAR && endYear <= lastFullYear() && endYear >= startYear
    && endYear - startYear + 1 >= 10;
}
export function useAnalysis(selection) {
  const regions = useQuery({ queryKey: ['regions'], queryFn: fetchRegions });
  const region = validYears(selection) && regions.data
    ? regionQuery(selection, regions.data)
    : null;
  const params = region
    ? {
        hazard: selection.hazard,
        start_year: selection.startYear,
        end_year: selection.endYear,
        ...region,
      }
    : null;
  const analysis = useQuery({
    queryKey: ['analysis', params],
    queryFn: ({ signal }) => fetchAnalysis(params, { signal }),
    enabled: Boolean(params),
  });
  return { regions, params, analysis };
}
