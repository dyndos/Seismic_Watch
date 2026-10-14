/**
 * Fault type classification and slip vector calculation.
 *
 * Based on Aki & Richards (2002) convention for strike/dip/rake.
 *
 * Fixes vs the Python prototype:
 *  - The prototype used azimuth = strike + rake, which ignores the dip angle.
 *    Here the horizontal projection accounts for dip: only the component
 *    sin(rake)*cos(dip) projects onto the horizontal dip direction.
 *  - Returns explicit "compression/convergence" direction contextualised
 *    by fault type, which is the business question ("куда движется плита").
 */

import type { FaultType } from "./types";

export function classifyFault(rake: number | null | undefined): FaultType {
  if (rake === null || rake === undefined || Number.isNaN(rake)) return "unknown";

  let r = rake % 360;
  if (r > 180) r -= 360;
  if (r < -180) r += 360;

  const abs = Math.abs(r);
  if (abs <= 30 || abs >= 150) return "strike_slip";
  if (r >= 60 && r <= 120) return "thrust";
  if (r <= -60 && r >= -120) return "normal";
  return "oblique";
}

const toRad = (d: number) => (d * Math.PI) / 180;

function azFromEN(east: number, north: number): number {
  const az = (Math.atan2(east, north) * 180) / Math.PI;
  return (az + 360) % 360;
}

/**
 * Horizontal projection of the slip vector (lower plate / footwall motion).
 *
 * Geometry (Aki & Richards strike φ, dip δ, rake λ):
 *   slip unit vector = cos(λ)·ê_strike + sin(λ)·ê_downdip
 *   where ê_strike has azimuth φ and ê_downdip has azimuth φ+90 but only
 *   cos(δ) of it lies in the horizontal plane.
 *
 * Interpretation by fault type:
 *   - thrust (λ≈+90):  dip azimuth φ+90 → direction the lower plate moves;
 *     for subduction zones this equals the plate convergence direction.
 *   - normal (λ≈−90):  opposite dip → extension direction.
 *   - strike-slip:     along strike (lateral motion).
 *
 * Note: for the hanging-wall block the direction is opposite (±180°).
 */
export function calcSlipProjection(
  strike: number | null,
  dip: number | null,
  rake: number | null,
): number | null {
  if (strike === null || rake === null) return null;
  if (dip === null) {
    // vertical-fault fallback (matches prototype behaviour)
    return Math.round(((strike + rake) % 360 + 360) % 360 * 10) / 10;
  }
  const phi = toRad(strike);
  const lam = toRad(rake);
  const cosDelta = Math.cos(toRad(dip));

  const cosLam = Math.cos(lam);
  const sinLamCosDelta = Math.sin(lam) * cosDelta;

  const east = cosLam * Math.sin(phi) + sinLamCosDelta * Math.sin(phi + Math.PI / 2);
  const north = cosLam * Math.cos(phi) + sinLamCosDelta * Math.cos(phi + Math.PI / 2);

  if (Math.abs(east) < 1e-9 && Math.abs(north) < 1e-9) return null; // vertical slip, no horizontal part
  return Math.round(azFromEN(east, north) * 10) / 10;
}

/**
 * Direction the OVERRIDING plate is being pushed / direction of plate
 * interaction relevant for chaining. For thrusts this is the dip azimuth
 * (convergence), for normals the extension, for strike-slip both strike
 * directions are equally plausible (we return NaN-safe strike az).
 */
export function contextualDirectionLabel(faultType: FaultType): string {
  switch (faultType) {
    case "thrust":
      return "Направление конвергенции (схождения) плит — поддвижная плита движется в эту сторону";
    case "normal":
      return "Направление экстенсии (расхождения) плит";
    case "strike_slip":
      return "Направление бокового сдвига блока по разлому";
    case "oblique":
      return "Результирующее направление косого скольжения";
    default:
      return "Направление скольжения не определено";
  }
}

export const FAULT_TYPE_RU: Record<FaultType, string> = {
  strike_slip: "Сдвиг",
  thrust: "Надвиг",
  normal: "Сброс",
  oblique: "Косое скольжение",
  unknown: "Не определён",
};

export const FAULT_TYPE_DESCRIPTION_RU: Record<FaultType, string> = {
  strike_slip: "Плиты скользят горизонтально мимо друг друга. Напряжение передаётся вдоль разлома — повышенный риск на соседних сегментах той же системы разломов.",
  thrust: "Плиты сходятся, одна надвигается на другую. Энергия подзадвигания перенаправляет нагрузку вдоль зоны субдукции — характерны цепочки в удалённых частях той же плитной системы.",
  normal: "Плиты расходятся, блок опускается. Растяжение может активировать параллельные разломы внутри плиты.",
  oblique: "Комбинация сдвига и надвига/сброса. Передача напряжений возможна и вдоль, и поперёк разлома.",
  unknown: "Тип разлома не определён (нет данных тензора сейсмического момента). Межрегиональный анализ ограничен.",
};
