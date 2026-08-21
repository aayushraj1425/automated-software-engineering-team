/** The app's single keyboard-focus indicator. `focus-visible` (not `focus`) so
 * it appears for keyboard and assistive-tech users but not on a mouse click.
 * sky-500 is the app's accent (links are text-sky-400) and stays visible on
 * both the dark surfaces and the light "primary" button; the offset matches the
 * zinc-950 body so the ring reads as a clean gap. Applied through the shared
 * primitives (Button, CopyButton, …) so every interactive element gets the same
 * visible focus for free — see docs/architecture/runs-ui/ACCESSIBILITY.md. */
export const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950";
