/*
 * Barra superiore dell'app (barra del titolo disegnata dall'app nel desktop Electron,
 * normale nel browser e nella PWA).
 *
 * I gruppi di sinistra e destra non si restringono mai: il titolo sta nel
 * flusso, al centro, e si tronca. Così nessun pulsante si sovrappone a un
 * altro; se lo spazio non basta, chi usa la barra può leggere l'overflow con
 * `headerRef` (scrollWidth > clientWidth) e spostare azioni in un menu.
 * Le regioni trascinabili sono gestite da `.app-drag-region` (theme.css): i
 * gruppi interattivi sono `app-no-drag`, lo spazio vuoto in mezzo trascina.
 */
import type { ReactNode, Ref } from 'react';
import { cn } from './utils.js';
import { WindowControls, type WindowControlsProps } from './WindowControls.js';

export interface HeaderBarProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  leftContent?: ReactNode;
  centerContent?: ReactNode;
  rightContent?: ReactNode;
  showWindowControls?: boolean;
  windowControlProps?: WindowControlsProps;
  className?: string;
  headerRef?: Ref<HTMLElement>;
}

export function HeaderBar({
  title,
  subtitle,
  leftContent,
  centerContent,
  rightContent,
  showWindowControls = false,
  windowControlProps,
  className,
  headerRef,
}: HeaderBarProps) {
  return (
    <header
      ref={headerRef}
      className={cn(
        'app-drag-region app-header sticky top-0 z-40 flex h-[calc(var(--topbar-height)+env(safe-area-inset-top))] shrink-0 select-none items-center gap-2 overflow-x-clip border-b bg-background pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))] pt-[env(safe-area-inset-top)] text-foreground',
        className,
      )}
    >
      {/* Sinistra: identità file + azioni primarie */}
      <div className="app-no-drag flex shrink-0 items-center gap-1.5">{leftContent}</div>

      {/* Titolo nel flusso: occupa lo spazio libero e si tronca */}
      {/* Con un titolo la colonna ha una larghezza minima: se manca spazio l'header va in overflow e chi lo usa può decidere di toglierlo. */}
      <div className={cn('pointer-events-none flex flex-1 flex-col items-center px-2', title ? 'min-w-24' : 'min-w-0')}>
        {title ? <span className="max-w-full truncate text-sm font-medium">{title}</span> : null}
        {subtitle ? <span className="max-w-full truncate text-2xs text-muted-foreground">{subtitle}</span> : null}
      </div>

      {/* Destra: switcher, azioni secondarie, controlli finestra */}
      <div className="app-no-drag flex shrink-0 items-center gap-1.5">
        {centerContent}
        {rightContent}
        {showWindowControls && <WindowControls {...windowControlProps} />}
      </div>
    </header>
  );
}
