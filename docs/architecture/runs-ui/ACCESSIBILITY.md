# Web App Accessibility Foundations

Plain language. The web app aims to be usable by keyboard and screen reader, not
just mouse and sight. These are the shared pieces that make that true everywhere
at once, so a new page inherits them instead of re-solving them.

## Keyboard focus is always visible

Every interactive element shows a **focus ring** when reached by keyboard — the
sky outline you see as you Tab through the app. It is one token,
`focusRing` (`components/ui/focus-ring.ts`), applied through the shared
primitives:

- **Buttons and button-styled links** get it from `buttonClassName`
  (`components/ui/button.tsx`), so every page's buttons are covered by using the
  shared `Button`.
- **The top navigation** (`components/ui/app-nav.tsx`), the **copy button**
  (`components/ui/copy-button.tsx`), and the **code-block toggle** apply the same
  token directly.

It uses `focus-visible`, not `focus`, so the ring appears for keyboard and
assistive-tech users but not on a mouse click. Text inputs (the chat composer)
show focus by brightening their border instead — same intent, input-appropriate.

## Landmarks and skip link

The signed-in layout (`app/(workspace)/layout.tsx`) renders a **"Skip to
content"** link as the first focusable element; it jumps past the nav to the
`#main-content` landmark (`components/ui/main-content.ts`). The id lives in one
place so the link and the target can never drift apart.

## Errors are announced, not just shown

Action failures render through `FormError` (`components/ui/feedback.tsx`), which
carries `role="alert"` — a screen reader announces the message the moment it
appears, instead of the text changing silently. The `Spinner` carries
`role="status"` with an accessible "Loading" label for the same reason.

## Motion respects the user's setting

Under `prefers-reduced-motion` the decorative skeleton pulse stops (`globals.css`
pauses the `.skeleton` class only). Meaningful motion — the streaming cursor and
the "Live" run indicator — keeps animating, because it carries information.

## Input methods

The chat composer's Enter-to-send is guarded against IME composition
(`isComposing`), so confirming a candidate character (e.g. CJK input) never sends
a half-typed message.
