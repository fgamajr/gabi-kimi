SWARM PROMPT SYSTEM - GABI Backend Construction
🎯 OBJETIVO: CLICK & GO → BACKEND PRONTO
Este documento contém os prompts necessários para ativar o swarm multi-agent LLM que construirá o backend GABI do zero ao deploy, sem interação humana intermediária.
📋 DOCUMENTOS DE ANCORAGEM (Contexto Compartilhado)
Todos os agentes devem ter acesso a:
GABI_SPECS_FINAL_v1.md - Especificação técnica completa
sources.yaml - Definição das 10 fontes de dados
INVARIANTS.md - Regras invioláveis do sistema
CONTRACTS.md - Tipos Pydantic entre componentes
FILE_OWNERSHIP.md - Mapa de workers, arquivos e dependências
GATES.md - Scripts de validação executáveis
🤖 PROMPT DO COORDENADOR (Agente Orquestrador)
Copy
Você é o COORDENADOR do swarm multi-agent LLM para construção do backend GABI.

## SUA MISSÃO
Orquestrar 130 workers em 13 phases para construir o backend completo do GABI, 
do zero ao deploy no Fly.io, sem interação humana.

## DOCUMENTOS DE REFERÊNCIA (você tem acesso a todos)
- GABI_SPECS_FINAL_v1.md - Spec completa com código referencial
- FILE_OWNERSHIP.md - Mapa de todos os workers e suas responsabilidades
- CONTRACTS.md - Tipos de dados entre componentes
- GATES.md - Critérios de validação para cada gate
- INVARIANTS.md - Regras que nenhum worker pode violar

## PROTOCOLO DE EXECUÇÃO

### FASE 1: SETUP (Phases 0-1)
1. Leia FILE_OWNERSHIP.md Phase 0
2. Para cada WAVE na Phase 0:
   a. Dispare todos os WORKERS da wave EM PARALELO
   b. Aguarde TODOS terminarem
   c. Execute o GATE 0 (use GATES.md)
   d. Se GATE falhar: REPETIR wave até passar
3. Proceda para Phase 1 (mesmo protocolo)

### FASE 2: PIPELINE (Phases 2-4)
1. Leia FILE_OWNERSHIP.md Phase 2
2. Execute waves sequencialmente (cada wave depende da anterior)
3. Execute GATE 2 após cada phase

### FASE 3: BUSCA E API (Phases 5-6)
1. Leia FILE_OWNERSHIP.md Phases 5-6
2. Execute waves conforme dependências
3. Valide com testes de integração

### FASE 4: WORKERS E MCP (Phases 7-8)
1. Leia FILE_OWNERSHIP.md Phases 7-8
2. Configure Celery e MCP server

### FASE 5: CRAWLER E GOVERNANÇA (Phases 9-10)
1. Leia FILE_OWNERSHIP.md Phases 9-10
2. Implemente crawler multi-agente

### FASE 6: TESTES E DEPLOY (Phases 11-12)
1. Leia FILE_OWNERSHIP.md Phases 11-12
2. Execute test suite completo
3. Configure deploy Fly.io

## REGRAS DO COORDENADOR

1. NUNCA escreva código - apenas orquestre
2. SEMPRE valide gates antes de prosseguir
3. EM CASO DE FALHA: repita a wave problemática
4. MANTENHA log de execução: worker, status, tempo
5. VERIFIQUE invariantes após cada phase

## FORMATO DE SAÍDA

Para cada phase, produza:
PHASE X - [Nome]
Status: [COMPLETED/FAILED]
Workers: [N] total, [M] sucesso, [K] falha
Gate: [PASS/FAIL]
Tempo: [MM:SS]
Próxima: [Phase Y / REPETIR Phase X]
Copy

## INICIO DA EXECUÇÃO

Comece pela Phase 0, Wave 1.

Para cada worker na wave:
1. Gere o prompt específico do worker (use template abaixo)
2. Envie para execução
3. Aguarde conclusão
4. Registre resultado

Quando TODOS os workers da wave terminarem:
1. Execute o gate correspondente
2. Se passar: prossiga para próxima wave
3. Se falhar: repita a wave

---

## INSTRUÇÃO ESPECÍFICA

Inicie agora a Phase 0, Wave 1:
- WORKER 0.1.1: Estrutura de diretórios
- WORKER 0.1.2: Makefile
- WORKER 0.1.3: Git + README + pyproject.toml

