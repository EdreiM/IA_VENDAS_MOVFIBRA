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
python scripts/test_varredura_frases.py
python scripts/test_auditoria_interpretacao.py
python scripts/test_imports_internos.py
```

`test_auditoria_interpretacao.py` é a auditoria do funil: 1.490 mensagens em todos os estados e 4 conversas completas, sempre com a interpretação correta do modelo, conferindo que as regras não estragam essa leitura (dado não gravado ou pedido de novo, conversa gravada como dado, objeção que avança, plano trocado, texto pedindo outro campo). Quando aparecer um erro novo em produção, acrescente a mensagem no banco correspondente desse arquivo. `--exportar` regrava `eval/casos_auditoria.jsonl` para medir o LLM real com esses mesmos casos.

`test_imports_internos.py` procura nome usado antes de um `import` feito dentro da mesma função, o que em produção vira `UnboundLocalError`.

`test_varredura_frases.py` passa frases comuns ("tá bom", "pera aí", "não entendi", "tá caro") por todos os estados do funil e falha se alguma for gravada como dado do cliente ou fizer o funil avançar. Ele bloqueia toda chamada HTTP: o `.env` local pode apontar para o n8n real, então qualquer simulação de fluxo fora das suítes deve fazer o mesmo.

## Respostas a dúvidas

A fonte das respostas é a **RAG** (webhook cadastrado em Config IA): cancelamento, multa, instalação e as informações da empresa ficam lá, não no código. Toda dúvida consulta a RAG, inclusive as de cancelamento e instalação.

A resposta é escrita pelo LLM a cada pergunta (`response._resposta_inteligente`): ele recebe a pergunta, a conversa e o que a RAG devolveu, responde só o que foi perguntado e não repete o que já explicou. A continuação do atendimento (pedir o próximo dado, o aceite) é acrescentada pelo código, sempre igual.

Para mudar o que a Eva afirma sobre um assunto, altere o conteúdo da RAG. Os textos fixos antigos só entram como reserva: quando o LLM falha, ou quando a RAG não devolve nada sobre cancelamento/instalação.

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
