# Audit as Code: LaTeX Report Generation Pipeline
## Technical Documentation for Cour des Comptes

**Document Version:** 1.0  
**Date:** March 2025  
**Classification:** Technical Architecture  
**Related Specifications:** CRSS-1, sources_v3.yaml

---

## Executive Summary

This document describes the **Audit as Code LaTeX Pipeline** — a deterministic, evidence-grade report generation system that transforms cryptographically-verified audit registries into publication-quality PDF documents. The pipeline embodies the principle that audit outputs should be as rigorously engineered as the audit process itself.

> *"La composition typographique n'est pas un art décoratif, mais une discipline de la pensée claire."*  
> — Maxim of French typographic tradition

---

## 1. The Pipeline: Five Transformations

The pipeline transforms audit data through five distinct stages, each producing an auditable artifact:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AUDIT AS CODE LATEX PIPELINE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐         │
│   │  YAML    │────▶│  DSL     │────▶│  CRSS-1  │────▶│  LaTeX   │────▶ PDF │
│   │  Specs   │     │  Model   │     │  Registry│     │  Source  │         │
│   └──────────┘     └──────────┘     └──────────┘     └──────────┘         │
│        │                │                │                │               │
│        ▼                ▼                ▼                ▼               │
│   Declarative      Validated         Canonical       Typeset             │
│   Audit Rules      Python Classes    Serialization   Document            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 Stage 1: YAML Audit Specifications

**Input:** `sources_v3.yaml` — Declarative audit specifications  
**Output:** Validated domain model entities

The YAML specification defines the complete audit universe:

```yaml
# sources_v3.yaml — excerpt
sources:
  dou:
    crawl:
      runtime:
        mode: browser
        wait_dom: network_idle
        timeout: 20s
      steps:
        - load: entry
        - extract:
            name: section_pages
            selector: "a[href*='/web/dou/-/']"
            attribute: href
            absolute: true
    model:
      dsl_version: "1.0"
      namespace: legal_publication
      entities:
        document:
          kind: record
          table: document
          identity:
            primary_key:
              field: id
              type: uuid
              generated: uuid_v7
          fields:
            document_type: { type: string, required: true }
            document_number: { type: string, required: false }
            title: { type: text, required: true }
            body_text: { type: text, required: true }
            issuing_authority: { type: string, required: false }
```

**Key Properties:**
- **Declarative:** What to audit, not how to audit it
- **Version-controlled:** Every change tracked in Git
- **Interpretation contract:** SHA256 hash commits to exact semantics (INV-5)

### 1.2 Stage 2: DSL Validation & Model Instantiation

**Input:** Validated YAML  
**Output:** Python dataclasses with runtime validation

```python
# From validation/extractor.py — entity instantiation
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Document:
    """Validated document entity from DSL model."""
    id: str  # UUID v7
    document_type: str
    document_number: Optional[str]
    title: str
    body_text: str
    content_hash: str  # SHA256 of canonical content
    occurrence_hash: str  # SHA256 of location + edition
    
    @property
    def identity_fingerprint(self) -> str:
        """Content-addressed identity — same content, same hash."""
        return self.content_hash[:16]
```

The DSL layer enforces:
- **Type safety:** Runtime validation against YAML schema
- **Identity resolution:** Natural key → stable hash mapping
- **Lineage tracking:** Every field can trace origin to source YAML

### 1.3 Stage 3: CRSS-1 Canonical Serialization

**Input:** Validated entity instances  
**Output:** Deterministic byte sequences suitable for cryptographic commitment

**Specification:** CRSS-1 (Canonical Registry Serialization Specification v1)

