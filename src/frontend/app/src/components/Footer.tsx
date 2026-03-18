import React from 'react';

export const Footer: React.FC = () => {
  return (
    <footer className="mt-12 border-t border-border">
      <div className="max-w-6xl mx-auto px-4 py-8 flex flex-col sm:flex-row items-center justify-between gap-2 text-sm text-text-secondary">
        <span className="font-semibold text-foreground">GABI DOU</span>
        <span>Dados do Diario Oficial da Uniao</span>
      </div>
    </footer>
  );
};
