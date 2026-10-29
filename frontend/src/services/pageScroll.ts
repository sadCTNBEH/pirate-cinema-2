/** Scroll only the content pane, leaving the desktop title bar in place. */
export function scrollPageTo(id: string, behavior: ScrollBehavior = 'auto') {
  const pane = document.getElementById('page-container');
  const target = document.getElementById(id);
  if (!pane || !target || !pane.contains(target)) return;
  pane.scrollTo({
    top: Math.max(0, pane.scrollTop + target.getBoundingClientRect().top - pane.getBoundingClientRect().top - pane.clientTop),
    behavior,
  });
}