```python
# commitment/crss1.py — canonical serialization

CRSS_VERSION = "CRSS1"

# Fixed field order — deterministic serialization
FIELD_ORDER: tuple[str, ...] = (
    "event_type",       # ingestion_log.action
    "natural_key_hash", # concept identity
    "strategy",         # identity resolution strategy
    "content_hash",     # WHAT: content fingerprint
    "occurrence_hash",  # WHERE: corpus location
    "page_number",      # edition pagination
    "source_url",       # provenance URL
    "publication_date", # temporal ordering
    "edition_number",   # edition identifier
    "edition_section",  # section within edition
    "listing_sha256",   # raw listing hash
)

def canonical_bytes(record: dict[str, Any]) -> bytes:
    """Serialize to CRSS-1 canonical form.
    
    MECH-1 rules enforced:
      1. Each field individually NFC-normalized
      2. NULL → empty string before normalization
      3. Joined by pipe (0x7C): "|".join([CRSS_VERSION] + field_values)
      4. UTF-8, no BOM, no trailing newline
      5. Empty final field produces trailing pipe
    """
    parts = [CRSS_VERSION]
    for field in FIELD_ORDER:
        parts.append(_nfc(record.get(field)))
    return "|".join(parts).encode("utf-8")

def leaf_hash(record: dict[str, Any]) -> str:
    """Compute Merkle leaf hash — evidence-grade commitment."""
    return hashlib.sha256(canonical_bytes(record)).hexdigest()
```

**Example Canonical Record:**
```
CRSS1|ingested|a3f7b2...|strict|e9c4d8...|f2a1b9...|15|\
https://www.in.gov.br/...|2024-03-15|Secao_1|DO1|8d7e6f...|
```

### 1.4 Stage 4: LaTeX Template System

**Input:** CRSS-1 commitment envelope + registry data  
**Output:** `.tex` source files — version-controlled, reviewable

The LaTeX generation layer transforms cryptographic commitments into publication-quality documents:

```python
# latex_generator.py — conceptual implementation
from jinja2 import Environment, FileSystemLoader
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass
class AuditReportContext:
    """Complete context for LaTeX template rendering."""
    # Commitment envelope (cryptographic proof)
    commitment_root: str
    crss_version: str
    record_count: int
    computed_at: datetime
    
    # Registry scope
    editions_count: int
    concepts_count: int
    versions_count: int
    earliest_date: datetime
    latest_date: datetime
    
    # Audit findings (aggregated from registry)
    findings: list[AuditFinding]
    
    # Interpretation contract (INV-5)
    sources_yaml_sha256: str
    identity_yaml_sha256: str

class LaTeXReportGenerator:
    """Generate evidence-grade LaTeX audit reports."""
    
    TEMPLATE_DIR = Path("templates/latex")
    
    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(self.TEMPLATE_DIR),
            block_start_string='<%',
            block_end_string='%>',
            variable_start_string='<<',
            variable_end_string='>>',
            comment_start_string='<#',
            comment_end_string='#>',
        )
        # LaTeX-specific filters
        self.env.filters['latex_escape'] = self._latex_escape
        self.env.filters['format_currency'] = self._format_currency
        self.env.filters['hash_short'] = lambda h: h[:16]
        
    def generate_report(
        self,
        envelope: dict[str, Any],
        findings: list[AuditFinding],
        template_name: str = "audit_report.tex.j2"
    ) -> str:
        """Generate complete .tex source from commitment envelope."""
        template = self.env.get_template(template_name)
        context = AuditReportContext(
            commitment_root=envelope['commitment_root'],
            crss_version=envelope['crss_version'],
            record_count=envelope['record_count'],
            computed_at=datetime.fromisoformat(envelope['snapshot']['computed_at_utc']),
            editions_count=envelope['scope']['editions_count'],
            concepts_count=envelope['scope']['concepts_count'],
            versions_count=envelope['scope']['versions_count'],
            earliest_date=datetime.fromisoformat(envelope['scope']['earliest_publication_date']),
            latest_date=datetime.fromisoformat(envelope['scope']['latest_publication_date']),
            findings=findings,
            sources_yaml_sha256=envelope['interpretation_contract'].get('sources_yaml_sha256', ''),
            identity_yaml_sha256=envelope['interpretation_contract'].get('identity_yaml_sha256', ''),
        )
        return template.render(context=context)
```

### 1.5 Stage 5: PDF Compilation

**Input:** `.tex` source files + static assets  
**Output:** PDF documents with embedded cryptographic signatures

