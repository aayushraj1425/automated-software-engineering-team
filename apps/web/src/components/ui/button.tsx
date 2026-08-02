import type { ButtonHTMLAttributes } from "react";

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
      className={`inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...props}
    />
  );
}
