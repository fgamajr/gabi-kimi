"use client";

import * as React from "react";
import { motion, AnimatePresence, Variants } from "framer-motion";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { 
  Sparkles, 
  Building2, 
  ChevronRight, 
  Check,
  Briefcase,
  Scale,
  Newspaper,
  Building,
  User
} from "lucide-react";

// =============================================================================
// ONBOARDING — DNA Nubank v4.0
// "Bem-vindo! Aqui a gente faz o DOU parecer coisa de gente, não de máquina"
// =============================================================================

interface OnboardingFlowProps {
  isOpen: boolean;
  onComplete: (preferences: UserPreferences) => void;
  onSkip: () => void;
}

export interface UserPreferences {
  profession: string;
  organs: string[];
  enableNotifications: boolean;
}

const professions = [
  { id: "advogado", label: "Advogado", icon: Scale },
  { id: "servidor", label: "Servidor Público", icon: Building2 },
  { id: "jornalista", label: "Jornalista", icon: Newspaper },
  { id: "empresario", label: "Empresário", icon: Briefcase },
  { id: "outro", label: "Outra área", icon: User },
];

const popularOrgans = [
  { id: "fazenda", name: "Ministério da Fazenda", short: "Fazenda" },
  { id: "bc", name: "Banco Central", short: "BC" },
  { id: "inss", name: "INSS", short: "INSS" },
  { id: "saude", name: "Ministério da Saúde", short: "Saúde" },
  { id: "tcu", name: "TCU", short: "TCU" },
  { id: "stf", name: "STF", short: "STF" },
];

export function OnboardingFlow({ isOpen, onComplete, onSkip }: OnboardingFlowProps) {
  const [step, setStep] = React.useState(0);
  const [profession, setProfession] = React.useState<string>("");
  const [selectedOrgans, setSelectedOrgans] = React.useState<string[]>([]);
  const [enableNotifications, setEnableNotifications] = React.useState(true);
  const [direction, setDirection] = React.useState(1);

  const totalSteps = 3;

  const handleNext = () => {
    if (step < totalSteps - 1) {
      setDirection(1);
      setStep(step + 1);
    } else {
      onComplete({
        profession,
        organs: selectedOrgans,
        enableNotifications,
      });
    }
  };

  const handleBack = () => {
    if (step > 0) {
      setDirection(-1);
      setStep(step - 1);
    }
  };

  const toggleOrgan = (organId: string) => {
    setSelectedOrgans(prev => 
      prev.includes(organId)
        ? prev.filter(id => id !== organId)
        : [...prev, organId]
    );
  };

  const slideVariants = {
    enter: (direction: number) => ({
      x: direction > 0 ? 300 : -300,
      opacity: 0,
    }),
    center: {
      x: 0,
      opacity: 1,
    },
    exit: (direction: number) => ({
      x: direction < 0 ? 300 : -300,
      opacity: 0,
    }),
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] bg-canvas">
      {/* Progress bar */}
      <div className="absolute top-0 left-0 right-0 h-1 bg-sunken">
        <motion.div
          className="h-full bg-brand"
          initial={{ width: 0 }}
          animate={{ width: `${((step + 1) / totalSteps) * 100}%` }}
          transition={{ duration: 0.3 }}
        />
      </div>

      {/* Skip button */}
      <button
        onClick={onSkip}
        className="absolute top-4 right-4 text-sm text-muted hover:text-primary transition-colors z-10"
      >
        Pular
      </button>

      {/* Content */}
      <div className="h-full flex flex-col items-center justify-center px-6 max-w-md mx-auto">
        <AnimatePresence mode="wait" custom={direction}>
          {step === 0 && (
            <StepWelcome
              key="welcome"
              variants={slideVariants}
              custom={direction}
              onNext={handleNext}
            />
          )}
          
          {step === 1 && (
            <StepProfession
              key="profession"
              variants={slideVariants}
              custom={direction}
              selected={profession}
              onSelect={setProfession}
              onNext={handleNext}
              onBack={handleBack}
            />
          )}
          
          {step === 2 && (
            <StepOrgans
              key="organs"
              variants={slideVariants}
              custom={direction}
              selected={selectedOrgans}
              onToggle={toggleOrgan}
              enableNotifications={enableNotifications}
              onToggleNotifications={setEnableNotifications}
              onComplete={handleNext}
              onBack={handleBack}
            />
          )}
        </AnimatePresence>

        {/* Step indicators */}
        <div className="absolute bottom-8 left-0 right-0 flex justify-center gap-2">
          {Array.from({ length: totalSteps }).map((_, i) => (
            <div
              key={i}
              className={cn(
                "w-2 h-2 rounded-full transition-all duration-300",
                i === step 
                  ? "w-6 bg-brand" 
                  : i < step 
                    ? "bg-brand/50" 
                    : "bg-sunken"
              )}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// STEP 1: Bem-vindo — Estamos felizes que você chegou!
// =============================================================================

function StepWelcome({ variants, custom, onNext }: { variants: Variants; custom: number; onNext: () => void }) {
  return (
    <motion.div
      variants={variants}
      initial="enter"
      animate="center"
      exit="exit"
      custom={custom}
      transition={{ type: "spring", damping: 25, stiffness: 200 }}
      className="w-full text-center"
    >
      {/* Animated logo */}
      <motion.div
        initial={{ scale: 0.5, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.2, type: "spring" }}
        className="w-24 h-24 mx-auto mb-8 rounded-3xl bg-gradient-to-br from-brand to-brand-dim flex items-center justify-center shadow-brand"
      >
        <Sparkles className="w-12 h-12 text-canvas" />
      </motion.div>

      <motion.h1
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.3 }}
        className="font-display font-bold text-3xl text-primary mb-4"
      >
        Bem-vindo ao DOU
      </motion.h1>

      <motion.p
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.4 }}
        className="text-secondary text-lg mb-4 leading-relaxed"
      >
        Aqui sai tudo que é oficial no Brasil.
        <br />
        <span className="text-primary font-medium">Toda lei, portaria e nomeação</span>
        <br />
        numa experiência que não dá sono.
      </motion.p>

      <motion.p
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.5 }}
        className="text-muted text-sm mb-8"
      >
        Em 1 minuto a gente configura tudo pra você.
      </motion.p>

      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ delay: 0.6 }}
      >
        <Button 
          variant="primary" 
          fullWidth 
          onClick={onNext}
          rightIcon={<ChevronRight className="w-5 h-5" />}
        >
          Vamos começar
        </Button>
      </motion.div>
    </motion.div>
  );
}

