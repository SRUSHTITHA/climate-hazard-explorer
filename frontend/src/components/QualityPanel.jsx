export default function QualityPanel({ quality, attribution, cellIds }) {
  if (!quality) return null;
  const shortfall = quality.min_cells_valid < quality.cells;
  return (
    <section className="quality" aria-label="Data quality">
      <h2>Data quality</h2>
      <p>Valid years: {quality.valid_years} of {quality.total_years}</p>
      <p title={(cellIds ?? []).join(', ')}>Grid cells used: {quality.cells}</p>
      {shortfall ? <p>Some years use fewer cells (minimum {quality.min_cells_valid}).</p> : null}
      <p>
        {attribution}{' '}
        <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">
          Weather data by Open-Meteo.com
        </a>
      </p>
    </section>
  );
}
