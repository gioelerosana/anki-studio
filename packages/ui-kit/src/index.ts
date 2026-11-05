/*
 * Punto d'ingresso del ui-kit.
 *
 * Perché un unico barrel: le app importano solo da `@anki-studio/ui-kit`, così i file
 * interni (`shared.ts`) restano privati e si può riorganizzare il package senza
 * toccare i chiamanti. L'API pubblica è descritta in docs/DESIGN-SYSTEM.md.
 */
export * from './utils.js';
export * from './Spinner.js';
export * from './Button.js';
export * from './IconButton.js';
export * from './Badge.js';
export * from './Kbd.js';
export * from './Input.js';
export * from './Textarea.js';
export * from './Select.js';
export * from './Switch.js';
export * from './Checkbox.js';
export * from './Field.js';
export * from './Separator.js';
export * from './Banner.js';
export * from './Card.js';
export * from './EmptyHint.js';
export * from './Tooltip.js';
export * from './ViewSwitcher.js';
export * from './HeaderBar.js';
export * from './Toast.js';
export * from './Modal.js';
export * from './Menu.js';
