/*
 * Campo di testo multiriga.
 *
 * Perché `autoResize`: le note e i titoli dei blocchi crescono col contenuto;
 * misurare `scrollHeight` evita lo scroll interno per testi brevi senza
 * dipendere da `field-sizing`, non ancora affidabile ovunque in Electron.
 */
import {
  forwardRef,
  useCallback,
  useLayoutEffect,
  useRef,
  type TextareaHTMLAttributes,
} from 'react';
import { cn } from './utils.js';
import { CONTROL_FIELD, controlShell, useMergedRefs } from './shared.js';

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  mono?: boolean;
  invalid?: boolean;
  /** Adatta l'altezza al contenuto invece di mostrare la scrollbar. */
  autoResize?: boolean;
  /** Classi della `<textarea>` nativa; `className` va sul contenitore. */
  textareaClassName?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  {
    mono = false,
    invalid,
    autoResize = false,
    className,
    textareaClassName,
    disabled,
    rows = 3,
    onInput,
    value,
    ...props
  },
  ref,
) {
  const innerRef = useRef<HTMLTextAreaElement>(null);
  const mergedRef = useMergedRefs(innerRef, ref);
  const isInvalid = invalid ?? (props['aria-invalid'] === true || props['aria-invalid'] === 'true');

  const resize = useCallback(() => {
    const el = innerRef.current;
    if (!el || !autoResize) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [autoResize]);

  useLayoutEffect(resize, [resize, value]);

  return (
    <span
      className={cn(controlShell(isInvalid, !!disabled), 'items-stretch', className)}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          event.preventDefault();
          innerRef.current?.focus();
        }
      }}
    >
      <textarea
        ref={mergedRef}
        rows={rows}
        value={value}
        disabled={disabled}
        aria-invalid={isInvalid || undefined}
        onInput={(event) => {
          resize();
          onInput?.(event);
        }}
        className={cn(
          CONTROL_FIELD,
          'min-h-[60px] w-full px-[11px] py-[5px] leading-5',
          autoResize ? 'resize-none overflow-hidden' : 'resize-y',
          mono && 'font-mono',
          textareaClassName,
        )}
        {...props}
      />
    </span>
  );
});
