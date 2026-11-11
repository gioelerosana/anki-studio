/*
 * Mattoni delle impostazioni: un gruppo (titolo + card) e una riga etichetta / controllo.
 * Condivisi da SettingsScreen e dalla sezione Agenti.
 */
import type { ReactNode } from 'react';

export function Group({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="px-1 text-2xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h2>
        {action}
      </div>
      <div className="overflow-hidden rounded-lg border bg-card">{children}</div>
    </section>
  );
}

export function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b px-4 py-3 last:border-b-0 coarse:min-h-14">
      <div className="flex min-w-0 flex-col">
        <span className="text-sm">{label}</span>
        {hint ? <span className="text-2xs text-muted-foreground">{hint}</span> : null}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}
