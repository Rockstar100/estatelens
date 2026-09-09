import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const BASIS_LABEL: Record<string, string> = {
  total: "total",
  starting: "starting from",
  monthly_rent: "per month",
  annual_rent: "per year",
  unspecified: "",
};

/** Format a price the same way everywhere. Unknown -> "Price not listed". */
export function formatPrice(
  amount: string | null,
  currency: string | null,
  basis: string,
): string {
  if (amount === null || amount === undefined) return "Price not listed";
  const n = Number(amount);
  if (!Number.isFinite(n)) return "Price not listed";
  const nice = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: n % 1 === 0 ? 0 : 2,
  }).format(n);
  const suffix = BASIS_LABEL[basis] ? ` ${BASIS_LABEL[basis]}` : "";
  return `${currency ? currency + " " : ""}${nice}${suffix}`;
}

export function formatArea(value: string | null, unit: string | null): string | null {
  if (!value) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  const nice = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
  return `${nice} ${unit ?? "sqm"}`;
}

export function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

export function relativeDate(iso: string | null): string {
  if (!iso) return "unknown";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function shortId(): string {
  return Math.random().toString(36).slice(2, 10);
}
