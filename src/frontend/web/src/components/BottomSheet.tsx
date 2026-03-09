import React, { useId } from "react";
import * as Dialog from "@radix-ui/react-dialog";

interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  contentId?: string;
  children: React.ReactNode;
}

export const BottomSheet: React.FC<BottomSheetProps> = ({ open, onClose, title, contentId, children }) => {
  const titleId = useId();

  return (
    <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-background/60 backdrop-blur-sm data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          id={contentId}
          aria-labelledby={title ? titleId : undefined}
          className="fixed inset-x-0 bottom-0 z-50 mx-auto flex max-h-[88vh] w-full max-w-xl flex-col overflow-y-auto rounded-t-[28px] border-x border-t border-white/8 bg-[linear-gradient(180deg,rgba(16,18,30,0.98),rgba(10,12,22,0.99))] shadow-[var(--shadow-lg)] outline-none data-[state=closed]:animate-out data-[state=closed]:slide-out-to-bottom data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom"
        >
          <div className="sticky top-0 z-10 border-b border-white/6 bg-[rgba(14,16,26,0.92)] px-6 pb-3 pt-3 backdrop-blur-xl">
            <div className="mx-auto mb-3 h-1.5 w-12 rounded-full bg-white/12" />
            {title ? (
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-text-tertiary">Painel contextual</p>
                  <Dialog.Title id={titleId} className="mt-1 font-editorial text-2xl leading-none text-foreground">
                    {title}
                  </Dialog.Title>
                </div>
                <Dialog.Close asChild>
                  <button
                    type="button"
                    className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-full border border-white/8 bg-white/[0.03] text-text-secondary transition-colors hover:text-foreground focus-ring"
                    aria-label="Fechar painel"
                  >
                    <span aria-hidden="true">×</span>
                  </button>
                </Dialog.Close>
              </div>
            ) : null}
          </div>
          <div className="px-6 pb-8 pt-2">
            {children}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
