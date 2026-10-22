const WIDTH = 560;
const HEIGHT = 150;
const PADDING = 28;

export default function SalesChart({ units, forecast }) {
  if (!units || units.length === 0) return <p className="muted">No sales history.</p>;

  const maxValue = Math.max(...units, forecast || 0, 1);
  const baseline = HEIGHT - PADDING;
  const slotWidth = (WIDTH - PADDING * 2) / units.length;
  const toY = (value) => baseline - (value / maxValue) * (HEIGHT - PADDING * 2);

  return (
    <svg className="chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Daily sales for the last 28 days">
      <line x1={PADDING} y1={baseline} x2={WIDTH - PADDING} y2={baseline} stroke="#cbd5e1" />
      <text x={PADDING - 4} y={PADDING + 4} textAnchor="end" className="chart-label">{maxValue}</text>
      <text x={PADDING - 4} y={baseline} textAnchor="end" className="chart-label">0</text>

      {units.map((value, index) => (
        <rect
          key={index}
          x={PADDING + index * slotWidth + 1}
          y={toY(value)}
          width={slotWidth - 2}
          height={baseline - toY(value)}
          fill="#93c5fd"
        >
          <title>{`Day ${index + 1}: ${value} units`}</title>
        </rect>
      ))}

      {forecast != null && (
        <>
          <line
            x1={PADDING}
            y1={toY(forecast)}
            x2={WIDTH - PADDING}
            y2={toY(forecast)}
            stroke="#d97706"
            strokeWidth="2"
            strokeDasharray="5 4"
          />
          <text x={WIDTH - PADDING} y={toY(forecast) - 5} textAnchor="end" className="chart-label">
            forecast {forecast}/day
          </text>
        </>
      )}

      <text x={PADDING} y={HEIGHT - 8} className="chart-label">28 days ago</text>
      <text x={WIDTH - PADDING} y={HEIGHT - 8} textAnchor="end" className="chart-label">latest</text>
    </svg>
  );
}
