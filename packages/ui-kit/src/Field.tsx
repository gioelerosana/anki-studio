/*
 * Etichetta + controllo + suggerimento/errore.
 *
 * Perché `Field` collega da solo `label`, `aria-describedby` e `aria-invalid`:
 * nei form dell'app (esporta, importa, proprietà del blocco) ogni campo ripeteva
 * a mano id e legami ARIA. Se il figlio è un singolo elemento React gli viene
 * assegnato un `id` (se non ne ha già uno) e gli stati di errore.
 */
import {
  Fragment,
  cloneElement,
  forwardRef,
  isValidElement,
  useId,
  type HTMLAttributes,
  type LabelHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from 'react';
import { cn } from './utils.js';

export const Label = forwardRef<HTMLLabelElement, LabelHTMLAttributes<HTMLLabelElement>>(
  function Label({ className, ...props }, ref) {
    return (
      <label
        ref={ref}
        className={cn('text-xs font-medium leading-4 text-foreground', className)}
        {...props}
      />
    );
  },
);

export interface FieldProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  label?: ReactNode;
  /** Testo d'aiuto sotto il controllo (`text-2xs`, muto). */
  hint?: ReactNode;
  /** Messaggio d'errore: se presente sostituisce il `hint` e marca il campo non valido. */
  error?: ReactNode;
  /** `id` del controllo, se non lo si vuole derivare dal figlio. */
  htmlFor?: string;
  children: ReactNode;
}

type ControlProps = {
  id?: string;
  'aria-describedby'?: string;
  'aria-invalid'?: boolean;
};

export function Field({
  label,
  hint,
  error,
  htmlFor,
  className,
  children,
  ...props
}: FieldProps) {
  const autoId = useId();
  const child =
    isValidElement<ControlProps>(children) && children.type !== Fragment
      ? (children as ReactElement<ControlProps>)
      : null;
  const controlId = htmlFor ?? child?.props.id ?? `${autoId}-control`;
  const messageId = `${autoId}-message`;
  const message = error ?? hint;

  const control = child
    ? cloneElement(child, {
        id: controlId,
        'aria-describedby': cn(child.props['aria-describedby'], message ? messageId : undefined) || undefined,
        ...(error ? { 'aria-invalid': true } : null),
      })
    : children;

  return (
    <div className={cn('flex flex-col gap-1.5', className)} {...props}>
      {label ? <Label htmlFor={controlId}>{label}</Label> : null}
      {control}
      {message ? (
        <p
          id={messageId}
          role={error ? 'alert' : undefined}
          className={cn('text-2xs', error ? 'text-error-foreground' : 'text-muted-foreground')}
        >
          {message}
        </p>
      ) : null}
    </div>
  );
}
