/** The one id the "Skip to content" link targets, and the props that make an
 * element a valid skip destination. Kept in a single place so the link (in the
 * workspace layout) and whichever element is the page's main landmark —
 * WorkspaceShell's <main> or chat's own <section> — can't drift apart. A rename
 * here changes all of them together instead of silently breaking one route.
 * tabIndex -1 lets the link move keyboard focus to the target, not just scroll. */
export const MAIN_CONTENT_ID = "main-content";

export const mainContentProps = { id: MAIN_CONTENT_ID, tabIndex: -1 } as const;
