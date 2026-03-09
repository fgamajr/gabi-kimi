import React from "react";
import { Icons } from "@/components/Icons";

interface MobileActionsBarProps {
  onBack: () => void;
  onShare: () => void;
  onPdf: () => void;
  onIndex: () => void;
  hasSections: boolean;
}

export const MobileActionsBar: React.FC<MobileActionsBarProps> = ({
  onBack,
  onShare,
  onPdf,
  onIndex,
  hasSections,
}) => {
  return (
    <div className="document-mobile-actions fixed inset-x-0 bottom-0 z-40 px-3 pb-[calc(env(safe-area-inset-bottom)+0.5rem)] pt-2 md:hidden">
      <div className="reader-surface rounded-[28px] px-2 py-2 backdrop-blur-xl">
        <div className="grid grid-cols-4 gap-2">
          <ActionButton icon={<Icons.back className="w-4 h-4" />} label="Voltar" onClick={onBack} />
          <ActionButton icon={<Icons.copy className="w-4 h-4" />} label="Link" onClick={onShare} />
          <ActionButton icon={<Icons.document className="w-4 h-4" />} label="PDF" onClick={onPdf} />
          <ActionButton
            icon={<Icons.book className="w-4 h-4" />}
            label="Índice"
            onClick={onIndex}
            disabled={!hasSections}
          />
        </div>
      </div>
    </div>
  );
};

const ActionButton: React.FC<{
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}> = ({ icon, label, onClick, disabled = false }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    className="flex min-h-[56px] flex-col items-center justify-center gap-1 rounded-[20px] border border-white/8 bg-white/[0.03] text-foreground disabled:pointer-events-none disabled:opacity-35 press-effect focus-ring"
  >
    {icon}
    <span className="text-[11px] font-semibold uppercase tracking-[0.08em]">{label}</span>
  </button>
);
