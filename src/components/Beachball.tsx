/**
 * Schematic focal-sphere ("beachball") diagram.
 *
 * This is a deliberately simplified visualisation: each nodal plane is drawn
 * as its approximate trace in an equal-angle stereographic projection
 * (ellipse rotated by strike, eccentricity from cos(dip)). It is meant for
 * quick orientation, not for publication-grade seismology.
 */

export function Beachball({
  strike,
  dip,
  size = 190,
}: {
  strike: number | null;
  dip: number | null;
  size?: number;
}) {
  const r = 46;
  const s = strike ?? 0;
  const d = Math.max(5, Math.min(90, dip ?? 45));
  const ry = r * Math.cos((d * Math.PI) / 180);

  return (
    <svg
      viewBox="-55 -55 110 110"
      width={size}
      height={size}
      className="shrink-0"
      role="img"
      aria-label="Схема механизма очага"
    >
      <defs>
        <clipPath id="bb-clip">
          <circle cx="0" cy="0" r={r} />
        </clipPath>
        <radialGradient id="bb-shade" cx="35%" cy="30%" r="80%">
          <stop offset="0%" stopColor="#fbbf24" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#b45309" stopOpacity="0.9" />
        </radialGradient>
      </defs>

      <circle cx="0" cy="0" r={r} fill="#0d1526" stroke="#33507a" strokeWidth="1.2" />

      <g clipPath="url(#bb-clip)">
        {/* compression quadrants (schematic) */}
        <g transform={`rotate(${s})`}>
          <rect x="-55" y="-55" width="110" height="55" fill="url(#bb-shade)" opacity={dip && dip < 45 ? 0.85 : 0.25} />
          <rect x="-55" y="0" width="110" height="55" fill="url(#bb-shade)" opacity={dip && dip < 45 ? 0.25 : 0.85} />
          {/* nodal plane 1 trace */}
          <line x1={-55} y1="0" x2="55" y2="0" stroke="#5eead4" strokeWidth="2" />
          <line x1="-55" y1="0" x2="55" y2="0" stroke="#5eead4" strokeWidth="5" opacity="0.15" />
          {/* nodal plane 2 trace (approx) */}
          <ellipse cx="0" cy="0" rx={Math.max(ry, 2)} ry={r} fill="none" stroke="#fbbf24" strokeWidth="1.6" transform="rotate(90)" />
        </g>
      </g>

      {/* strike direction marker (North = up) */}
      <g transform={`rotate(${s})`}>
        <line x1="0" y1={-r - 6} x2="0" y2={-r + 2} stroke="#5eead4" strokeWidth="2.4" />
      </g>
      <text x="0" y={-r - 9} textAnchor="middle" fill="#8fa3c0" fontSize="8" fontFamily="monospace">
        N
      </text>
      <text x={r + 10} y="3" textAnchor="middle" fill="#55688c" fontSize="7" fontFamily="monospace">
        E
      </text>
    </svg>
  );
}
