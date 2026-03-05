"use client";

import * as React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { 
  Check, 
  AlertCircle, 
  Info, 
  X,
  Star,
  Bell,
  PartyPopper
} from "lucide-react";

// =============================================================================
// NUBANK TOASTS — Microcopy que parece um amigo
// "Tudo certo por aqui 💜" em vez de "Operação concluída com sucesso"
// =============================================================================

export type ToastType = "success" | "error" | "info" | "favorite" | "alert" | "achievement";

export interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  duration?: number;
}

interface ToastItemProps {
  toast: Toast;
  onRemove: (id: string) => void;
}

const toastConfig: Record<ToastType, { 
  icon: React.ElementType; 
  bgClass: string; 
  borderClass: string;
  iconClass: string;
}> = {
  success: {
    icon: Check,
    bgClass: "bg-success/10",
    borderClass: "border-success/20",
    iconClass: "text-success",
  },
  error: {
    icon: AlertCircle,
    bgClass: "bg-error/10",
    borderClass: "border-error/20",
    iconClass: "text-error",
  },
  info: {
    icon: Info,
    bgClass: "bg-info/10",
    borderClass: "border-info/20",
    iconClass: "text-info",
  },
  favorite: {
    icon: Star,
    bgClass: "bg-warning/10",
    borderClass: "border-warning/20",
    iconClass: "text-warning",
  },
  alert: {
    icon: Bell,
    bgClass: "bg-brand/10",
    borderClass: "border-brand/20",
    iconClass: "text-brand",
  },
  achievement: {
    icon: PartyPopper,
    bgClass: "bg-brand/10",
    borderClass: "border-brand/20",
    iconClass: "text-brand",
  },
};

export function ToastItem({ toast, onRemove }: ToastItemProps) {
  const config = toastConfig[toast.type];
  const Icon = config.icon;

  React.useEffect(() => {
    if (toast.duration === 0) return;
    
    const timer = setTimeout(() => {
      onRemove(toast.id);
    }, toast.duration || 4000);

    return () => clearTimeout(timer);
  }, [toast.id, toast.duration, onRemove]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -20, scale: 0.9 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 100, scale: 0.9 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      className={cn(
        "w-full max-w-sm mx-auto p-4 rounded-2xl border shadow-lg",
        "backdrop-blur-lg",
        config.bgClass,
        config.borderClass,
        "bg-raised/95"
      )}
    >
      <div className="flex items-start gap-3">
        <div className={cn("p-2 rounded-xl", config.bgClass)}>
          <Icon className={cn("w-5 h-5", config.iconClass)} />
        </div>
        
        <div className="flex-1 min-w-0">
          <p className="font-display font-semibold text-primary text-sm">
            {toast.title}
          </p>
          {toast.message && (
            <p className="text-secondary text-sm mt-0.5">
              {toast.message}
            </p>
          )}
        </div>

        <button
          onClick={() => onRemove(toast.id)}
          className="p-1 rounded-lg text-muted hover:text-primary hover:bg-sunken transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </motion.div>
  );
}

// =============================================================================
// TOAST CONTAINER
// =============================================================================

interface ToastContainerProps {
  toasts: Toast[];
  onRemove: (id: string) => void;
}

export function ToastContainer({ toasts, onRemove }: ToastContainerProps) {
  return (
    <div className="fixed top-4 left-4 right-4 z-[200] space-y-2 pointer-events-none">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto">
            <ToastItem toast={toast} onRemove={onRemove} />
          </div>
        ))}
      </AnimatePresence>
    </div>
  );
}

// =============================================================================
// HOOK useNUBankToast — Microcopy pré-definido com personalidade
// =============================================================================

import { useCallback, useState } from "react";

let toastId = 0;

export function useNUBankToast() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const add = useCallback((toast: Omit<Toast, "id">) => {
    const id = `toast-${++toastId}`;
    setToasts((prev) => [...prev, { ...toast, id }]);
    return id;
  }, []);

  // Predefined toasts with Nubank personality
  const success = useCallback((title: string, message?: string) => {
    return add({ type: "success", title, message });
  }, [add]);

  const error = useCallback((title: string, message?: string) => {
    return add({ type: "error", title, message });
  }, [add]);

  const info = useCallback((title: string, message?: string) => {
    return add({ type: "info", title, message });
  }, [add]);

  const favorite = useCallback(() => {
    return add({
      type: "favorite",
      title: "Salvo! ⭐",
      message: "Você pode ver todos os seus favoritos no perfil.",
    });
  }, [add]);

  const unfavorite = useCallback(() => {
    return add({
      type: "info",
      title: "Removido",
      message: "Documento removido dos favoritos.",
    });
  }, [add]);

  const alertCreated = useCallback((orgName?: string) => {
    return add({
      type: "alert",
      title: "Alerta criado! 🔔",
      message: orgName 
        ? `Você vai saber quando ${orgName} publicar algo novo.`
        : "Você vai receber notificações sobre esse tema.",
    });
  }, [add]);

  const downloaded = useCallback((filename: string) => {
    return add({
      type: "success",
      title: "Download pronto! 📥",
      message: `${filename} foi baixado com sucesso.`,
    });
  }, [add]);

  const shared = useCallback(() => {
    return add({
      type: "success",
      title: "Link copiado! 👌",
      message: "Quem abrir vai ver exatamente o que você tá vendo.",
    });
  }, [add]);

  const welcome = useCallback(() => {
    return add({
      type: "achievement",
      title: "Bem-vindo ao DOU! ✨",
      message: "Agora ficou muito mais fácil acompanhar o Diário Oficial.",
    });
  }, [add]);

  const offline = useCallback(() => {
    return add({
      type: "info",
      title: "Você está offline 📡",
      message: "Mas não se preocupa — seus últimos documentos estão salvos.",
    });
  }, [add]);

  const firstFavorite = useCallback(() => {
    return add({
      type: "achievement",
      title: "Primeiro favorito! 🎉",
      message: "Você salvou seu primeiro documento. Tá começando a pegar o jeito!",
    });
  }, [add]);

  const streak = useCallback((days: number) => {
    return add({
      type: "achievement",
      title: `${days} dias seguidos! 🔥`,
      message: "Você tá de olho em tudo. Isso sim é dedicação!",
    });
  }, [add]);

  return {
    toasts,
    remove,
    add,
    success,
    error,
    info,
    favorite,
    unfavorite,
    alertCreated,
    downloaded,
    shared,
    welcome,
    offline,
    firstFavorite,
    streak,
  };
}