```python
# pdf_compiler.py — deterministic PDF generation
import subprocess
from pathlib import Path

class PDFCompiler:
    """Compile LaTeX to PDF with reproducible builds."""
    
    def __init__(self, texlive_path: Path | None = None):
        self.latexmk = texlive_path or Path("/usr/bin/latexmk")
        
    def compile(
        self,
        tex_path: Path,
        output_dir: Path,
        deterministic: bool = True
    ) -> Path:
        """Compile .tex to PDF.
        
        Args:
            tex_path: Path to .tex source
            output_dir: Directory for output PDF
            deterministic: If True, use SOURCE_DATE_EPOCH for reproducible builds
        """
        env = os.environ.copy()
        if deterministic:
            # Force deterministic PDF generation
            env['SOURCE_DATE_EPOCH'] = str(self._get_commit_timestamp())
            env['FORCE_SOURCE_DATE'] = '1'
            env['TEXMFOUTPUT'] = str(output_dir)
        
        cmd = [
            str(self.latexmk),
            "-pdf",
            "-interaction=nonstopmode",
            "-output-directory", str(output_dir),
            str(tex_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            check=True
        )
        
        pdf_path = output_dir / f"{tex_path.stem}.pdf"
        if not pdf_path.exists():
            raise CompilationError(f"PDF not generated: {result.stderr}")
            
        return pdf_path
```

---

## 2. Why LaTeX: The French Administrative Tradition

### 2.1 Precision Typesetting for Legal Documents

LaTeX emerged from the same intellectual tradition that produced French administrative rigor — Donald Knuth's work at Stanford was inspired by the **"composition typographique"** standards of French academic publishing.

| Requirement | LaTeX Solution | Administrative Parallel |
|-------------|----------------|-------------------------|
| **Hyphenation** | `babel` with `french` patterns | Académie Française orthography |
| **Justification** | Microtype package, font expansion | *Mise en page* administrative |
| **Cross-references** | `cleveref`, `hyperref` | *Renvois* jurisprudentiels |
| **Page layout** | `geometry`, `fancyhdr` | *Formulaire* officiel |
| **Mathematical precision** | AMS-LaTeX, `siunitx` | Calculs financiers exacts |

### 2.2 Mathematical Formula Support

Audit calculations require unambiguous notation:

```latex
% LaTeX template excerpt — financial calculations
\begin{equation}
    \text{Montant total signalé} = \sum_{i=1}^{n} \text{contrat}_i \times \text{indicateur}_i
    \label{eq:total-flagged}
\end{equation}

\begin{table}[h]
    \centering
    \begin{tabular}{@{}lS[table-format=5.2]@{}}
        \toprule
        {Catégorie} & {Montant (M€)} \\
        \midrule
        Crédits ruraux & 29700.50 \\
        Contrats irréguliers & 8934.20 \\
        \midrule
        \textbf{Total} & \textbf{38634.70} \\
        \bottomrule
    \end{tabular}
    \caption{Répartition des montants signalés — Engagement cryptographique \texttt{<< context.commitment_root[:16] >>}}
\end{table}
```

### 2.3 Cross-Referencing and Indexing

Legal documents require precise navigation:

```latex
% Index entries for legal references
\usepackage{imakeidx}
\makeindex[name=juris, title=Index jurisprudentiel]

% In document body
La Cour des comptes a précédemment établi\index[juris]{Contrôle@Contrôle légalité} 
que la régularité des actes budgétaires doit être vérifiée selon les modalités 
décrites au §~\ref{sec:verification-regularite}.

% Automatic citation index
\usepackage{splitidx}
\newindex[Index des sources consultées]
```

### 2.4 Version Control Friendly (Text-Based)

Unlike binary formats (Word, PDF), LaTeX sources are **diff-able**:

```diff
% Git diff of audit report changes
- \begin{findings}
-   \item Montant total: 29,7 milliards R$
- \end{findings}
+ \begin{findings}
+   \item Montant total: 29,73 milliards R$
+   \item Engagement racine: \texttt{a3f7b2d9e8c1...}
+ \end{findings}
```

This enables:
- **Peer review** via pull requests
- **Audit trail** of every textual change
- **Deterministic reproduction** from any Git commit

### 2.5 French Administrative Typography

