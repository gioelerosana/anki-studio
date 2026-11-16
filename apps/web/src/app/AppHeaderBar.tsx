/*
 * HeaderBar delle schermate. Nell'app desktop la finestra non ha la cornice di sistema
 * (su GNOME sarebbe in stile GTK3, fuori posto): la barra del titolo è questa, con
 * riduci / massimizza / chiudi a destra come in XMap Studio, e lo spazio vuoto trascina
 * la finestra. Nel browser e nella PWA su iPad è la HeaderBar di sempre.
 */
import { useEffect, useState, type ComponentProps } from 'react';
import { HeaderBar } from '@anki-studio/ui-kit';
import { desktop } from './desktop';

type Props = Omit<ComponentProps<typeof HeaderBar>, 'showWindowControls' | 'windowControlProps'>;

export function AppHeaderBar(props: Props) {
  const maximized = useWindowMaximized();
  if (!desktop) return <HeaderBar {...props} />;
  const win = desktop;
  return (
    <HeaderBar
      {...props}
      showWindowControls
      windowControlProps={{
        onMinimize: win.minimize,
        onMaximize: win.maximize,
        onClose: win.close,
        isMaximized: maximized,
      }}
    />
  );
}

function useWindowMaximized(): boolean {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!desktop) return;
    let alive = true;
    void desktop.isMaximized().then((value) => {
      if (alive) setMaximized(value);
    });
    const stop = desktop.onMaximizedChange(setMaximized);
    return () => {
      alive = false;
      stop();
    };
  }, []);
  return maximized;
}
