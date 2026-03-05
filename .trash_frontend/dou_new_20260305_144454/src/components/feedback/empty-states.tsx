"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Search,
  Bell,
  Star,
  Clock,
  FileText,
  WifiOff,
  Umbrella,
  Coffee,
  Compass,
  Sparkles
} from "lucide-react";

// =============================================================================
// EMPTY STATES — DNA Nubank
// "Zero resultados não é falha. É oportunidade de conversar com o usuário."
// =============================================================================

interface EmptyStateProps {
  className?: string;
  onAction?: () => void;
  onStart?: () => void;
  onRetry?: () => void;
}

// Busca sem resultados — Não achamos nada assim :(
export function EmptySearch({ className, onAction }: EmptyStateProps & { query?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("py-12 text-center px-6", className)}
    >
      <motion.div
        animate={{ 
          rotate: [0, -10, 10, -10, 10, 0],
          scale: [1, 1.1, 1]
        }}
        transition={{ duration: 0.5, delay: 0.2 }}
        className="w-20 h-20 mx-auto mb-6 rounded-full bg-sunken flex items-center justify-center"
      >
        <Search className="w-10 h-10 text-muted" />
      </motion.div>

      <h2 className="font-display font-bold text-xl text-primary mb-3">
        Não achamos nada assim
      </h2>

      <p className="text-secondary mb-2">
        A gente procurou em todo lugar (sério!)
      </p>

      <p className="text-muted text-sm mb-6 max-w-xs mx-auto">
        Que tal tentar termos mais amplos? Ou ajustar os filtros de data?
      </p>

      <div className="flex flex-wrap justify-center gap-2 mb-6">
        {["ministério da fazenda", "banco central", "aposentadoria INSS"].map((term) => (
          <button
            key={term}
            onClick={onAction}
            className="px-3 py-1.5 bg-raised border border-border rounded-lg text-sm text-secondary hover:text-primary hover:border-brand/50 transition-colors"
          >
            {term}
          </button>
        ))}
      </div>
    </motion.div>
  );
}

// Sem alertas configurados — Você ainda não tem alertas
export function EmptyAlerts({ className, onAction }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("py-12 text-center px-6", className)}
    >
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", delay: 0.1 }}
        className="w-20 h-20 mx-auto mb-6 rounded-full bg-brand/10 flex items-center justify-center"
      >
        <Bell className="w-10 h-10 text-brand" />
      </motion.div>

      <h2 className="font-display font-bold text-xl text-primary mb-3">
        Você não tem alertas ainda
      </h2>

      <p className="text-secondary mb-6 max-w-xs mx-auto">
        Quando sair algo no DOU sobre um tema seu,
        <span className="text-primary"> a gente avisa na hora.</span>
      </p>

      <Button variant="primary" onClick={onAction}>
        Criar meu primeiro alerta
      </Button>
    </motion.div>
  );
}

// Sem favoritos — Seus favoritos ficam aqui
export function EmptyFavorites({ className, onAction }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("py-12 text-center px-6", className)}
    >
      <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-sunken flex items-center justify-center">
        <Star className="w-10 h-10 text-muted" />
      </div>

      <h2 className="font-display font-bold text-xl text-primary mb-3">
        Seus favoritos ficam aqui
      </h2>

      <p className="text-secondary mb-6 max-w-xs mx-auto">
        Toque na <Star className="w-4 h-4 inline mx-1" /> em qualquer documento
        para salvar e ver depois.
      </p>

      <Button variant="secondary" onClick={onAction}>
        Explorar documentos
      </Button>
    </motion.div>
  );
}

// Sem histórico — Você não leu nada ainda
export function EmptyHistory({ className, onAction }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("py-12 text-center px-6", className)}
    >
      <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-sunken flex items-center justify-center">
        <Clock className="w-10 h-10 text-muted" />
      </div>

      <h2 className="font-display font-bold text-xl text-primary mb-3">
        Você não leu nada ainda
      </h2>

      <p className="text-secondary mb-6 max-w-xs mx-auto">
        Que tal começar por aqui? A gente guarda suas últimas leituras pra você voltar quando quiser.
      </p>

      <Button variant="secondary" onClick={onAction}>
        Ver o que saiu hoje
      </Button>
    </motion.div>
  );
}

// Offline — Você está offline
export function EmptyOffline({ className }: EmptyStateProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("py-12 text-center px-6", className)}
    >
      <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-warning/10 flex items-center justify-center">
        <WifiOff className="w-10 h-10 text-warning" />
      </div>

      <h2 className="font-display font-bold text-xl text-primary mb-3">
        Você está offline
      </h2>

      <p className="text-secondary mb-2 max-w-xs mx-auto">
        Mas não se preocupa!
      </p>

      <p className="text-muted text-sm mb-6 max-w-xs mx-auto">
        A gente guardou seus últimos documentos. Você pode continuar lendo.
      </p>

      <div className="flex flex-col gap-2">
        <Button variant="secondary">
          Ver documentos salvos
        </Button>
        <p className="text-xs text-muted">
          Atualizações disponíveis quando reconectar
        </p>
      </div>
    </motion.div>
  );
}