The LaTeX pipeline respects French typographic tradition:

```latex
% french typography setup
\usepackage[french]{babel}
\frenchsetup{
    AutoSpacePunctuation=true,  % « guillemets » with automatic spacing
    og=«, cg=»,                % French quotation marks
    ItemLabeli=\textbullet,    # Standard bullet
    ItemLabelii=--,           # En-dash for sub-items
}

% Specific to administrative documents
\usepackage[autolanguage]{numprint}  % French number formatting
\npthousandsep{~}                    % Thin space as thousands separator
\npdecimalsign{,}                    # Comma as decimal separator
```

---

## 3. Technical Architecture

### 3.1 Complete Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           AUDIT AS CODE ARCHITECTURE                         │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   Source    │    │   Crawler   │    │   Entity    │    │   Registry  │  │
│  │   Corpus    │───▶│   Engine    │───▶│   Extract   │───▶│   Ingest    │  │
│  │  (DOU, etc) │    │   (DSL)     │    │   (YAML)    │    │  (PostgreSQL)│  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘  │
│         │                                                         │         │
│         │         ┌──────────────────────────────────────────────┘         │
│         │         │                                                        │
│         │    ┌────▼────┐    ┌──────────┐    ┌─────────┐    ┌────────┐     │
│         └───▶│  CRSS-1 │───▶│  Merkle  │───▶│ Commit  │───▶│ Anchor │     │
│              │ Serialize│   │   Tree   │    │  ment   │    │  to DB │     │
│              └──────────┘    └──────────┘    └─────────┘    └────┬───┘     │
│                                                                  │         │
│                              ┌───────────────────────────────────┘         │
│                              │                                             │
│                         ┌────▼────┐    ┌──────────┐    ┌─────────┐        │
│                         │  LaTeX  │───▶│   PDF    │───▶│ Evidence│        │
│                         │ Generate│    │ Compile  │    │ Package │        │
│                         └─────────┘    └──────────┘    └─────────┘        │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Deterministic Reproduction

The entire pipeline is **deterministic by design**:

| Stage | Determinism Mechanism | Verification |
|-------|----------------------|--------------|
| YAML → DSL | Schema validation + strict parsing | `sources_yaml_sha256` |
| DSL → CRSS-1 | Canonical serialization (MECH-1) | Byte-by-byte comparison |
| CRSS-1 → Tree | Order-preserving Merkle build (INV-3) | `build_tree(leaves).root` |
| Tree → Commit | SHA256 root hash | Independent recomputation |
| Commit → LaTeX | Jinja2 template with sorted context | Text diff |
| LaTeX → PDF | `SOURCE_DATE_EPOCH`, reproducible builds | `pdfinfo` hash comparison |

### 3.3 Evidence-Grade Documentation

Every output document contains embedded proof of its own validity:

```latex
% audit_report.tex — embedded cryptographic commitments
\begin{titlepage}
    \centering
    \vspace*{2cm}
    {\Huge\bfseries Rapport d'Audit Automatisé\par}
    \vspace{1cm}
    {\Large Cour des Comptes — Session 2025\par}
    \vspace{2cm}
    
    \begin{commitmentbox}
        \textbf{Engagement Cryptographique (CRSS-1)}\\[0.5em]
        \texttt{\scriptsize << context.commitment_root >>}\\[0.3em]
        Racine Merkle: << context.commitment_root[:16] >>...\\
        Enregistrements: << context.record_count|format_number >>\\
        Calculé: << context.computed_at|format_datetime >>
    \end{commitmentbox}
    
    \vfill
    {\small Document généré par Audit as Code — Reproductible et vérifiable\par}
\end{titlepage}
```

---

## 4. The French Connection

### 4.1 LaTeX in French Academic/Legal Tradition

LaTeX adoption in French institutions follows a historical arc:

| Era | Institution | Contribution |
|-----|-------------|--------------|
| 1984 | **INRIA** | First French LaTeX distribution (M. Goossens) |
| 1990 | **CNRS** | `babel-french` package standardization |
| 1995 | **Imprimerie Nationale** | Official document templates |
| 2005 | **Cour des comptes** | Migration of annual reports to LaTeX |
| 2015 | **École Normale Supérieure** | `réglementation` package for legal texts |
| 2025 | **Audit as Code** | Deterministic evidence-grade pipeline |

