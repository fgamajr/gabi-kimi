import type { DocumentDetail, NormativeReference } from "@/lib/api";

export type LegalStatusCode =
  | "unknown"
  | "linked"
  | "procedure-linked"
  | "amended"
  | "revoked";

export interface LegalStatusEvidence {
  kind: "revocation" | "amendment" | "procedure" | "reference";
  label: string;
  detail?: string;
}

export interface LegalStatusAssessment {
  code: LegalStatusCode;
  tone: "ok" | "warn" | "info";
  label: string;
  summary: string;
  confidence: "low" | "medium";
  evidence: LegalStatusEvidence[];
}

export interface LegalTimelineItem {
  date?: string;
  timestamp: number;
  dateLabel: string;
  label: string;
  detail?: string;
}

export function assessLegalStatus(doc: DocumentDetail | null): LegalStatusAssessment {
  if (!doc) {
    return {
      code: "unknown",
      tone: "info",
      label: "Sem dados normativos",
      summary: "O documento ainda não carregou referências suficientes para análise.",
      confidence: "low",
      evidence: [],
    };
  }

  const references = doc.normative_refs || [];
  const procedures = doc.procedure_refs || [];
  const evidence: LegalStatusEvidence[] = [];

  for (const ref of references) {
    const corpus = [ref.reference_type, ref.reference_text, ref.reference_number].filter(Boolean).join(" ").toLowerCase();
    if (/\brevog/i.test(corpus)) {
      evidence.push({
        kind: "revocation",
        label: [ref.reference_type, ref.reference_number].filter(Boolean).join(" ").trim() || "Sinal de revogação",
        detail: ref.reference_text || undefined,
      });
    } else if (/\balter|\bretific|\bprorrog|\bcomplement/i.test(corpus)) {
      evidence.push({
        kind: "amendment",
        label: [ref.reference_type, ref.reference_number].filter(Boolean).join(" ").trim() || "Sinal de alteração",
        detail: ref.reference_text || undefined,
      });
    } else {
      evidence.push({
        kind: "reference",
        label: [ref.reference_type, ref.reference_number].filter(Boolean).join(" ").trim() || "Referência normativa",
        detail: ref.reference_text || undefined,
      });
    }
  }

  for (const procedure of procedures) {
    evidence.push({
      kind: "procedure",
      label: [procedure.procedure_type, procedure.procedure_identifier].filter(Boolean).join(" · ") || "Procedimento relacionado",
    });
  }

  if (evidence.some((item) => item.kind === "revocation")) {
    return {
      code: "revoked",
      tone: "warn",
      label: "Sinal de revogação ou substituição",
      summary:
        "A base detectou linguagem de revogação ligada a este ato. Confirme a vigência em consolidação oficial ou no ato posterior correspondente.",
      confidence: "medium",
      evidence: evidence.slice(0, 4),
    };
  }

  if (evidence.some((item) => item.kind === "amendment")) {
    return {
      code: "amended",
      tone: "warn",
      label: "Ato com alterações ou complementações detectadas",
      summary:
        "Há sinais de versão normativa posterior relacionada a este documento. Use a linha detectada e a rede de referências para continuar a análise.",
      confidence: "medium",
      evidence: evidence.slice(0, 4),
    };
  }

  if (evidence.some((item) => item.kind === "procedure")) {
    return {
      code: "procedure-linked",
      tone: "ok",
      label: "Ato conectado a procedimentos do corpus",
      summary:
        "Foram encontrados procedimentos vinculados a este documento, úteis para contextualização administrativa e auditoria.",
      confidence: "medium",
      evidence: evidence.slice(0, 4),
    };
  }

  if (evidence.length > 0) {
    return {
      code: "linked",
      tone: "ok",
      label: "Ato conectado a outras referências normativas",
      summary:
        "O documento possui referências normativas estruturadas no corpus. Isso ajuda a reconstruir contexto, mas não substitui consolidação oficial.",
      confidence: "medium",
      evidence: evidence.slice(0, 4),
    };
  }

  return {
    code: "unknown",
    tone: "info",
    label: "Sem alterações detectadas no corpus",
    summary:
      "Nenhuma referência estruturada de alteração, revogação ou procedimento foi detectada para este documento na base atual.",
    confidence: "low",
    evidence: [],
  };
}

export function buildNormativeTimeline(refs: NormativeReference[] | undefined): LegalTimelineItem[] {
  return (refs || [])
    .map((ref) => {
      const date = ref.reference_date ? new Date(ref.reference_date) : null;
      const isValidDate = Boolean(date && !Number.isNaN(date.getTime()));
      return {
        date: isValidDate ? date!.toISOString() : undefined,
        timestamp: isValidDate ? date!.getTime() : Number.MAX_SAFE_INTEGER,
        dateLabel: isValidDate
          ? date!.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" })
          : "Sem data",
        label: [ref.reference_type, ref.reference_number].filter(Boolean).join(" ").trim() || "Referência normativa",
        detail: ref.reference_text || "",
      };
    })
    .sort((left, right) => left.timestamp - right.timestamp)
    .slice(0, 6);
}
