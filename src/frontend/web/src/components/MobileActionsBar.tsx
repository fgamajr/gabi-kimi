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
    <div className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-border bg-background/95 backdrop-blur-xl px-3 pb-[calc(env(safe-area-inset-bottom)+0.5rem)] pt-2">
      <div className="grid grid-cols-4 gap-2">
        <ActionButton icon={<Icons.back className="w-4 h-4" />} label="Voltar" onClick={onBack} />
        <ActionButton icon={<Icons.share className="w-4 h-4" />} label="Compartilhar" onClick={onShare} />
        <ActionButton icon={<Icons.document className="w-4 h-4" />} label="PDF" onClick={onPdf} />
        <ActionButton
          icon={<Icons.book className="w-4 h-4" />}
          label="Índice"
          onClick={onIndex}
          disabled={!hasSections}
        />
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
    className="min-h-[52px] rounded-2xl border border-border bg-card text-foreground disabled:opacity-35 disabled:pointer-events-none press-effect focus-ring flex flex-col items-center justify-center gap-1"
  >
    {icon}
    <span className="text-[11px] font-medium">{label}</span>
  </button>
);
