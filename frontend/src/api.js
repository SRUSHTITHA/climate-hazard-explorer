const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
  }
}

function buildQuery(params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, value);
    }
  }
  return query.toString();
}

async function readError(response) {
  const fallback = `Request failed (${response.status}).`;
  try {
    const body = await response.json();
    return new ApiError(body.code || 'unknown_error', body.message || fallback);
  } catch {
    return new ApiError('unknown_error', fallback);
  }
}

async function getJson(path, params, signal) {
  const query = buildQuery(params);
  const baseUrl = BASE_URL.replace(/\/+$/, '');
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const url = `${baseUrl}${normalizedPath}${query ? `?${query}` : ''}`;

  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw await readError(response);
  }
  return response.json();
}

export const fetchRegions = ({ signal } = {}) => getJson('/api/regions', null, signal);

export const fetchAnalysis = (params, { signal } = {}) =>
  getJson('/api/analysis', params, signal);