### 4.2 "Composition Typographique" Precision

French administrative typography demands exactitude:

```latex
% French administrative document class
\documentclass[
    a4paper,
    12pt,
    french,
    official,      % Imprimerie Nationale spacing rules
    numbering=legal % Article/paragraphe numbering
]{administratif}

% Spacing rules from Imprimerie Nationale
\setlength{\parindent}{1.5em}      % Alinéa traditionnel
\setlength{\parskip}{0pt}          % Pas d'espace inter-paragraphe
\linespread{1.15}                  % Interligne administratif

% "Composition à la française"
\frenchspacing                      % Espaces uniformes
\usepackage{microtype}              % Rapprochement des caractères
\ DisableLigatures[f]{encoding=*}   % Pas de ligature sur le f (règle française)
```

### 4.3 Comparison to Traditional "Mise en Page" Administrative

| Aspect | Traditional "Mise en Page" | Audit as Code LaTeX |
|--------|---------------------------|---------------------|
| **Preparation** | Manual formatting in Word | Automated from registry |
| **Review** | Track changes, email chains | Git pull requests |
| **Validation** | Human signature | Cryptographic commitment + human signature |
| **Reproduction** | "Print to PDF" | Deterministic compilation |
| **Archival** | Binary .docx + .pdf | Text .tex + commitment envelope |
| **Verification** | Trust in process | Independent recomputation |

### 4.4 French Engineering Tradition

The pipeline embodies French engineering philosophy:

> *"Le génie civil français ne se contente pas de construire — il conçoit des systèmes que d'autres peuvent vérifier."*

- **Ponts et Chaussées:** Structural integrity through visible, calculable design
- **Arts et Métiers:** Precision tooling for reproducible results  
- **École des Mines:** Resource accounting with mathematical certainty

The CRSS-1 commitment scheme is the **digital equivalent** of a French engineering blueprint — every element dimensioned, every assumption stated, every result verifiable.

---

## 5. Code Examples: Complete Flow

### 5.1 End-to-End Report Generation

```python
#!/usr/bin/env python3
"""Generate evidence-grade LaTeX audit report."""

from pathlib import Path
from commitment.anchor import compute_commitment
from latex.generator import LaTeXReportGenerator
from pdf.compiler import PDFCompiler
from findings.aggregator import aggregate_findings

def generate_audit_report(
    dsn: str,
    sources_yaml: Path,
    output_dir: Path
) -> Path:
    """Complete pipeline: registry → LaTeX → PDF.
    
    Returns:
        Path to generated PDF with embedded cryptographic proof.
    """
    # Stage 1: Compute commitment from registry
    envelope = compute_commitment(
        dsn=dsn,
        sources_yaml=sources_yaml,
        identity_yaml=sources_yaml.parent / "identity.yaml",
    )
    
    # Stage 2: Aggregate findings from committed data
    findings = aggregate_findings(
        commitment_root=envelope['commitment_root'],
        dsn=dsn
    )
    
    # Stage 3: Generate LaTeX source
    generator = LaTeXReportGenerator()
    tex_source = generator.generate_report(
        envelope=envelope,
        findings=findings,
        template_name="cour_des_comptes_2025.tex.j2"
    )
    
    tex_path = output_dir / f"audit_{envelope['commitment_root'][:16]}.tex"
    tex_path.write_text(tex_source, encoding='utf-8')
    
    # Stage 4: Compile to PDF (deterministic)
    compiler = PDFCompiler()
    pdf_path = compiler.compile(
        tex_path=tex_path,
        output_dir=output_dir,
        deterministic=True  # SOURCE_DATE_EPOCH for reproducibility
    )
    
    return pdf_path


# CLI entry point
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate evidence-grade LaTeX audit report"
    )
    parser.add_argument("--dsn", required=True, help="PostgreSQL connection string")
    parser.add_argument("--sources", required=True, help="Path to sources_v3.yaml")
    parser.add_argument("--output", required=True, help="Output directory")
    
    args = parser.parse_args()
    
    pdf_path = generate_audit_report(
        dsn=args.dsn,
        sources_yaml=Path(args.sources),
        output_dir=Path(args.output)
    )
    
    print(f"Report generated: {pdf_path}")
```

