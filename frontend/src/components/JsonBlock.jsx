export default function JsonBlock({ label, value }) {
  if (value === null || value === undefined) return null;
  return (
    <details className="json">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
