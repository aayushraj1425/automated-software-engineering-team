import type { ButtonHTMLAttributes } from "react";

import { focusRing } from "./focus-ring";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

/** The app's one button. Variants match the styles that were previously written
 * inline everywhere (a light "primary", an outlined "secondary", a text "ghost",
 * and a "danger"), so pages read consistently. Defaults to type="button" — pass
 * type="submit" for form actions. */
const VARIANTS: Record<Variant, string> = {
  primary: "bg-zinc-100 text-zinc-900 hover:bg-white disabled:opacity-50",
  secondary: "border border-zinc-700 text-zinc-300 hover:border-zinc-500 disabled:opacity-50",
  ghost: "text-zinc-400 hover:text-zinc-100 disabled:opacity-50",
  danger: "border border-red-900 text-red-300 hover:border-red-700 disabled:opacity-50",
};

const SIZES: Record<Size, string> = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-4 py-2 text-sm",
};

/** The button look as a class string, so an element that must not be a <button>
 * — a Next <Link> styled as a button, say — can share the exact same styling
 * instead of hand-copying it. Button itself is built from this. */
export function buttonClassName(variant: Variant = "primary", size: Size = "md"): string {
  return `inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed ${focusRing} ${VARIANTS[variant]} ${SIZES[size]}`;
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  type,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      type={type ?? "button"}
      className={`${buttonClassName(variant, size)} ${className}`}
      {...props}
    />
  );
}
