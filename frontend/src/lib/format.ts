export const money = (value: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
export const bps = (value: number) => `${Number((value * 10000).toFixed(1))} bps`;
export const percent = (value: number) => `${Number(value.toFixed(2))}%`;
export const tierLabel = (score: number) => score >= 720 ? "Tier 1 · Auto-bind eligible" : score >= 580 ? "Tier 2 · Conditional bind" : "Tier 3 · Remediation required";

export const perilLabel = (peril: import("@/types/resiliscore").Peril) => ({
  FLOOD: "Flood", WILDFIRE: "Wildfire", WIND_HAIL: "Wind / hail",
  PLUVIAL: "Street/rain flooding", SEWER_BACKUP: "Sewer backup",
})[peril];
