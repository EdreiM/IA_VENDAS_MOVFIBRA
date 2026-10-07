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

`test_auditoria_interpretacao.py` é a auditoria do funil: 1.525 mensagens em todos os estados e 9 conversas completas, sempre com a interpretação correta do modelo, conferindo que as regras não estragam essa leitura (dado não gravado ou pedido de novo, conversa gravada como dado, objeção que avança, plano trocado, texto pedindo outro campo). Quando aparecer um erro novo em produção, acrescente a mensagem no banco correspondente desse arquivo. `--exportar` regrava `eval/casos_auditoria.jsonl` para medir o LLM real com esses mesmos casos.

`test_imports_internos.py` procura nome usado antes de um `import` feito dentro da mesma função, o que em produção vira `UnboundLocalError`.

`test_varredura_frases.py` passa frases comuns ("tá bom", "pera aí", "não entendi", "tá caro") por todos os estados do funil e falha se alguma for gravada como dado do cliente ou fizer o funil avançar. Ele bloqueia toda chamada HTTP: o `.env` local pode apontar para o n8n real, então qualquer simulação de fluxo fora das suítes deve fazer o mesmo.

## Respostas a dúvidas

A fonte das respostas é a **RAG** (webhook cadastrado em Config IA): cancelamento, multa, instalação e as informações da empresa ficam lá, não no código. Toda dúvida consulta a RAG, inclusive as de cancelamento e instalação.

A mensagem é escrita pelo LLM a cada pergunta (`response._responder_duvida`): ele recebe a pergunta, a conversa, o que a RAG devolveu e o próximo passo do atendimento. Responde só o que foi perguntado, não repete o que já explicou e termina retomando o atendimento com as próprias palavras. O código só confere se a mensagem retomou o atendimento e acrescenta o próximo passo se o LLM esqueceu.

Não existe texto pronto de regra comercial no código. Para mudar o que a Eva afirma sobre um assunto, altere o conteúdo da RAG. Se a RAG não trouxer a resposta, a Eva diz que prefere confirmar com a equipe. Com o LLM fora do ar, sai uma frase neutra seguida do próximo passo.

## Localização: bairro ou cidade

A lista de cidades atendidas fica em `app/localizacao_heuristica.py` (`CIDADES_ATENDIDAS_CANONICAS`). Quando o cliente manda um nome de lugar sozinho:

- cidade da lista → é a cidade; a Eva pede o bairro;
- bairro conhecido, ou o cliente escreveu "bairro" → é o bairro; a Eva pede a cidade;
- qualquer outro nome → a Eva pergunta "*X* é o seu bairro?" (`aguardando=confirmar_local`). Se for, guarda como bairro e pede a cidade; se o cliente disser que é a cidade, ela está fora da área e a Eva informa as cidades atendidas.

Assim um nome solto nunca é gravado como cidade só porque o modelo chutou.

## Endereço: rua, número e complemento

No endereço escrito de uma vez ("sérgio henn, 891 residencial plácido"), a posição decide: o que vem antes do número é a rua, o que vem depois é o complemento (`parser._separar_endereco`). Isso vale mesmo quando o modelo devolve os dois trocados. O complemento aparece no resumo de confirmação. Número que faz parte do nome ("rua 7", "travessa 15 de agosto") não é tomado como número da casa, e "sem número" / "s/n" fica registrado como `S/N`.

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