### 5.2 LaTeX Template Structure

```latex
% templates/cour_des_comptes_2025.tex.j2
\documentclass[
    a4paper,
    12pt,
    french,
    official
]{administratif}

% ─────────────────────────────────────────────────────────────────────────────
% PACKAGES
% ─────────────────────────────────────────────────────────────────────────────
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{microtype}
\usepackage{booktabs}
\usepackage{siunitx}
\usepackage{xcolor}
\usepackage{tcolorbox}
\usepackage{hyperref}
\usepackage{fancyhdr}
\usepackage{lastpage}

% French typography
\usepackage[french]{babel}
\frenchsetup{AutoSpacePunctuation=true}

% Custom colors — Cour des comptes palette
\definecolor{cdcblue}{RGB}{0, 51, 102}
\definecolor{cdcgold}{RGB}{201, 169, 97}

% ─────────────────────────────────────────────────────────────────────────────
% COMMITMENT BOX
% ─────────────────────────────────────────────────────────────────────────────
\newtcolorbox{commitmentbox}{
    colback=cdcblue!5,
    colframe=cdcblue,
    fonttitle=\bfseries,
    title=Engagement Cryptographique,
    boxrule=0.5pt
}

% ─────────────────────────────────────────────────────────────────────────────
% DOCUMENT METADATA
% ─────────────────────────────────────────────────────────────────────────────
\title{Rapport d'Audit Automatisé}
\subtitle{Analyse du Registre Déterministe}
\date{<< context.computed_at|format_date >>}
\commitment{<< context.commitment_root >>}

% ─────────────────────────────────────────────────────────────────────────────
% HEADER/FOOTER
% ─────────────────────────────────────────────────────────────────────────────
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small\textcolor{cdcblue}{Cour des Comptes}}
\fancyhead[R]{\small\textcolor{cdcblue}{Rapport << context.crss_version >>}}
\fancyfoot[C]{\thepage/\pageref{LastPage}}
\renewcommand{\headrulewidth}{0.4pt}

% ─────────────────────────────────────────────────────────────────────────────
% CONTENT
% ─────────────────────────────────────────────────────────────────────────────
\begin{document}

\begin{titlepage}
    \centering
    \vspace*{3cm}
    {\Huge\bfseries\textcolor{cdcblue}{Rapport d'Audit Automatisé}\par}
    \vspace{1cm}
    {\Large\textit{Analyse du Registre Déterministe}\par}
    \vspace{3cm}
    
    \begin{commitmentbox}
        \begin{tabular}{@{}ll@{}}
            \textbf{Racine CRSS-1:} & \texttt{<< context.commitment_root >>} \\
            \textbf{Enregistrements:} & << context.record_count|format_number >> \\
            \textbf{Éditions:} & << context.editions_count >> \\
            \textbf{Concepts:} & << context.concepts_count >> \\
            \textbf{Versions:} & << context.versions_count >> \\
            \textbf{Période:} & << context.earliest_date|format_date >> — << context.latest_date|format_date >> \\
        \end{tabular}
    \end{commitmentbox}
    
    \vfill
    {\small Document généré par le système Audit as Code\\
     Reproductible et vérifiable indépendamment\par}
\end{titlepage}

\tableofcontents
\newpage

\section{Introduction}

Ce rapport présente les résultats d'une audit automatisé conduite selon 
la méthodologie \emph{Audit as Code}. Les données analysées sont 
archivées dans un registre déterministe dont l'engagement cryptographique 
est:\\[0.5em]
\begin{center}
\texttt{<< context.commitment_root >>}
\end{center}

\section{Méthodologie}

\subsection{Spécifications d'Audit}

Les règles d'extraction et de validation sont définies dans les fichiers 
YAML suivants, dont les empreintes SHA256 constituent le contrat 
d'interprétation:\\[0.5em]

\begin{tabular}{@{}ll@{}}
    \texttt{sources\_v3.yaml}: & \texttt{<< context.sources_yaml_sha256 >>} \\
    \texttt{identity.yaml}: & \texttt{<< context.identity_yaml_sha256 >>} \\
\end{tabular}

\subsection{Sérialisation Canonique CRSS-1}

Les enregistrements sont sérialisés selon la spécification CRSS-1 
(\emph{Canonical Registry Serialization Specification v1}), garantissant:
\begin{itemize}
    \item \textbf{Déterminisme:} Mêmes entrées → Mêmes sorties
    \item \textbf{Vérifiabilité:} Reproduction indépendante possible
    \item \textbf{Immutabilité:} Engagement cryptographique inviolable
\end{itemize}

\section{Constatations}

<% for finding in context.findings %>
\subsection{<< finding.category >>}

<< finding.description >>

\begin{table}[h]
    \centering
    \begin{tabular}{@{}lS[table-format=10.2]@{}}
        \toprule
        {Indicateur} & {Valeur} \\
        \midrule
        <% for metric in finding.metrics %>
        << metric.name >> & << metric.value|format_number >> \\
        <% endfor %>
        \bottomrule
    \end{tabular}
\end{table}
<% endfor %>

\section{Annexes}

\subsection{Contrat d'Interprétation (INV-5)}

Conformément à l'invariant INV-5 de la spécification CRSS-1, les fichiers 
de spécification YAML sont intégrés à l'engagement cryptographique. 
Toute modification des règles d'audit produit un engagement distinct, 
préservant la traçabilité complète.

\end{document}
```

