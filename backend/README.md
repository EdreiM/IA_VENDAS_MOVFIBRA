# Backend Eva

## Local

Requer PostgreSQL (`DATABASE_URL` no `.env` da raiz).

```powershell
# da raiz do monorepo
.\run_backend.ps1
# API em http://127.0.0.1:8001
```

## Admin / painel

Rotas sob `/admin/*` e `/metrics/*` exigem `X-Admin-Token` (`ADMIN_API_TOKEN`).

Módulos: `unidades`, `planos_admin`, `ferramentas`, `admin_store` (config/promoções).

No boot, `init_schema()` cria/migra tabelas de unidades, ferramentas e seed de `transferir_atendimento`.

## Testes

Precisam do PostgreSQL acessível. Rodam sem LLM (a interpretação é simulada) e também no CI, antes do build das imagens.

```powershell
# da pasta backend
python scripts/test_regressao_contexto.py
python scripts/test_interpretador.py
```

## Avaliação do interpretador (LLM real)

Mede o que o modelo configurado realmente devolve — os testes acima não medem isso. Usa a chave e o modelo do painel (Config IA).

```powershell
# casos-semente em eval/casos_interpretador.jsonl
python scripts/eval_interpretador.py rodar

# turnos reais do banco → eval/reais/turnos.jsonl (fora do Git: tem dados de clientes)
python scripts/eval_interpretador.py exportar --limite 500
python scripts/eval_interpretador.py rodar --casos eval/reais/turnos.jsonl
```

Em produção: `docker exec iavendas-api python scripts/eval_interpretador.py rodar`.

O relatório separa "LLM sozinho" de "LLM + parser". Quando um turno real sair errado, copie a linha para `eval/casos_interpretador.jsonl` com o campo `esperado` — vira caso permanente.

Cada turno grava em `turno_log_ia` o estado anterior (`estado_antes`), a resposta bruta do modelo (`interpretacao_llm`) e a `confianca`.

## Docker

Construído pelo `docker-compose.yml` na raiz (serviço `api`).
