export default function InsightCard({ insights }) {
  if (!insights || insights.length === 0) return null;
  return (
    <section className="insights" aria-label="Insights">
      <h2>Insights</h2>
      <ul>
        {insights.map((insight) => (
          <li
            key={insight.key}
            className={insight.level === 'caution' ? 'insight insight-caution' : 'insight'}
          >
            {insight.level === 'caution' ? <strong className="note">Note: </strong> : null}
            {insight.text}
          </li>
        ))}
      </ul>
    </section>
  );
}
