export const LAYOUTS = {
  ru: ['ёйцукенгшщзхъ', 'фывапролджэ', 'ячсмитьбю'],
  en: ['qwertyuiop', 'asdfghjkl', 'zxcvbnm'],
};
export type TextField = HTMLInputElement | HTMLTextAreaElement;
export function isTextField(element: HTMLElement | null): element is TextField {
  return !!element && ['INPUT', 'TEXTAREA'].includes(element.tagName)
    && !(element as TextField).readOnly && !(element as TextField).disabled
    && !['checkbox', 'radio', 'range', 'file', 'button', 'submit', 'reset', 'color', 'date', 'time', 'datetime-local', 'month', 'week'].includes((element as HTMLInputElement).type);
}
export function editText(field: TextField, text: string, operation: 'insert' | 'backspace' | 'clear' = 'insert') {
  let start = field.selectionStart ?? field.value.length;
  const end = field.selectionEnd ?? start;
  if (operation === 'backspace' && start === end) {
    start -= Array.from(field.value.slice(0, start)).at(-1)?.length || 0;
  }
  if (field.maxLength >= 0) text = text.slice(0, Math.max(0, field.maxLength - field.value.length + end - start));
  const value = operation === 'clear' ? '' : field.value.slice(0, start) + text + field.value.slice(end);
  const prototype = field.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(field, value);
  field.dispatchEvent(new Event('input', { bubbles: true }));
  try { field.setSelectionRange(Math.min(start + text.length, value.length), Math.min(start + text.length, value.length)); } catch { /* number/email fields */ }
}