// =============================================================================
// STEP 2: O que você faz? — Pra gente te conhecer melhor
// =============================================================================

function StepProfession({ variants, custom, selected, onSelect, onNext, onBack }: { variants: Variants; custom: number; selected: string; onSelect: (id: string) => void; onNext: () => void; onBack: () => void }) {
  return (
    <motion.div
      variants={variants}
      initial="enter"
      animate="center"
      exit="exit"
      custom={custom}
      transition={{ type: "spring", damping: 25, stiffness: 200 }}
      className="w-full"
    >
      <h2 className="font-display font-bold text-2xl text-primary mb-2">
        O que você faz?
      </h2>
      <p className="text-secondary mb-8">
        Isso ajuda a gente a personalizar sua experiência.
      </p>

      <div className="space-y-3 mb-8">
        {professions.map((prof, i) => {
          const Icon = prof.icon;
          const isSelected = selected === prof.id;
          
          return (
            <motion.button
              key={prof.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.1 }}
              onClick={() => onSelect(prof.id)}
              className={cn(
                "w-full p-4 rounded-2xl border-2 transition-all duration-200 flex items-center gap-4",
                isSelected
                  ? "border-brand bg-brand/5"
                  : "border-border bg-raised hover:border-border-strong"
              )}
            >
              <div className={cn(
                "w-12 h-12 rounded-xl flex items-center justify-center transition-colors",
                isSelected ? "bg-brand text-canvas" : "bg-sunken text-secondary"
              )}>
                <Icon className="w-6 h-6" />
              </div>
              <span className={cn(
                "font-display font-medium flex-1 text-left",
                isSelected ? "text-primary" : "text-secondary"
              )}>
                {prof.label}
              </span>
              {isSelected && (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  className="w-6 h-6 rounded-full bg-brand flex items-center justify-center"
                >
                  <Check className="w-4 h-4 text-canvas" />
                </motion.div>
              )}
            </motion.button>
          );
        })}
      </div>

      <div className="flex gap-3">
        <Button variant="secondary" onClick={onBack} className="flex-1">
          Voltar
        </Button>
        <Button 
          variant="primary" 
          onClick={onNext} 
          disabled={!selected}
          className="flex-[2]"
        >
          Continuar
        </Button>
      </div>
    </motion.div>
  );
}

