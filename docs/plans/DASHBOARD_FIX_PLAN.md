> Status: **histórico / deprecated (backend-only desde 2026-02-19)**  
> Este plano referencia `Gabi.Web` e não representa o runtime atual.

# Dashboard Fix Plan (all-in-one)

Plano concreto para alinhar o dashboard atual ao projeto visual: navegação, cards, pipeline e dados.

---

## 1. Rotas e navegação (sidebar)

**Problema:** Sidebar aponta para `/dashboard/sources`, `/dashboard/pipeline`, `/dashboard/settings`, mas só existem rotas para `/dashboard` (index) e `/dashboard/safra`. Clicar em Sources, Pipeline ou Settings leva a URL sem rota.

**Solução:** Manter uma única página de overview; usar scroll para seções em vez de rotas separadas. Sidebar continua com "Dashboard" (overview), "Safra Details" (rota), "Settings" (rota ou placeholder).

**Alterações:**

- **[App.tsx](src/Gabi.Web/App.tsx)**  
  - Manter apenas: `Route index element={<Dashboard />}`, `Route path="safra" element={<SafraDetails />}`.  
  - Opcional: `Route path="settings" element={<SettingsPlaceholder />}` (página simples "Settings – em breve") para não quebrar o link.

- **[DashboardSidebar.tsx](src/Gabi.Web/dashboard/components/DashboardSidebar.tsx)**  
  - Remover `path: '/dashboard/sources'` e `path: '/dashboard/pipeline'` (não são rotas).  
  - **Opção A (scroll):** "Dashboard" vai para `/dashboard`. "Sources" e "Pipeline" também navegam para `/dashboard` mas com `?section=sources` ou `?section=pipeline`; no [Dashboard.tsx](src/Gabi.Web/dashboard/pages/Dashboard.tsx) usar `useSearchParams` e `ref` para scroll até a seção (ex.: `#sources`, `#pipeline`).  
  - **Opção B (mais simples):** Deixar só dois itens de navegação: "Dashboard" (`/dashboard`) e "Safra Details" (`/dashboard/safra`). Remover "Sources" e "Pipeline" do sidebar (o conteúdo já está na mesma página). "Settings" pode ir para `/dashboard/settings` com placeholder.

**Recomendação:** Opção B: sidebar com Dashboard, Safra Details, Settings (placeholder). Sem scroll por query.

---

## 2. Card Sync Status (UI + rótulo)

**Problema:** Card mostra só o número (ex.: "0") e no rodapé "Pending: X, Total: Y". O visual espera algo como "X/Y Synced" e "Z Processing" em destaque.

**Alterações:**

- **[Dashboard.tsx](src/Gabi.Web/dashboard/pages/Dashboard.tsx)**  
  - **Value:** Exibir `{synced_count}/{total_count} synced` (ou `total_count` = total de jobs/sources, conforme contrato). Ex.: `value={\`${fmt(syncStatus?.synced_count)}/${fmt(syncStatus?.total_count)} synced\`}`.  
  - **Description (ou footer):** "Z processing" quando `processing_count > 0`. Ex.: `description={syncStatus?.processing_count ? \`${syncStatus.processing_count} processing\` : 'All synced'}`.  
  - Manter footer opcional com "Total: X" se fizer sentido.

---

## 3. Card Processing Rate (rótulo e métrica)

**Problema:** O card usa `processing_count` (jobs ativos) e descrição "Active jobs". No visual é "Processing Rate" com valor "N/A" e tendência.

**Alterações:**

- **[Dashboard.tsx](src/Gabi.Web/dashboard/pages/Dashboard.tsx)**  
  - **Título:** Manter "Processing Rate".  
  - **Value:** Se a API passar `processing_rate` (docs/min) ou similar, usar; senão exibir `"N/A"`.  
  - **Description:** "Current throughput" (ou "Active jobs: X" em pequeno) em vez de só "Active jobs".  
  - **Trend:** Se o backend enviar um campo de tendência (ex.: `+8.3%`), usar no MetricCard (prop `trend`).  
- **Backend (opcional):** Em [DashboardModels.cs](src/Gabi.Contracts/Dashboard/DashboardModels.cs) e [DashboardService.cs](src/Gabi.Api/Services/DashboardService.cs), adicionar em stats algo como `processing_rate_docs_per_min` (nullable) e `processing_rate_trend_percent` (nullable). Enquanto não houver métrica real, enviar `null` e tendência stub; no front mostrar "N/A" e opcionalmente o trend.

