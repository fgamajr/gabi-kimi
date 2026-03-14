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
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose();
    };
    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
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
        className={`relative w-full max-w-lg max-h-[85vh] bg-card rounded-t-2xl border-t border-x border-border shadow-[var(--shadow-lg)] overflow-y-auto
          ${closing ? 'sheet-exit' : 'sheet-enter'}`}
      >
        {/* Handle */}
        <div className="sticky top-0 bg-card pt-3 pb-2 px-6 z-10">
          <div className="w-10 h-1 rounded-full bg-border mx-auto mb-3" />
          {title && <h2 className="text-lg font-semibold text-foreground">{title}</h2>}
        </div>
        <div className="px-6 pb-8">
          {children}
        </div>
      </div>
    </div>
  );
};