// =============================================================================
// STEP 3: Quais órgãos você acompanha? — A gente avisa quando sair algo
// =============================================================================

function StepOrgans({ 
  variants, 
  custom, 
  selected, 
  onToggle, 
  enableNotifications,
  onToggleNotifications,
  onComplete, 
  onBack 
}: { 
  variants: Variants; 
  custom: number; 
  selected: string[]; 
  onToggle: (id: string) => void; 
  enableNotifications: boolean;
  onToggleNotifications: (v: boolean) => void;
  onComplete: () => void; 
  onBack: () => void;
}) {
  const canComplete = selected.length > 0;

  return (
    <motion.div
      variants={variants}
      initial="enter"
      animate="center"
      exit="exit"
      custom={custom}
      transition={{ type: "spring", damping: 25, stiffness: 200 }}
      className="w-full"
    >
      <h2 className="font-display font-bold text-2xl text-primary mb-2">
        Quais órgãos você acompanha?
      </h2>
      <p className="text-secondary mb-6">
        A gente te avisa quando publicarem algo novo.
      </p>

      {/* Organs grid */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        {popularOrgans.map((organ, i) => {
          const isSelected = selected.includes(organ.id);
          
          return (
            <motion.button
              key={organ.id}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.05 }}
              onClick={() => onToggle(organ.id)}
              className={cn(
                "p-4 rounded-xl border-2 transition-all duration-200 relative overflow-hidden",
                isSelected
                  ? "border-brand bg-brand/5"
                  : "border-border bg-raised hover:border-border-strong"
              )}
            >
              <div className="flex flex-col items-center text-center">
                <Building className={cn(
                  "w-8 h-8 mb-2",
                  isSelected ? "text-brand" : "text-muted"
                )} />
                <span className={cn(
                  "font-display font-medium text-sm",
                  isSelected ? "text-primary" : "text-secondary"
                )}>
                  {organ.short}
                </span>
              </div>
              
              {isSelected && (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  className="absolute top-2 right-2 w-5 h-5 rounded-full bg-brand flex items-center justify-center"
                >
                  <Check className="w-3 h-3 text-canvas" />
                </motion.div>
              )}
            </motion.button>
          );
        })}
      </div>

      {/* Notifications toggle */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className={cn(
          "p-4 rounded-xl border-2 mb-6 transition-all",
          enableNotifications 
            ? "border-brand/30 bg-brand/5" 
            : "border-border bg-raised"
        )}
      >
        <label className="flex items-center gap-3 cursor-pointer">
          <div className={cn(
            "w-12 h-7 rounded-full p-1 transition-colors",
            enableNotifications ? "bg-brand" : "bg-sunken"
          )}>
            <motion.div
              animate={{ x: enableNotifications ? 20 : 0 }}
              transition={{ type: "spring", stiffness: 500, damping: 30 }}
              className="w-5 h-5 rounded-full bg-canvas shadow-sm"
            />
          </div>
          <div className="flex-1">
            <p className="font-display font-medium text-primary">
              Ativar notificações
            </p>
            <p className="text-xs text-muted">
              Recomendado — você não perde nada
            </p>
          </div>
          <input
            type="checkbox"
            checked={enableNotifications}
            onChange={(e) => onToggleNotifications(e.target.checked)}
            className="sr-only"
          />
        </label>
      </motion.div>

      {/* Completion message */}
      <AnimatePresence>
        {canComplete && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-4 p-4 bg-success/10 border border-success/20 rounded-xl"
          >
            <p className="text-sm text-success font-medium text-center">
              ✨ Pronto! Criamos {selected.length} alerta{selected.length > 1 ? "s" : ""} pra você
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex gap-3">
        <Button variant="secondary" onClick={onBack} className="flex-1">
          Voltar
        </Button>
        <Button 
          variant="primary" 
          onClick={onComplete}
          disabled={!canComplete}
          className="flex-[2]"
        >
          {canComplete ? "Começar a usar" : "Selecione pelo menos um"}
        </Button>
      </div>
    </motion.div>
  );
}