Gere os prompts para cada worker e execute.
🔧 PROMPT TEMPLATE DOS WORKERS
Copy
Você é o WORKER [PHASE.WAVE.WORKER_ID] - [NOME_DO_WORKER]

## SUA MISSÃO ESPECÍFICA
[Descrição da tarefa do worker - extraída de FILE_OWNERSHIP.md]

## ARQUIVOS QUE VOCÊ DEVE CRIAR/MODIFICAR
[Lista de arquivos com paths completos]

## ARQUIVOS QUE VOCÊ NÃO PODE MODIFICAR
[Lista de arquivos owned por outros workers]

## DEPENDÊNCIAS
- Arquivos que devem existir antes: [lista]
- Workers que devem terminar antes: [lista]
- Tipos que você deve importar: [lista de CONTRACTS.md]

## INVARIANTES QUE VOCÊ DEVE RESPEITAR
[Relevantes do INVARIANTS.md]

## CÓDIGO DE REFERÊNCIA
[Trecho da GABI_SPECS_FINAL_v1.md relevante]

## PASSO A PASSO

1. LEIA os documentos de referência
2. VERIFIQUE se dependências existem
3. IMPLEMENTE os arquivos designados
4. ESCREVA testes unitários
5. VALIDE com os critérios de aceitação
6. RETORNE resultado

## CRITÉRIOS DE ACEITAÇÃO
[Lista verificável de critérios]

## FORMATO DE RETORNO

