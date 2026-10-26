export type Direction = 'left' | 'right' | 'up' | 'down';
type Rect = Pick<DOMRect, 'left' | 'top' | 'right' | 'bottom' | 'width' | 'height'>;
export function nearestIndex(origin: Rect, rects: Rect[], direction: Direction): number {
  const horizontal = direction === 'left' || direction === 'right';
  const sign = direction === 'left' || direction === 'up' ? -1 : 1;
  const ox = origin.left + origin.width / 2, oy = origin.top + origin.height / 2;
  let best = -1, score = Infinity;
  rects.forEach((r, index) => {
    const dx = r.left + r.width / 2 - ox, dy = r.top + r.height / 2 - oy;
    const primary = (horizontal ? dx : dy) * sign;
    if (primary <= 1) return;
    const secondary = Math.abs(horizontal ? dy : dx);
    const overlap = horizontal ? r.bottom > origin.top && r.top < origin.bottom : r.right > origin.left && r.left < origin.right;
    const distance = primary + secondary * (overlap ? 1 : 4);
    if (distance < score) { best = index; score = distance; }
  });
  return best;
}
export function visible(element: HTMLElement): boolean {
  return element.isConnected && element.getClientRects().length > 0
    && !element.closest('[hidden], [inert], [aria-hidden="true"]')
    && !element.matches(':disabled, [aria-disabled="true"]')
    && getComputedStyle(element).visibility !== 'hidden';
}
export function focusScope(): HTMLElement {
  const dialogs = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"], [data-focus-scope]')).filter(visible);
  return dialogs.at(-1) || document.body;
}
export function candidates(scope = focusScope()): HTMLElement[] {
  return Array.from(scope.querySelectorAll<HTMLElement>('button, a[href], input:not([type="hidden"]), select, textarea, [tabindex="0"], [role="button"], [data-focusable]')).filter(visible);
}
export function focusElement(element?: HTMLElement | null) {
  if (!element) return;
  if (element.tabIndex < 0) element.tabIndex = 0;
  element.focus({ preventScroll: true });
  element.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'instant' });
}
export function moveFocus(direction: Direction) {
  const elements = candidates();
  const current = document.activeElement as HTMLElement;
  if (!elements.includes(current)) { focusElement(elements[0]); return; }
  focusElement(elements[nearestIndex(current.getBoundingClientRect(), elements.map(e => e.getBoundingClientRect()), direction)]);
}