// Feriado — Hoje não tem edição
export function EmptyHoliday({ className, nextDate }: EmptyStateProps & { nextDate?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("py-12 text-center px-6", className)}
    >
      <motion.div
        animate={{ rotate: [0, -5, 5, -5, 5, 0] }}
        transition={{ duration: 2, repeat: Infinity, repeatDelay: 3 }}
        className="w-20 h-20 mx-auto mb-6 rounded-full bg-info/10 flex items-center justify-center"
      >
        <Umbrella className="w-10 h-10 text-info" />
      </motion.div>

      <h2 className="font-display font-bold text-xl text-primary mb-3">
        Hoje não tem edição
      </h2>

      <p className="text-secondary mb-2">
        Nem o governo trabalha nesse feriado 😎
      </p>

      {nextDate && (
        <p className="text-muted text-sm mb-6">
          A próxima edição sai em <span className="text-primary font-medium">{nextDate}</span>
        </p>
      )}

      <Button variant="secondary">
        Ver última edição
      </Button>
    </motion.div>
  );
}

// Fim de semana — DOU não é publicado nos fins de semana
export function EmptyWeekend({ className, nextDate }: EmptyStateProps & { nextDate?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("py-12 text-center px-6", className)}
    >
      <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-sunken flex items-center justify-center">
        <Coffee className="w-10 h-10 text-muted" />
      </div>

      <h2 className="font-display font-bold text-xl text-primary mb-3">
        Final de semana!
      </h2>

      <p className="text-secondary mb-6 max-w-xs mx-auto">
        O DOU descansa sábado e domingo.
        Aproveita pra ler o que você salvou essa semana?
      </p>

      {nextDate && (
        <p className="text-muted text-sm mb-6">
          Próxima edição: <span className="text-primary">{nextDate}</span>
        </p>
      )}
    </motion.div>
  );
}

// Erro genérico — Algo deu errado
export function EmptyError({ className, onRetry }: EmptyStateProps & { onRetry: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("py-12 text-center px-6", className)}
    >
      <motion.div
        animate={{ x: [0, -5, 5, -5, 5, 0] }}
        transition={{ duration: 0.4 }}
        className="w-20 h-20 mx-auto mb-6 rounded-full bg-error/10 flex items-center justify-center"
      >
        <Compass className="w-10 h-10 text-error" />
      </motion.div>

      <h2 className="font-display font-bold text-xl text-primary mb-3">
        Algo deu errado aqui
      </h2>

      <p className="text-secondary mb-2">
        Já estamos vendo o que aconteceu.
      </p>

      <p className="text-muted text-sm mb-6">
        Enquanto isso, que tal tentar de novo?
      </p>

      {onRetry && (
        <Button variant="primary" onClick={onRetry}>
          Tentar de novo
        </Button>
      )}
    </motion.div>
  );
}

// Primeira vez do usuário — Bem-vindo!
export function EmptyFirstTime({ className, onStart }: EmptyStateProps & { onStart: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className={cn("py-12 text-center px-6", className)}
    >
      <motion.div
        animate={{ rotate: 360 }}
        transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
        className="w-24 h-24 mx-auto mb-6 rounded-full bg-gradient-to-br from-brand/20 to-brand-dim/20 flex items-center justify-center"
      >
        <Sparkles className="w-12 h-12 text-brand" />
      </motion.div>

      <h2 className="font-display font-bold text-2xl text-primary mb-4">
        Pronto pra começar?
      </h2>

      <p className="text-secondary mb-8 max-w-sm mx-auto">
        O Diário Oficial pode ser complexo, mas a gente simplificou.
        Em 1 minuto você configura tudo.
      </p>

      <Button variant="primary" fullWidth onClick={onStart}>
        Fazer tour rápido
      </Button>

      <button 
        onClick={onStart}
        className="mt-4 text-sm text-muted hover:text-primary transition-colors"
      >
        Pular e começar a usar →
      </button>
    </motion.div>
  );
}

// Loading divertido
export function FunLoading({ message }: { message?: string }) {
  const messages = React.useMemo(() => [
    "Buscando no universo de documentos...",
    "Conversando com o servidor...",
    "Organizando as informações...",
    "Quase lá...",
  ], []);
  
  const [currentMessage, setCurrentMessage] = React.useState(message || messages[0]);
  
  React.useEffect(() => {
    if (message) return;
    
    let i = 0;
    const msgs = messages;
    const interval = setInterval(() => {
      i = (i + 1) % msgs.length;
      setCurrentMessage(msgs[i]);
    }, 2000);
    
    return () => clearInterval(interval);
  }, [message, messages]);

  return (
    <div className="py-12 text-center">
      <motion.div
        animate={{ 
          scale: [1, 1.2, 1],
          rotate: [0, 180, 360]
        }}
        transition={{ duration: 2, repeat: Infinity }}
        className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-brand/20 flex items-center justify-center"
      >
        <FileText className="w-8 h-8 text-brand" />
      </motion.div>
      
      <motion.p
        key={currentMessage}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        className="text-sm text-muted"
      >
        {currentMessage}
      </motion.p>
    </div>
  );
}