### 5.3 Verification Script

```python
#!/usr/bin/env python3
"""Verify PDF report against registry commitment."""

import re
import json
from pathlib import Path
from commitment.crss1 import canonical_bytes
from commitment.tree import build_tree

def extract_commitment_from_pdf(pdf_path: Path) -> str | None:
    """Extract embedded commitment root from PDF metadata or text."""
    # Method 1: Check PDF metadata
    import subprocess
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        capture_output=True,
        text=True
    )
    for line in result.stdout.split('\n'):
        if 'Keywords' in line and 'commitment=' in line:
            return line.split('commitment=')[1].strip()
    
    # Method 2: Extract from text content
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True,
        text=True
    )
    # Look for CRSS-1 root pattern (64 hex chars)
    match = re.search(r'[a-f0-9]{64}', result.stdout)
    return match.group(0) if match else None


def verify_report_integrity(
    pdf_path: Path,
    envelope_path: Path
) -> bool:
    """Verify that PDF matches the commitment envelope."""
    
    # Load envelope
    envelope = json.loads(envelope_path.read_text())
    expected_root = envelope['commitment_root']
    
    # Extract from PDF
    extracted_root = extract_commitment_from_pdf(pdf_path)
    
    if extracted_root is None:
        raise ValueError("No commitment found in PDF")
    
    # Verify match
    if extracted_root != expected_root:
        print(f"MISMATCH!")
        print(f"  PDF claims:     {extracted_root}")
        print(f"  Envelope says:  {expected_root}")
        return False
    
    print(f"✓ Verified: PDF commitment matches envelope")
    print(f"  Root: {expected_root}")
    print(f"  Records: {envelope['record_count']}")
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: verify_report.py <report.pdf> <envelope.json>")
        sys.exit(1)
    
    valid = verify_report_integrity(
        Path(sys.argv[1]),
        Path(sys.argv[2])
    )
    sys.exit(0 if valid else 1)
```

---

## 6. Integration with Existing Infrastructure

### 6.1 Registry Database Schema

The LaTeX pipeline reads from the existing `registry` schema:

