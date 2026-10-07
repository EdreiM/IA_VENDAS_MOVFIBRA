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
python scripts/test_conversa_natural.py
python scripts/test_transcricao.py
```

`test_conversa_natural.py` cobre a conversa no meio do funil (seção abaixo): pedido de tempo, "não tenho esse dado", objeção de preço, áudio, quem já é cliente, alteração depois do cadastro, reenvio dos termos, transferência quando trava e cliente que volta depois do encerramento.

`test_auditoria_interpretacao.py` é a auditoria do funil: 1.525 mensagens em todos os estados e 9 conversas completas, sempre com a interpretação correta do modelo, conferindo que as regras não estragam essa leitura (dado não gravado ou pedido de novo, conversa gravada como dado, objeção que avança, plano trocado, texto pedindo outro campo). Quando aparecer um erro novo em produção, acrescente a mensagem no banco correspondente desse arquivo. `--exportar` regrava `eval/casos_auditoria.jsonl` para medir o LLM real com esses mesmos casos.

`test_imports_internos.py` procura nome usado antes de um `import` feito dentro da mesma função, o que em produção vira `UnboundLocalError`.

`test_varredura_frases.py` passa frases comuns ("tá bom", "pera aí", "não entendi", "tá caro") por todos os estados do funil e falha se alguma for gravada como dado do cliente ou fizer o funil avançar. Ele bloqueia toda chamada HTTP: o `.env` local pode apontar para o n8n real, então qualquer simulação de fluxo fora das suítes deve fazer o mesmo.

## Respostas a dúvidas

A fonte das respostas é a **RAG** (webhook cadastrado em Config IA): cancelamento, multa, instalação e as informações da empresa ficam lá, não no código. Toda dúvida consulta a RAG, inclusive as de cancelamento e instalação.

A mensagem é escrita pelo LLM a cada pergunta (`response._responder_duvida`): ele recebe a pergunta, a conversa, o que a RAG devolveu e o próximo passo do atendimento. Responde só o que foi perguntado, não repete o que já explicou e termina retomando o atendimento com as próprias palavras. O código só confere se a mensagem retomou o atendimento e acrescenta o próximo passo se o LLM esqueceu.

Não existe texto pronto de regra comercial no código. Para mudar o que a Eva afirma sobre um assunto, altere o conteúdo da RAG. Se a RAG não trouxer a resposta, a Eva diz que prefere confirmar com a equipe. Com o LLM fora do ar, sai uma frase neutra seguida do próximo passo.

## Conversa no meio do funil

A máquina de estados decide o funil; `app/conversa.py` cuida do que fazer quando o cliente responde outra coisa no lugar do passo pedido. Em vez de repetir a mesma frase, a Eva responde ao que ele disse (`response._conversar`, escrito pelo LLM) e conduz de volta.

O interpretador devolve dois campos a mais: `situacao` e `nota`. As regras de `conversa.classificar` cobrem o que o modelo deixar em branco.

| Situação | Exemplo | O que a Eva faz |
|---|---|---|
| `ESPERA` | "pera aí", "já mando", um "ok" depois de um pedido de dado | Diz que aguarda. Não conta como tentativa. |
| `ADIAMENTO` | "vou pensar", "depois eu vejo" | Acolhe sem pressionar. Não conta como tentativa. |
| `IMPEDIMENTO` | "não tenho e-mail", "não sei meu CEP" | Ajuda com um caminho prático. Conta 2. |
| `OBJECAO_PRECO` | "tá caro", "a concorrente faz por 99" | Responde com os fatos do plano, da RAG e os planos mais em conta do catálogo. Conta 1. |
| `NAO_ENTENDEU` | "não entendi", "como assim?" | Explica de outro jeito. Conta 1. |
| `MIDIA` | imagem ou arquivo sem texto, ou áudio que não deu para transcrever (`[audio]`) | Avisa que não conseguiu ouvir/abrir e pede para escrever. Conta 1. |
| `SUPORTE` | "minha internet caiu, já sou cliente", "segunda via do boleto" | Transfere para a equipe na hora. |
| (nenhuma) | "kkk", comentário solto | Responde em uma frase e retoma. Conta 1. |

- **Transferência por travar:** as tentativas sem avanço no mesmo passo são somadas em `tentativas_travadas`; ao chegar em 4 (`conversa.LIMITE_TRAVADO`) a Eva chama uma pessoa da equipe, com o motivo na nota do Chatwoot. Qualquer avanço zera a soma. Recusar os horários oferecidos conta 2.
- **Depois do cadastro concluído:** pedido de alterar dado ou plano transfere direto (antes a Eva perguntava "posso te encaminhar?" e o "sim" era lido como aceite dos termos).
- **Termos:** "não recebi" / "não abriu o PDF" reenvia os termos; na segunda vez, transfere.
- **Cliente que volta depois de `finalizado`:** venda concluída → volta para as dúvidas do pós-venda; encerrado por inatividade → continua do passo em que estava (`retorno_estado`); encerrado sem venda e sem ponto de retomada → atendimento novo, com o histórico mantido. Agradecimento solto continua sendo só a cortesia. `transferido` segue em silêncio.
- **Notas da conversa:** fatos que o cliente contou ("só pode receber o técnico à tarde") ficam em `notas_conversa` e entram nos prompts do interpretador e das respostas, mesmo depois de saírem do histórico recente.
- **Sem LLM:** `_conversar` devolve vazio e sai o texto fixo de sempre.

As orientações de `_GUIA_SITUACAO` dizem como conversar; não trazem regra comercial. Os fatos continuam vindo do catálogo de planos e da RAG.

## Áudio do cliente

Áudio que chega pelo Chatwoot é transcrito antes de a Eva interpretar (`app/transcricao.py`): o anexo (`data_url`) é baixado e enviado à API de transcrição com a chave de **Config IA → API Key transcrição de áudio**. Chave `gsk_…` usa o Whisper da Groq (`whisper-large-v3-turbo`); as demais usam a OpenAI (`whisper-1`). O texto transcrito entra no atendimento como se o cliente tivesse digitado, e é ele que aparece no histórico.

Sem chave, com falha na API, áudio mudo ou maior que 20 MB, a mensagem segue como `[audio]` e a Eva pede para o cliente escrever (situação `MIDIA`). Conversa já transferida para a equipe não é transcrita. Os turnos ficam marcados com `audio_transcrito` ou `audio_nao_transcrito` nos Pontos de atenção.

`scripts/test_transcricao.py` cobre esse fluxo sem rede.

## Pontos de atenção (medição)

Cada turno grava em `turno_log_ia.sinais` o que aconteceu (`travado`, `impedimento`, `objecao_preco`, `midia`, `sem_base`, `suporte`, `transferido_por_travar`, `voltou_apos_encerrar`...). `GET /metrics/atencao?dias=7` resume por tipo e por passo do funil e lista os turnos; a aba **Pontos de atenção** do painel mostra isso.

Quando a Eva responde que vai confirmar com a equipe (a RAG não trouxe a resposta, ou o modelo abriu a mensagem com a marca `[SEM_BASE]`, que é apagada antes do envio), a pergunta entra em `perguntas_sem_resposta_ia`, aparece na mesma aba e vira nota privada na conversa do Chatwoot. Depois de incluir a resposta na RAG, marque como resolvida (`POST /admin/perguntas-sem-resposta/{id}/resolver`).

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
