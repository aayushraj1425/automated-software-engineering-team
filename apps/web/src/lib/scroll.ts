/** True when a scroll container sits at (or within `threshold` px of) its
 * bottom. It's the test for whether to keep auto-following streamed content:
 * follow while the user is at the bottom, but stop yanking them down the moment
 * they scroll up to read. Pulled out as a pure function of the three scroll
 * metrics so the decision is testable without a real layout. */
export function isScrolledToBottom(
  el: { scrollTop: number; scrollHeight: number; clientHeight: number },
  threshold = 60,
): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}