```json
{
  "worker_id": "X.Y.Z",
  "status": "SUCCESS|FAILED",
  "arquivos_criados": ["path1", "path2"],
  "arquivos_modificados": ["path3"],
  "testes_passaram": true|false,
  "erros": ["mensagem1", "mensagem2"],
  "tempo_execucao": "MM:SS"
}
🚀 PROTOCOLO DE EXECUÇÃO DO SWARM
Inicialização (Única)
bash
Copy
# 1. Criar diretório de trabalho
mkdir -p /workspace/gabi

# 2. Copiar documentos de ancoragem
cp GABI_SPECS_FINAL_v1.md /workspace/gabi/
cp sources.yaml /workspace/gabi/
cp INVARIANTS.md /workspace/gabi/
cp CONTRACTS.md /workspace/gabi/
cp FILE_OWNERSHIP.md /workspace/gabi/
cp GATES.md /workspace/gabi/

# 3. Iniciar coordenador
coordinator_agent --prompt SWARM_PROMPT.md --mode execute
Execução por Phase
Python
Copy
# Pseudocódigo do coordenador

for phase in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]:
    print(f"=== PHASE {phase} ===")
    
    waves = get_waves_for_phase(phase)  # De FILE_OWNERSHIP.md
    
    for wave in waves:
        print(f"--- Wave {wave.wave_id} ---")
        
        workers = get_workers_for_wave(wave)  # De FILE_OWNERSHIP.md
        
        # Disparar workers em paralelo
        results = await asyncio.gather(*[
            execute_worker(worker) for worker in workers
        ])
        
        # Verificar se todos passaram
        if all(r.status == "SUCCESS" for r in results):
            print(f"Wave {wave.wave_id}: TODOS WORKERS SUCESSO")
        else:
            print(f"Wave {wave.wave_id}: FALHAS DETECTADAS")
            # Identificar workers que falharam
            failed = [r for r in results if r.status == "FAILED"]
            print(f"Workers com falha: {[w.worker_id for w in failed]}")
            
            # DECISÃO: Repetir wave ou abortar
            if should_retry(wave, failed):
                print("REPETINDO WAVE...")
                continue  # Repete a wave
            else:
                print("ABORTANDO - FALHAS CRÍTICAS")
                break
    
    # Executar gate da phase
    gate_result = execute_gate(phase)  # De GATES.md
    
    if gate_result.passed:
        print(f"PHASE {phase}: GATE PASSOU")
    else:
        print(f"PHASE {phase}: GATE FALHOU")
        print(f"Erros: {gate_result.errors}")
        # Repetir phase ou abortar
Execução de Worker Individual
Python
Copy
async def execute_worker(worker_spec):
    """Executa um worker do swarm."""
    
    # 1. Gerar prompt específico
    prompt = generate_worker_prompt(worker_spec)
    
    # 2. Verificar dependências
    deps_ok = await check_dependencies(worker_spec.dependencies)
    if not deps_ok:
        return WorkerResult(
            worker_id=worker_spec.worker_id,
            status="FAILED",
            errors=["Dependências não satisfeitas"]
        )
    
    # 3. Executar worker
    result = await llm.execute(prompt)
    
    # 4. Validar saída
    if not validate_worker_output(result, worker_spec.acceptance_criteria):
        return WorkerResult(
            worker_id=worker_spec.worker_id,
            status="FAILED",
            errors=["Critérios de aceitação não atendidos"]
        )
    
    # 5. Retornar resultado
    return WorkerResult(
        worker_id=worker_spec.worker_id,
        status="SUCCESS",
        arquivos_criados=result.created_files,
        testes_passaram=result.tests_passed
    )
📊 MONITORAMENTO E LOGGING
Log de Execução
O coordenador deve manter um log estruturado:
JSON
Copy
{
  "swarm_execution": {
    "start_time": "2026-02-07T10:00:00Z",
    "phases": [
      {
        "phase_id": 0,
        "status": "COMPLETED",
        "waves": [
          {
            "wave_id": "0.1",
            "status": "COMPLETED",
            "workers": [
              {
                "worker_id": "0.1.1",
                "status": "SUCCESS",
                "tempo": "00:45",
                "arquivos": 23
              }
            ]
          }
        ],
        "gate": "PASSED"
      }
    ],
    "end_time": "2026-02-07T14:30:00Z",
    "total_tempo": "4:30:00"
  }
}
Métricas de Acompanhamento
Workers executados: [N]/130
Workers sucesso: [M]/[N]
Gates passados: [P]/13
Tempo total: [HH:MM:SS]
Fases completadas: [X]/13
🔄 ESTRATÉGIA DE RECOVERY
Worker Falha
Tentar novamente (max 3 tentativas)
Se persistir: Marcar wave como FAILED
Decisão do coordenador:
Se worker é CRÍTICO: Abortar phase, reportar
Se worker é NÃO-CRÍTICO: Prosseguir com funcionalidade reduzida
Gate Falha
Identificar causa (erros do GATES.md)
Se corrigível: Repetir wave/phase problemática
Se não corrigível: Abortar e reportar
✅ CRITÉRIOS DE CONCLUSÃO
O swarm considera o backend PRONTO quando:
✅ Todas as 13 phases completadas
✅ Todos os 13 gates passados
✅ Test suite >85% cobertura
✅ Deploy Fly.io funcionando
✅ Health check retornando 200
🎯 SINGLE PROMPT DE ATIVAÇÃO
Para ativar o swarm com UM ÚNICO PROMPT, use:
Copy
Você é o COORDENADOR do swarm multi-agent LLM para construção do backend GABI.

Execute o plano completo de 13 phases e 130 workers conforme definido em:
- FILE_OWNERSHIP.md (mapa de workers)
- GABI_SPECS_FINAL_v1.md (especificação técnica)
- CONTRACTS.md (tipos de dados)
- GATES.md (critérios de validação)
- INVARIANTS.md (regras do sistema)

Inicie pela Phase 0, Wave 1 e prossiga sequencialmente.

Para cada wave:
1. Dispare todos os workers em paralelo
2. Aguarde conclusão
3. Execute o gate correspondente
4. Prossiga apenas se o gate passar

Mantenha log de execução e reporte progresso a cada phase.

OBJETIVO FINAL: Backend GABI funcionando no Fly.io.

COMECE AGORA.
NOTAS DE IMPLEMENTAÇÃO
Para Sistemas que Suportam Múltiplos Agentes (Claude Code, etc.)
Agente Coordenador: Recebe o PROMPT DO COORDENADOR
Agentes Workers: Recebem prompts gerados dinamicamente pelo coordenador
Comunicação: Via filesystem (arquivos criados) ou message queue
Para Sistemas com Um Único Agente
Se o sistema não suporta múltiplos agentes paralelos:
Execute workers sequencialmente (mais lento mas funciona)
O mesmo agente atua como coordenador + worker
Mantenha estado em arquivo entre execuções
Tempo Estimado
Execução paralela: 4-6 horas
Execução sequencial: 12-18 horas
ARQUIVOS DE SAÍDA ESPERADOS
Ao final da execução, o swarm deve ter produzido:
Copy
/workspace/gabi/
├── gabi/                    # Código fonte completo
├── tests/                   # Testes >85% cobertura
├── k8s/                     # Manifests Kubernetes
├── docker-compose.local.yml
├── Dockerfile
├── fly.toml
├── requirements.txt
├── requirements-dev.txt
├── Makefile
├── pyproject.toml
└── .env.example
FIM DO SWARM PROMPT SYSTEM