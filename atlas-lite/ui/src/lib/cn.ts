import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Conditional className builder with Tailwind-aware merge semantics. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
