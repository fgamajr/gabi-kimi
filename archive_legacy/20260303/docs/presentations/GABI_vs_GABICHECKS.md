# CLARIFICATION DOCUMENT: GABI vs. GABICHECKS

## Purpose
This document clarifies the distinction between **GABI** and **GABICHECKS** for the TCU presentation team presenting to the French Court of Auditors (Cour des Comptes).

---

## The Core Distinction

| Aspect | **GABI** | **GABICHECKS** |
|--------|----------|----------------|
| **Nature** | Integrated AI agent within ChatTCU | Standalone document verification tool |
| **Purpose** | Meeting assistance and documentation | PDF compliance verification |
| **Input** | Audio, video, YouTube links | PDF documents + JSON checklists |
| **Output** | Meeting minutes, summaries, work papers | Compliance reports with evidence |
| **Publication** | PursuIT 10th Edition 2025 (India) | Acórdão 1372/2025, Apêndice I |
| **Phase** | Phase 2 (Integrated Agents) | Separate/Complementary tool |

---

## Output Format Comparison

> **Important Clarification:** Neither GABI nor GabiChecks produce LaTeX output. Programmatic LaTeX generation is introduced only in Phase 3 "Audit as Code".

| Tool | Output Format | Description |
|------|---------------|-------------|
| **GABI** | Meeting minutes (text/documents) | Editable meeting documents, structured work papers, summaries |
| **GabiChecks** | Compliance reports (JSON/CSV/Markdown) | Structured compliance reports with evidence citations and justifications |
| **Audit as Code** | LaTeX (.tex) → PDF | Programmatic generation of publication-ready audit reports |

This distinction illustrates the **maturity progression**:
- **Phase 2 (GABI):** Basic document/text output
- **GabiChecks:** Structured data reports (JSON/CSV)
- **Phase 3 (Audit as Code):** Professional publication formats (LaTeX → PDF)

---

## GABI (Gabinete Automatizado de Boas Ideias)

### Full Name
**Gabinete Automatizado de Boas Ideias**  
*(Automated Office of Good Ideas)*

### What It Is
An **integrated AI agent/app** embedded directly within the ChatTCU platform.

### Function
Transforms meeting recordings into structured, actionable documentation:
- **Transcription** of audio/video content
- **Summarization** of key discussion points
- **Drafting** of formal meeting minutes

### Input Types
- Audio recordings
- Video files
- YouTube links

### Output
- Editable meeting documents
- Structured work papers
- Summarized action items

### Publication Details
- **Venue:** PursuIT 10th Edition 2025
- **Location:** India
- **Authors:** 
  - Pedro C. Filho
  - Fernando Gama Jr
  - Klauss Nogueira

### Presentation Placement
**Phase 2: Integrated Agents** (Slides 7-9)

---

## GABICHECKS

### What It Is
A **separate document verification tool** — not an integrated agent but a specialized utility.

### Function
Automates tedious verification tasks using LLMs to check PDF documents for compliance:
- Extracts text from PDF documents
- AI analyzes content against predefined checklists
- Generates structured compliance reports

### Input Types
- PDF documents
- JSON checklist parameters (rules/validation criteria)

### Process
1. PDF text extraction
2. AI analysis against checklist criteria
3. Report generation with evidence and justifications

### Output
- Compliance reports
- Evidence citations
- Detailed justifications for findings

### Source
- **Reference:** Acórdão 1372/2025, Apêndice I
- **Context:** Automates tedious verification tasks using Large Language Models (LLMs)

### Presentation Placement
**After Phase 3** (Slides 13-14) — positioned as a complementary tool, not part of the 3-phase arc

---

## Why the Confusion Occurs

### 1. Similar Names
Both names start with "Gabi" — GABI vs. GABICHECKS — suggesting a familial relationship that doesn't exist.

### 2. Both Use AI
Both tools leverage artificial intelligence and Large Language Models (LLMs) as their core technology.

### 3. Same Audience
Both are designed for TCU auditors and inspection workflows.

### 4. Same Origin
Both emerge from TCU's innovation ecosystem.

---

## Key Difference to Emphasize

> **GABI** = Meeting documentation assistant  
> **GABICHECKS** = Document compliance verifier

| Use Case | Tool |
|----------|------|
| "I need minutes from this meeting" | **GABI** |
| "Does this document comply with regulations?" | **GABICHECKS** |

---

## Talking Points for French Audience

### How to Explain the Distinction Clearly

#### The "Meeting vs. Document" Frame
> "Think of **GABI** as your meeting assistant — it listens, transcribes, and documents. **GABICHECKS** is your document inspector — it reads, verifies, and validates compliance."

#### The "Workflow Position" Frame
> "**GABI** is embedded in our conversational AI platform (Phase 2), helping auditors during and after meetings. **GABICHECKS** operates independently, checking the documents you already have."

#### The "Input/Output" Frame
> "**GABI** takes *audio/video* and produces *meeting minutes*. **GABICHECKS** takes *PDFs and checklists* and produces *compliance reports*."

### Key Phrases to Use

| Instead of... | Say... |
|---------------|--------|
| "Both are AI tools" | "Both use AI, but for completely different audit tasks" |
| "They're related" | "They share a naming convention but serve different purposes" |
| "GABI and GABICHECKS" | "GABI, the meeting assistant, and GABICHECKS, the compliance verifier" |

### French Translation References (if needed)

| English | French |
|---------|--------|
| Meeting transcription | Transcription de réunion |
| Compliance checking | Vérification de conformité |
| Meeting minutes | Compte-rendu de réunion |
| Document verification | Vérification documentaire |
| AI agent | Agent IA |
| Standalone tool | Outil autonome |

---

## Presentation Slide Guide

| Slide Range | Content | Tool Mentioned |
|-------------|---------|----------------|
| 7-9 | Phase 2: Integrated Agents | **GABI** only |
| 10-12 | Phase 3 | (no GABI/GABICHECKS) |
| 13-14 | Complementary Tools | **GABICHECKS** only |

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────┐
│  QUESTION: "Which tool should I mention?"                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Is the topic about MEETINGS?                                   │
│  → Use GABI                                                     │
│                                                                 │
│  Is the topic about DOCUMENT COMPLIANCE/VERIFICATION?           │
│  → Use GABICHECKS                                               │
│                                                                 │
│  Is the audience confused about the names?                      │
│  → Explain: "GABI helps with meetings, GABICHECKS checks docs"  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Summary for Presenters

**GABI and GABICHECKS are completely separate tools that happen to share similar names.**

- **GABI** = Meeting documentation (Phase 2, integrated in ChatTCU)
- **GABICHECKS** = PDF compliance checking (separate tool, post-Phase 3)

**Bottom line for the French audience:**  
*"One helps you document what was said in meetings. The other helps you verify if documents comply with rules."*

---

*Document prepared for TCU presentation team*  
*Presentation to Cour des Comptes (French Court of Auditors)*