---

## 4. Pipeline: "Soon", Phase X e status Complete/Processing

**Problema:** Quase todos os estágios aparecem com badge "Soon" e "Phase 3/4/5/6 - Coming in next release"; só Discovery está "available". O visual espera estágios em "Complete" ou "Processing" com progresso real.

**Alterações:**

- **Backend [DashboardService.cs](src/Gabi.Api/Services/DashboardService.cs) – GetPipelineAsync:**  
  - **Discovery:** Manter `Availability = "available"`. Quando `totalLinks > 0` e `count == total`, definir `Status = PipelineStageStatus.Idle` e considerar mensagem "Complete" (ou sem "Phase X").  
  - **Outros estágios (Ingest, Processing, Embedding, Indexing):**  
    - Trocar mensagem de "Phase 3 - Coming in next release" para "Coming in next release" (ou "Phase 2", "Phase 3", etc. de forma consistente: Discovery=1, Ingest=2, Processing=3, Embedding=4, Indexing=5).  
    - Ou remover "Phase X" e deixar só "Coming in next release".

- **Frontend [PipelineOverview.tsx](src/Gabi.Web/dashboard/components/PipelineOverview.tsx):**  
  - **Badge "Soon":** Mostrar "Soon" apenas quando `availability === 'coming_soon'`. Para estágios `available`, quando `count >= total && total > 0` exibir badge/texto "Complete" (verde) em vez de "Soon".  
  - **Status visual:** Se `status === 'active'` → indicador "Processing"; se `availability === 'available' && count >= total && total > 0` → "Complete" (checkmark ou texto verde).  
  - **Message:** Exibir `stage.message` sem alterar; backend já pode enviar texto sem "Phase X" ou com numeração corrigida.

---

## 5. Resumo das alterações por arquivo

| Arquivo | Alteração |
|--------|-----------|
| [App.tsx](src/Gabi.Web/App.tsx) | Manter rotas atuais; opcional: rota `settings` com placeholder. |
| [DashboardSidebar.tsx](src/Gabi.Web/dashboard/components/DashboardSidebar.tsx) | Ajustar `navItems`: apenas Dashboard (`/dashboard`), Safra Details (`/dashboard/safra`), Settings (`/dashboard/settings` com placeholder). Remover Sources e Pipeline como rotas. |
| [Dashboard.tsx](src/Gabi.Web/dashboard/pages/Dashboard.tsx) | Sync Status: value "X/Y synced", description/footer "Z processing". Processing Rate: value "N/A" quando não houver taxa, description "Current throughput", trend se a API enviar. |
| [PipelineOverview.tsx](src/Gabi.Web/dashboard/components/PipelineOverview.tsx) | Lógica de badge: "Complete" quando available e count >= total; "Soon" só para coming_soon. Status "Processing" para active, "Complete" para concluído. |
| [DashboardService.cs](src/Gabi.Api/Services/DashboardService.cs) | GetPipelineAsync: mensagens dos estágios sem "Phase 3" repetido; numeração consistente (1–5) ou remover "Phase X". Discovery com status Idle quando count == total. |
| (Opcional) [DashboardModels.cs](src/Gabi.Contracts/Dashboard/DashboardModels.cs) + DashboardService | Campos opcionais para Processing Rate (valor e tendência); frontend usa para N/A + trend. |

---

## 6. Ordem sugerida de implementação

1. **Sidebar e rotas** – Ajustar `DashboardSidebar` e, se quiser, rota `settings` em App, para não haver links quebrados.  
2. **Cards** – Sync Status e Processing Rate no Dashboard.tsx (textos e valor N/A).  
3. **Pipeline** – Backend: mensagens e status do Discovery; frontend: regra de "Complete" vs "Soon" e indicador Processing/Complete.  
4. **Opcional** – Processing Rate no backend (campos + stub) e trend no card.

Com isso, navegação fica consistente, os cards alinham ao visual (Sync Status como "X/Y synced", Processing Rate como N/A + tendência) e o pipeline deixa de parecer tudo "Soon" com "Phase 3" repetido, passando a mostrar "Complete" onde fizer sentido.
