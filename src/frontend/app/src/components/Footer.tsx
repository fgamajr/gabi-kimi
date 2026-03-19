import React from 'react';

export const Footer: React.FC = () => {
  return (
    <footer className="mt-12 border-t border-border bg-surface-sunken">
      <div className="max-w-6xl mx-auto px-4 py-8 flex flex-col sm:flex-row items-center justify-between gap-2 text-sm text-muted-foreground">
        <span className="font-black text-foreground">Arquivo da República</span>
        <span className="text-xs font-mono uppercase tracking-widest">DOU + TCU · Dados abertos do governo federal</span>
      </div>
    </footer>
  );
};
