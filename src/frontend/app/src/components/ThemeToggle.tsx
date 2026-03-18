import { useTheme } from 'next-themes';
import { Icons } from './Icons';

export const ThemeToggle: React.FC = () => {
  const { theme, setTheme } = useTheme();
  return (
    <button
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      className="p-2 rounded-lg hover:bg-muted transition-colors focus-ring min-w-[44px] min-h-[44px] flex items-center justify-center"
      aria-label={theme === 'dark' ? 'Modo claro' : 'Modo escuro'}
    >
      {theme === 'dark' ? <Icons.sun className="w-5 h-5" /> : <Icons.moon className="w-5 h-5" />}
    </button>
  );
};
