function csvCell(value) {
  if (value == null) return '';
  let text = typeof value === 'object' ? JSON.stringify(value) : String(value);
  if (/^[=+@\-\t\r]/.test(text)) text = `'${text}`; // prevent spreadsheet formula execution
  return `"${text.replaceAll('"', '""')}"`;
}
function download(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; anchor.click();
  URL.revokeObjectURL(url);
}
export function exportCsv(data, selection) {
  const lines = [
    ['Climate Hazard Explorer export'],
    ['Hazard', selection.hazard], ['Start year', selection.startYear], ['End year', selection.endYear],
    [], ['ANNUAL SERIES'],
  ];
  const series = data.series ?? [];
  const seriesKeys = [...new Set(series.flatMap((row) => Object.keys(row)))];
  lines.push(seriesKeys, ...series.map((row) => seriesKeys.map((key) => row[key] ?? '')));
  lines.push([], ['EVENTS']);
  const events = data.events ?? [];
  const eventKeys = [...new Set(events.flatMap((row) => Object.keys(row)))];
  if (eventKeys.length) lines.push(eventKeys, ...events.map((row) => eventKeys.map((key) => row[key] ?? '')));
  lines.push([], ['INSIGHTS'], ['Level', 'Key', 'Text']);
  for (const insight of data.insights ?? []) lines.push([insight.level, insight.key, insight.text]);
  download('\uFEFF' + lines.map((row) => row.map(csvCell).join(',')).join('\r\n'), `climate-hazard-${selection.startYear}-${selection.endYear}.csv`, 'text/csv;charset=utf-8');
}
export function exportPdf() {
  window.print();
}
