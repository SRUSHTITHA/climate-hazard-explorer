function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
function normalPValue(z) {
  // Two-sided normal approximation using a standard polynomial tail approximation.
  const x = Math.abs(z);
  const t = 1 / (1 + 0.2316419 * x);
  const density = 0.3989422804014327 * Math.exp(-0.5 * x * x);
  const tail = density * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  return Math.max(0, Math.min(1, 2 * tail));
}
export function mannKendall(series, metric) {
  const rows = series.filter((row) => row.valid !== false && row[metric] != null && Number.isFinite(Number(row.year)) && Number.isFinite(Number(row[metric])));
  const n = rows.length;
  if (n < 8) return { n, insufficient: true };
  let s = 0;
  const slopes = [];
  for (let i = 0; i < n - 1; i++) for (let j = i + 1; j < n; j++) {
    const delta = Number(rows[j][metric]) - Number(rows[i][metric]);
    s += Math.sign(delta);
    const yearGap = Number(rows[j].year) - Number(rows[i].year);
    if (yearGap) slopes.push(delta / yearGap * 10);
  }
  const counts = new Map();
  rows.forEach((row) => counts.set(Number(row[metric]), (counts.get(Number(row[metric])) ?? 0) + 1));
  const tieTerm = [...counts.values()].reduce((sum, t) => sum + t * (t - 1) * (2*t + 5), 0);
  const variance = (n * (n - 1) * (2*n + 5) - tieTerm) / 18;
  if (variance <= 0) return { n, s, tau: 0, p: 1, senSlope: 0, direction: 'no change' };
  const z = s > 0 ? (s - 1) / Math.sqrt(variance) : s < 0 ? (s + 1) / Math.sqrt(variance) : 0;
  const p = normalPValue(z);
  const tau = s / (n * (n - 1) / 2);
  const senSlope = median(slopes);
  return { n, s, tau, p, senSlope, direction: s > 0 ? 'increasing' : s < 0 ? 'decreasing' : 'no monotonic trend', significant: p < 0.05 };
}