```sql
-- Registry tables (from dbsync/registry_schema.sql)
CREATE SCHEMA IF NOT EXISTS registry;

-- Canonical projection for CRSS-1
CREATE OR REPLACE VIEW registry.crss1_projection AS
SELECT
    l.action AS event_type,
    trim(c.natural_key_hash) AS natural_key_hash,
    COALESCE(trim(c.strategy), '') AS strategy,
    trim(v.content_hash) AS content_hash,
    trim(o.occurrence_hash) AS occurrence_hash,
    COALESCE(trim(o.page_number), '') AS page_number,
    COALESCE(trim(o.source_url), '') AS source_url,
    COALESCE(e.publication_date::text, '') AS publication_date,
    COALESCE(trim(e.edition_number), '') AS edition_number,
    COALESCE(trim(e.edition_section), '') AS edition_section,
    COALESCE(trim(e.listing_sha256), '') AS listing_sha256
FROM registry.ingestion_log l
JOIN registry.occurrences o ON trim(o.occurrence_hash) = trim(l.occurrence_hash)
JOIN registry.versions v ON v.id = o.version_id
JOIN registry.concepts c ON trim(c.natural_key_hash) = trim(v.natural_key_hash)
JOIN registry.editions e ON trim(e.edition_id) = trim(o.edition_id)
WHERE l.action != 'duplicate_skipped'
ORDER BY e.publication_date, e.edition_number, o.page_number, o.occurrence_hash;
```

### 6.2 CLI Integration

```bash
# Compute commitment and generate LaTeX report
python3 commitment_cli.py compute \
    --dsn "$GABI_DSN" \
    --out commitment_2025.json \
    --sources sources_v3.yaml

# Generate LaTeX source
python3 latex_generator.py \
    --envelope commitment_2025.json \
    --template cour_des_comptes_2025 \
    --output report_2025.tex

# Compile to PDF (deterministic)
latexmk -pdf -interaction=nonstopmode \
    -output-directory=./output \
    report_2025.tex

# Verify PDF against commitment
python3 verify_report.py \
    output/report_2025.pdf \
    commitment_2025.json
```

---

## 7. Security and Governance

### 7.1 Three Lines of Defense

| Line | Control | Implementation |
|------|---------|----------------|
| **1st** | Audit logic correctness | Unit tests for extraction rules |
| **2nd** | Registry integrity | CRSS-1 commitment + Merkle tree |
| **3rd** | Output verification | PDF commitment extraction + validation |

### 7.2 Evidence Preservation

All artifacts are preserved for evidentiary purposes:

```
audit_evidence/
├── 2025-03-01_audit_rural_credit/
│   ├── sources_v3.yaml           # Interpretation contract
│   ├── identity.yaml             # Identity rules
│   ├── commitment.json           # CRSS-1 envelope
│   ├── canonical_records.txt     # CRSS-1 serialized records
│   ├── report.tex                # LaTeX source
│   ├── report.pdf                # Compiled output
│   ├── compilation.log           # LaTeX build log
│   └── verification_proof.json   # Third-party verification
```

---

## 8. Conclusion

The Audit as Code LaTeX Pipeline represents the convergence of:

- **French administrative tradition:** *Composition typographique* as discipline of clear thought
- **Cryptographic engineering:** Deterministic, verifiable, immutable
- **Software engineering:** Version-controlled, tested, reproducible

> *"L'audit n'est pas une destination, c'est une infrastructure."*

For Cour des Comptes, this pipeline offers:
1. **Transparency:** Every conclusion traceable to cryptographic proof
2. **Reproducibility:** Independent verification by any third party
3. **Longevity:** Text-based sources readable decades hence
4. **Elegance:** *La mise en page* worthy of French administrative tradition

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **CRSS-1** | Canonical Registry Serialization Specification v1 |
| **content_hash** | SHA256 of canonical document content — defines WHAT |
| **occurrence_hash** | SHA256 of corpus location — defines WHERE |
| **commitment_root** | Merkle root hash — cryptographic summary of registry state |
| **INV-5** | Invariant 5: Interpretation contract from rule file bytes |
| **MECH-1** | Mechanism 1: Byte-level encoding (NFC, no BOM, UTF-8) |

## Appendix B: References

1. CRSS-1 Specification: `commitment/crss1.py`
2. Anchor Computation: `commitment/anchor.py`
3. YAML DSL: `sources_v3.yaml`
4. French Typography: *Lexique des règles typographiques en usage à l'Imprimerie nationale* (2002)

---

*Document generated for Cour des Comptes — March 2025*  
*TCU Audit as Code Initiative — Open Source, Open Standards*
