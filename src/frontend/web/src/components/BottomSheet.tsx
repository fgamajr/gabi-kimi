import React, { useState, useCallback, useRef, useEffect } from 'react';

interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
}

export const BottomSheet: React.FC<BottomSheetProps> = ({ open, onClose, title, children }) => {
  const [closing, setClosing] = useState(false);
  const sheetRef = useRef<HTMLDivElement>(null);

  const handleClose = useCallback(() => {
    setClosing(true);
    setTimeout(onClose, 250);
  }, [onClose]);

  useEffect(() => {
    if (open) setClosing(false);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose();
    };
    document.addEventListener('keydown', handleEsc);
    return () => {
      document.body.style.overflow = originalOverflow;
      document.removeEventListener('keydown', handleEsc);
    };
  }, [open, handleClose]);

  if (!open && !closing) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <div
        className={`absolute inset-0 bg-background/60 backdrop-blur-sm ${closing ? 'overlay-exit' : 'overlay-enter'}`}
        onClick={handleClose}
      />
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`relative w-full max-w-xl max-h-[88vh] overflow-y-auto rounded-t-[28px] border-x border-t border-white/8 bg-[linear-gradient(180deg,rgba(16,18,30,0.98),rgba(10,12,22,0.99))] shadow-[var(--shadow-lg)]
          ${closing ? 'sheet-exit' : 'sheet-enter'}`}
      >
        <div className="sticky top-0 z-10 border-b border-white/6 bg-[rgba(14,16,26,0.92)] px-6 pb-3 pt-3 backdrop-blur-xl">
          <div className="mx-auto mb-3 h-1.5 w-12 rounded-full bg-white/12" />
          {title ? (
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-tertiary">Painel contextual</p>
                <h2 className="mt-1 font-editorial text-2xl leading-none text-foreground">{title}</h2>
              </div>
              <button
                onClick={handleClose}
                className="flex min-h-[40px] min-w-[40px] items-center justify-center rounded-full border border-white/8 bg-white/[0.03] text-text-secondary transition-colors hover:text-foreground focus-ring"
                aria-label="Fechar painel"
              >
                <span aria-hidden="true">×</span>
              </button>
            </div>
          ) : null}
        </div>
        <div className="px-6 pb-8 pt-2">
          {children}
        </div>
      </div>
    </div>
  );
};
