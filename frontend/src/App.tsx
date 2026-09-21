import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Conversa,
  Ferramenta,
  FerramentaParam,
  Funil,
  Plano,
  Promocao,
  Resumo,
  Unidade,
  createFerramenta,
  createPlano,
  createUnidade,
  deleteFerramenta,
  deletePlano,
  deletePromocao,
  fetchAgents,
  fetchConfigIa,
  saveConfigIa,
  fetchConversas,
  fetchFerramentas,
  syncCatalogoFerramentas,
  fetchFunil,
  fetchHealth,
  fetchLabels,
  fetchPlanos,
  fetchPromocoes,
  fetchResumo,
  fetchTeams,
  fetchTurnos,
  fetchUnidades,
  getAdminToken,
  postHandoff,
  postChat,
  postReset,
  setAdminToken,
  setPlanoInicial,
  updateFerramenta,
  updatePlano,
  uploadPlanoImagem,
  upsertPromocao,
} from "./api";

type Tab =
  | "chat"
  | "metricas"
  | "conversas"
  | "planos"
  | "promocoes"
  | "config"
  | "ferramentas"
  | "unidades";

type Option = { id: number; label: string };

type ChatMsg = {
  who: "cliente" | "eva" | "sistema";
  text: string;
  meta?: string;
  imageUrl?: string;
};

const GUIA_TESTE: { titulo: string; dica: string; msgs: string[] }[] = [
  {
    titulo: "1. Abertura",
    dica: "Veja se ela se apresenta como Eva e pede cidade/bairro.",
    msgs: ["Oi", "Quem é você?"],
  },
  {
    titulo: "2. Localização",
    dica: "Informe cidade e bairro (cobertura mock/IXC conforme .env).",
    msgs: ["Santarém, Centro", "Belém, Batista Campos"],
  },
  {
    titulo: "3. Planos",
    dica: "Peça lista, detalhes ou escolha um plano.",
    msgs: ["Quero ver os planos", "Quais os benefícios?", "Quero esse"],
  },
  {
    titulo: "4. Cadastro",
    dica: "Depois de confirmar o plano, envie os dados um a um.",
    msgs: [
      "Maria Silva",
      "12345678909",
      "maria@teste.com",
      "93992219098",
      "01/01/1990",
    ],
  },
  {
    titulo: "5. Transferência",
    dica: "Testa handoff / ferramenta transferir_atendimento.",
    msgs: ["Quero falar com um humano", "Me passa pra um atendente"],
  },
];

function asList(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    if (Array.isArray(o.payload)) return o.payload;
    if (Array.isArray(o.data)) return o.data;
  }
  return [];
}

function mapAgents(raw: unknown): Option[] {
  return asList(raw)
    .map((item) => {
      const a = item as Record<string, unknown>;
      const id = Number(a.id);
      if (!Number.isFinite(id)) return null;
      const name = String(a.name || a.available_name || a.email || `Agent ${id}`);
      return { id, label: name };
    })
    .filter(Boolean) as Option[];
}

function mapTeams(raw: unknown): Option[] {
  return asList(raw)
    .map((item) => {
      const t = item as Record<string, unknown>;
      const id = Number(t.id);
      if (!Number.isFinite(id)) return null;
      return { id, label: String(t.name || `Team ${id}`) };
    })
    .filter(Boolean) as Option[];
}

function mapLabelTitles(raw: unknown): string[] {
  return asList(raw)
    .map((item) => {
      if (typeof item === "string") return item;
      const l = item as Record<string, unknown>;
      return String(l.title || l.name || "").trim();
    })
    .filter(Boolean);
}

function statusBadge(status?: string) {
  const s = status || "com_ia";
  const label =
    s === "transferido" ? "Transferido" : s === "finalizado" ? "Finalizado" : "Com IA";
  return <span className={`badge badge-${s}`}>{label}</span>;
}

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "Chat teste" },
  { id: "metricas", label: "Métricas" },
  { id: "conversas", label: "Conversas" },
  { id: "planos", label: "Planos" },
  { id: "promocoes", label: "Promoções" },
  { id: "config", label: "Config IA" },
  { id: "ferramentas", label: "Ferramentas" },
  { id: "unidades", label: "Unidades" },
];

const emptyTool = (): Omit<Ferramenta, "id" | "chamadas_sucesso"> => ({
  tool_key: "",
  nome: "",
  descricao: "",
  webhook_url: "",
  integracao: "global",
  unidade_id: null,
  destaque_dashboard: false,
  ativo: true,
  parametros: [],
});

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [tokenInput, setTokenInput] = useState(getAdminToken());
  const [unidades, setUnidades] = useState<Unidade[]>([]);
  const [unidadeFiltro, setUnidadeFiltro] = useState<number | "">("");
  const [error, setError] = useState("");
  const [okMsg, setOkMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [apiOk, setApiOk] = useState<boolean | null>(null);

  const [chatId, setChatId] = useState("teste-local");
  const [chatConversationId, setChatConversationId] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatMsgs, setChatMsgs] = useState<ChatMsg[]>([
    {
      who: "sistema",
      text: "Guia de teste da Eva. Use as sugestões à direita ou digite livremente. Reinicie a conversa antes de um fluxo novo.",
    },
  ]);
  const [chatEstado, setChatEstado] = useState<string>("—");

  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [funil, setFunil] = useState<Funil | null>(null);
  const [conversas, setConversas] = useState<Conversa[]>([]);
  const [statusFiltro, setStatusFiltro] = useState("");
  const [sel, setSel] = useState<Conversa | null>(null);
  const [turnos, setTurnos] = useState<unknown[]>([]);
  const [agents, setAgents] = useState<Option[]>([]);
  const [teams, setTeams] = useState<Option[]>([]);
  const [labelOptions, setLabelOptions] = useState<string[]>([]);
  const [assigneeId, setAssigneeId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [labelsCsv, setLabelsCsv] = useState("sofia_transferido");
  const [statusHandoff, setStatusHandoff] = useState("open");

  const [planos, setPlanos] = useState<Plano[]>([]);
  const [planoForm, setPlanoForm] = useState<Partial<Plano>>({
    nome: "",
    valor: 0,
    ativo: true,
    ordem: 100,
    imagem_url: "",
  });
  const [editPlanoId, setEditPlanoId] = useState<number | null>(null);
  const [planoImagemFile, setPlanoImagemFile] = useState<File | null>(null);
  const [planoImagemPreview, setPlanoImagemPreview] = useState("");

  const [promos, setPromos] = useState<Promocao[]>([]);
  const [promoForm, setPromoForm] = useState<Partial<Promocao>>({
    codigo: "",
    titulo: "",
    descricao: "",
    ativo: true,
  });

  const [iaForm, setIaForm] = useState({
    nome_ia: "Eva",
    tom_voz: "Calorosa, simpática, objetiva",
    pode_emoji: true,
    llm_provider: "openai",
    openai_model: "gpt-4.1-mini",
    llm_temperature: 0.3,
    openai_api_key: "",
    transcription_api_key: "",
    rag_provider: "webhook",
    rag_webhook_url: "",
    rag_webhook_token: "",
  });
  const [iaMasks, setIaMasks] = useState({
    openai: "",
    transcription: "",
    rag_token: "",
  });

  const [tools, setTools] = useState<Ferramenta[]>([]);
  const [toolForm, setToolForm] = useState(emptyTool());
  const [editToolId, setEditToolId] = useState<number | null>(null);

  const [novaUnidade, setNovaUnidade] = useState({ codigo: "", nome: "" });

  const uid = unidadeFiltro === "" ? undefined : Number(unidadeFiltro);

  const saveToken = (e: FormEvent) => {
    e.preventDefault();
    setAdminToken(tokenInput.trim());
    setOkMsg("Token salvo");
    void refreshAll();
  };

  const refreshUnidades = useCallback(async () => {
    const u = await fetchUnidades();
    setUnidades(u.items || []);
  }, []);

  const refreshMetrics = useCallback(async () => {
    const [r, f] = await Promise.all([fetchResumo(), fetchFunil()]);
    setResumo(r);
    setFunil(f);
  }, []);

  const refreshConversas = useCallback(async () => {
    const c = await fetchConversas(60, {
      unidade_id: uid,
      status: statusFiltro || undefined,
    });
    setConversas(c.items || []);
  }, [uid, statusFiltro]);

  const refreshPlanos = useCallback(async () => {
    const p = await fetchPlanos(uid);
    setPlanos(p.items || []);
  }, [uid]);

  const refreshPromos = useCallback(async () => {
    const p = await fetchPromocoes(uid);
    setPromos(p.items || []);
  }, [uid]);

  const refreshConfig = useCallback(async () => {
    const c = await fetchConfigIa(uid);
    setIaForm({
      nome_ia: c.nome_ia || "Eva",
      tom_voz: c.tom_voz || "",
      pode_emoji: !!c.pode_emoji,
      llm_provider: c.llm_provider || "openai",
      openai_model: c.openai_model || "gpt-4.1-mini",
      llm_temperature: Number(c.llm_temperature ?? 0.3),
      openai_api_key: "",
      transcription_api_key: "",
      rag_provider: c.rag_provider || "webhook",
      rag_webhook_url: c.rag_webhook_url || "",
      rag_webhook_token: "",
    });
    setIaMasks({
      openai: c.openai_api_key_mask || "",
      transcription: c.transcription_api_key_mask || "",
      rag_token: c.rag_webhook_token_mask || "",
    });
  }, [uid]);

  const refreshTools = useCallback(async () => {
    try {
      const synced = await syncCatalogoFerramentas();
      setTools(synced.items || []);
    } catch {
      const t = await fetchFerramentas(uid);
      setTools(t.items || []);
    }
  }, [uid]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const h = await fetchHealth();
      setApiOk(!!h.ok);
      await refreshUnidades();
      if (tab === "chat") {
        /* só health + token — chat é interativo */
      }
      if (tab === "metricas") await refreshMetrics();
      if (tab === "conversas") {
        await refreshConversas();
        const [a, t, l] = await Promise.all([fetchAgents(), fetchTeams(), fetchLabels()]);
        setAgents(mapAgents(a.data));
        setTeams(mapTeams(t.data));
        setLabelOptions(mapLabelTitles(l.data));
      }
      if (tab === "planos") await refreshPlanos();
      if (tab === "promocoes") await refreshPromos();
      if (tab === "config") await refreshConfig();
      if (tab === "ferramentas") await refreshTools();
    } catch (err) {
      setApiOk(false);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [
    tab,
    refreshUnidades,
    refreshMetrics,
    refreshConversas,
    refreshPlanos,
    refreshPromos,
    refreshConfig,
    refreshTools,
  ]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const maxFunil = useMemo(
    () => Math.max(1, ...(funil?.etapas.map((e) => e.quantidade) || [1])),
    [funil],
  );

  async function onSelectConversa(c: Conversa) {
    setSel(c);
    try {
      const t = await fetchTurnos(c.id_cliente);
      setTurnos(t.items || []);
    } catch {
      setTurnos([]);
    }
  }

  async function doHandoff() {
    if (!sel?.conversation_id) {
      setError("Conversa sem conversation_id");
      return;
    }
    setError("");
    try {
      await postHandoff({
        conversation_id: String(sel.conversation_id),
        assignee_id: assigneeId ? Number(assigneeId) : null,
        team_id: teamId ? Number(teamId) : null,
        labels: labelsCsv.split(",").map((x) => x.trim()).filter(Boolean),
        status: statusHandoff,
        motivo: "Painel Eva",
      });
      setOkMsg("Handoff enviado");
      await refreshConversas();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function savePlano(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const body = {
        ...planoForm,
        valor: Number(planoForm.valor || 0),
        unidade_id: planoForm.unidade_id ?? uid ?? null,
        imagem_url: planoForm.imagem_url || "",
      };
      let saved: Plano;
      if (editPlanoId) saved = await updatePlano(editPlanoId, body);
      else saved = await createPlano(body);
      if (planoImagemFile) {
        saved = await uploadPlanoImagem(saved.id, planoImagemFile);
      }
      setEditPlanoId(null);
      setPlanoForm({ nome: "", valor: 0, ativo: true, ordem: 100, imagem_url: "" });
      setPlanoImagemFile(null);
      setPlanoImagemPreview("");
      setOkMsg("Plano salvo");
      await refreshPlanos();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function savePromo(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await upsertPromocao({
        ...promoForm,
        codigo: String(promoForm.codigo || ""),
        unidade_id: promoForm.unidade_id ?? uid ?? null,
      } as Promocao & { codigo: string });
      setPromoForm({ codigo: "", titulo: "", descricao: "", ativo: true });
      setOkMsg("Promoção salva");
      await refreshPromos();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveConfig(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const saved = await saveConfigIa({
        ...iaForm,
        unidade_id: uid ?? null,
      });
      setIaForm((f) => ({
        ...f,
        openai_api_key: "",
        transcription_api_key: "",
        rag_webhook_token: "",
        nome_ia: saved.nome_ia,
        tom_voz: saved.tom_voz,
        pode_emoji: saved.pode_emoji,
        llm_provider: saved.llm_provider,
        openai_model: saved.openai_model,
        llm_temperature: Number(saved.llm_temperature ?? 0.3),
        rag_provider: saved.rag_provider || "webhook",
        rag_webhook_url: saved.rag_webhook_url || "",
      }));
      setIaMasks({
        openai: saved.openai_api_key_mask || "",
        transcription: saved.transcription_api_key_mask || "",
        rag_token: saved.rag_webhook_token_mask || "",
      });
      setOkMsg("Configuração IA salva");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function addParam() {
    setToolForm((f) => ({
      ...f,
      parametros: [
        ...f.parametros,
        { nome: "", tipo: "texto", descricao: "", obrigatorio: false, ordem: f.parametros.length },
      ],
    }));
  }

  function updateParam(i: number, patch: Partial<FerramentaParam>) {
    setToolForm((f) => ({
      ...f,
      parametros: f.parametros.map((p, idx) => (idx === i ? { ...p, ...patch } : p)),
    }));
  }

  function removeParam(i: number) {
    setToolForm((f) => ({
      ...f,
      parametros: f.parametros.filter((_, idx) => idx !== i),
    }));
  }

  async function saveTool(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const body = {
        ...toolForm,
        unidade_id: toolForm.integracao === "unidade" ? toolForm.unidade_id ?? uid ?? null : null,
      };
      if (editToolId) await updateFerramenta(editToolId, body);
      else await createFerramenta(body);
      setEditToolId(null);
      setToolForm(emptyTool());
      setOkMsg("Ferramenta salva");
      await refreshTools();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function editTool(t: Ferramenta) {
    setEditToolId(t.id);
    setToolForm({
      tool_key: t.tool_key,
      nome: t.nome,
      descricao: t.descricao,
      webhook_url: t.webhook_url,
      integracao: t.integracao || (t.unidade_id ? "unidade" : "global"),
      unidade_id: t.unidade_id,
      destaque_dashboard: t.destaque_dashboard,
      ativo: t.ativo,
      parametros: t.parametros || [],
    });
  }

  async function saveUnidade(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await createUnidade({ ...novaUnidade, ativo: true });
      setNovaUnidade({ codigo: "", nome: "" });
      setOkMsg("Unidade criada");
      await refreshUnidades();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function enviarChat(texto?: string) {
    const mensagem = (texto ?? chatInput).trim();
    if (!mensagem || chatBusy) return;
    setChatInput("");
    setError("");
    setChatMsgs((m) => [...m, { who: "cliente", text: mensagem }]);
    setChatBusy(true);
    try {
      const r = await postChat({
        mensagem,
        id_cliente: chatId.trim() || "teste-local",
        conversation_id: chatConversationId.trim() || undefined,
        buffer: false,
      });
      const bolhas =
        r.outputs && r.outputs.length > 0
          ? r.outputs.filter((b) => String(b).trim())
          : r.resposta
            ? [r.resposta]
            : ["(sem resposta)"];
      const fase = r.estado?.fase || "—";
      const aguardando = r.estado?.aguardando || "—";
      const acao = r.decisao?.acao || "";
      setChatEstado(`${fase} · aguardando=${aguardando}${acao ? ` · ${acao}` : ""}`);
      const imgs = (r.imagens || []).filter((i) => i?.url);
      const imgsUniq = imgs.filter(
        (img, idx, arr) => arr.findIndex((x) => x.url === img.url) === idx,
      );
      setChatMsgs((m) => [
        ...m,
        ...imgsUniq.map((img) => ({
          who: "eva" as const,
          text: img.plano_nome ? `Imagem: ${img.plano_nome}` : "Imagem do plano",
          imageUrl: img.url,
        })),
        ...bolhas.map((b, i) => ({
          who: "eva" as const,
          text: String(b),
          meta: i === bolhas.length - 1 ? `fase=${fase} · aguardando=${aguardando}` : undefined,
        })),
      ]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setChatMsgs((m) => [...m, { who: "sistema", text: `Erro: ${msg}` }]);
    } finally {
      setChatBusy(false);
    }
  }

  async function reiniciarChat() {
    setError("");
    try {
      await postReset(chatId.trim() || "teste-local");
      setChatMsgs([
        {
          who: "sistema",
          text: `Conversa reiniciada para ${chatId.trim() || "teste-local"}. Pode mandar um oi.`,
        },
      ]);
      setChatEstado("inicio");
      setOkMsg("Chat reiniciado");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">E</span>
          <div>
            <strong>Eva</strong>
            <small>Painel operacional MOV</small>
          </div>
        </div>
        <nav>
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? "nav-item active" : "nav-item"}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className={apiOk ? "dot ok" : apiOk === false ? "dot bad" : "dot"} />
          API {apiOk ? "online" : apiOk === false ? "offline" : "…"}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <form className="token-row" onSubmit={saveToken}>
            <input
              type="password"
              placeholder="ADMIN_API_TOKEN"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
            />
            <button type="submit">Salvar token</button>
          </form>
          <div className="top-filters">
            <label>
              Unidade
              <select
                value={unidadeFiltro}
                onChange={(e) =>
                  setUnidadeFiltro(e.target.value === "" ? "" : Number(e.target.value))
                }
              >
                <option value="">Todas / global</option>
                {unidades.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.nome}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="ghost" onClick={() => void refreshAll()} disabled={loading}>
              {loading ? "Atualizando…" : "Atualizar"}
            </button>
          </div>
        </header>

        {error ? <div className="alert bad">{error}</div> : null}
        {okMsg ? (
          <div className="alert ok" onClick={() => setOkMsg("")}>
            {okMsg}
          </div>
        ) : null}

        {tab === "chat" && (
          <section className="panel chat-panel">
            <div className="chat-layout">
              <div className="chat-main">
                <div className="row-head">
                  <div>
                    <h1>Chat de testes</h1>
                    <p className="muted" style={{ margin: 0 }}>
                      Converse com a Eva como se fosse o cliente no WhatsApp.
                    </p>
                  </div>
                  <div className="chat-toolbar">
                    <label className="chat-id">
                      id_cliente
                      <input
                        value={chatId}
                        onChange={(e) => setChatId(e.target.value)}
                        placeholder="teste-local"
                      />
                    </label>
                    <label className="chat-id">
                      conversation_id
                      <input
                        value={chatConversationId}
                        onChange={(e) => setChatConversationId(e.target.value)}
                        placeholder="2969 (Chatwoot)"
                        title="Obrigatório para enviar termos/áudio via n8n"
                      />
                    </label>
                    <button type="button" className="ghost" onClick={() => void reiniciarChat()}>
                      Reiniciar
                    </button>
                  </div>
                </div>
                <div className="chat-estado">Estado: {chatEstado}</div>
                <div className="chat-log">
                  {chatMsgs.map((m, i) => (
                    <div key={i} className={`chat-bubble ${m.who}`}>
                      {m.who === "cliente" ? (
                        <div className="chat-label">CUSTOMER</div>
                      ) : m.who === "eva" ? (
                        <div className="chat-label">AI</div>
                      ) : null}
                      <div className="chat-text">{m.text}</div>
                      {m.imageUrl ? (
                        <img className="chat-plano-img" src={m.imageUrl} alt={m.text || "Plano"} />
                      ) : null}
                      {m.meta ? <div className="chat-meta">{m.meta}</div> : null}
                    </div>
                  ))}
                  {chatBusy ? (
                    <div className="chat-bubble eva typing">
                      <div className="chat-label">AI</div>
                      <div className="chat-text">digitando…</div>
                    </div>
                  ) : null}
                </div>
                <form
                  className="chat-compose"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void enviarChat();
                  }}
                >
                  <input
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder="Digite como o cliente…"
                    disabled={chatBusy}
                    autoComplete="off"
                  />
                  <button type="submit" disabled={chatBusy || !chatInput.trim()}>
                    Enviar
                  </button>
                </form>
              </div>

              <aside className="chat-guide">
                <h2>Guia rápido</h2>
                <p className="muted">
                  Siga a ordem do funil. Clique numa frase para enviar. Reinicie entre cenários.
                </p>
                {GUIA_TESTE.map((bloco) => (
                  <div className="guide-block" key={bloco.titulo}>
                    <strong>{bloco.titulo}</strong>
                    <small>{bloco.dica}</small>
                    <div className="guide-chips">
                      {bloco.msgs.map((msg) => (
                        <button
                          key={msg}
                          type="button"
                          className="chip"
                          disabled={chatBusy}
                          onClick={() => void enviarChat(msg)}
                        >
                          {msg}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                <div className="guide-block">
                  <strong>Dica</strong>
                  <small>
                    Preencha <code>conversation_id</code> (Chatwoot) para testar cadastro, termos e
                    agendamento via n8n. Com cobertura em mock, qualquer cidade/bairro costuma passar.
                  </small>
                </div>
              </aside>
            </div>
          </section>
        )}

        {tab === "metricas" && (
          <section className="panel">
            <h1>Métricas</h1>
            <p className="muted">Visão do funil e desempenho operacional.</p>
            <div className="cards">
              <div className="stat">
                <span>Conversas</span>
                <strong>{resumo?.conversas ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Com IA</span>
                <strong>{resumo?.com_ia ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Transferidos</span>
                <strong>{resumo?.transferidos_humano ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Agendamentos</span>
                <strong>{resumo?.agendamentos_confirmados ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Cobertura</span>
                <strong>{resumo?.com_cobertura ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Mensagens</span>
                <strong>{resumo?.mensagens ?? "—"}</strong>
              </div>
            </div>
            {(resumo?.ferramentas_destaque || []).length > 0 && (
              <div className="cards tools-stats">
                {resumo!.ferramentas_destaque!.map((f) => (
                  <div className="stat" key={f.id}>
                    <span>{f.nome}</span>
                    <strong>{f.chamadas_sucesso}</strong>
                    <small>sucessos</small>
                  </div>
                ))}
              </div>
            )}
            <h2>Funil</h2>
            <div className="funil">
              {(funil?.etapas || []).map((e) => (
                <div key={e.fase} className="funil-row">
                  <span>{e.fase}</span>
                  <div className="bar-wrap">
                    <div
                      className="bar"
                      style={{ width: `${Math.round((e.quantidade / maxFunil) * 100)}%` }}
                    />
                  </div>
                  <strong>{e.quantidade}</strong>
                </div>
              ))}
            </div>
          </section>
        )}

        {tab === "conversas" && (
          <section className="panel split">
            <div>
              <div className="row-head">
                <h1>Conversas</h1>
                <select value={statusFiltro} onChange={(e) => setStatusFiltro(e.target.value)}>
                  <option value="">Todos status</option>
                  <option value="com_ia">Com IA</option>
                  <option value="transferido">Transferido</option>
                  <option value="finalizado">Finalizado</option>
                </select>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Cliente</th>
                      <th>Status</th>
                      <th>Fase</th>
                      <th>Cidade</th>
                      <th>Atualizado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {conversas.map((c) => (
                      <tr
                        key={c.id_cliente}
                        className={sel?.id_cliente === c.id_cliente ? "selected" : ""}
                        onClick={() => void onSelectConversa(c)}
                      >
                        <td>
                          <div>{c.nome || c.id_cliente}</div>
                          <small>{c.telefone || c.conversation_id || "—"}</small>
                        </td>
                        <td>{statusBadge(c.status)}</td>
                        <td>{c.fase}</td>
                        <td>{c.cidade || "—"}</td>
                        <td>
                          <small>{c.updated_at ? new Date(c.updated_at).toLocaleString() : "—"}</small>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <aside className="detail">
              <h2>Detalhe</h2>
              {!sel ? (
                <p className="muted">Selecione uma conversa.</p>
              ) : (
                <>
                  <p>
                    <strong>{sel.nome || sel.id_cliente}</strong>
                    <br />
                    {statusBadge(sel.status)} · {sel.fase}
                  </p>
                  <p className="muted">
                    Plano: {sel.plano_confirmado || "—"}
                    <br />
                    CID: {sel.conversation_id || "—"}
                  </p>
                  <h3>Handoff</h3>
                  <label>
                    Atendente
                    <select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
                      <option value="">—</option>
                      {agents.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Time
                    <select value={teamId} onChange={(e) => setTeamId(e.target.value)}>
                      <option value="">—</option>
                      {teams.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Labels
                    <input
                      value={labelsCsv}
                      onChange={(e) => setLabelsCsv(e.target.value)}
                      list="labels-dl"
                    />
                    <datalist id="labels-dl">
                      {labelOptions.map((l) => (
                        <option key={l} value={l} />
                      ))}
                    </datalist>
                  </label>
                  <label>
                    Status
                    <select value={statusHandoff} onChange={(e) => setStatusHandoff(e.target.value)}>
                      <option value="open">open</option>
                      <option value="pending">pending</option>
                      <option value="resolved">resolved</option>
                    </select>
                  </label>
                  <button type="button" onClick={() => void doHandoff()}>
                    Transferir agora
                  </button>
                  <h3>Turnos recentes</h3>
                  <ul className="turnos">
                    {turnos.slice(0, 8).map((t, i) => {
                      const row = t as Record<string, unknown>;
                      return (
                        <li key={i}>
                          <small>
                            {String(row.acao || row.fase || "")} —{" "}
                            {String(row.created_at || "").slice(0, 19)}
                          </small>
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
            </aside>
          </section>
        )}

        {tab === "planos" && (
          <section className="panel">
            <h1>Planos</h1>
            <p className="muted">
              Catálogo da Eva · a IA usa estes planos (não o webhook). Marque o plano inicial.
            </p>
            <form className="form-grid" onSubmit={savePlano}>
              <label>
                Nome
                <input
                  required
                  value={planoForm.nome || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, nome: e.target.value })}
                />
              </label>
              <label>
                Valor (R$)
                <input
                  type="number"
                  step="0.01"
                  required
                  value={planoForm.valor ?? 0}
                  onChange={(e) => setPlanoForm({ ...planoForm, valor: Number(e.target.value) })}
                />
              </label>
              <label>
                Valor pontualidade (opcional)
                <input
                  type="number"
                  step="0.01"
                  value={planoForm.valor_pontualidade ?? ""}
                  onChange={(e) =>
                    setPlanoForm({
                      ...planoForm,
                      valor_pontualidade: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                  placeholder="Ex: 119"
                />
              </label>
              <label>
                Velocidade
                <input
                  value={planoForm.velocidade || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, velocidade: e.target.value })}
                />
              </label>
              <label>
                Modalidade
                <input
                  value={planoForm.modalidade || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, modalidade: e.target.value })}
                />
              </label>
              <label className="span2">
                Imagem do plano (PNG)
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"
                  onChange={(e) => {
                    const f = e.target.files?.[0] || null;
                    setPlanoImagemFile(f);
                    if (f) setPlanoImagemPreview(URL.createObjectURL(f));
                    else setPlanoImagemPreview("");
                  }}
                />
                <small className="field-hint">
                  Envie um PNG (ou JPG/WEBP). A imagem fica salva na plataforma — sem link externo.
                </small>
                {(planoImagemPreview || planoForm.imagem_url) && (
                  <img
                    className="plano-thumb"
                    src={planoImagemPreview || planoForm.imagem_url || ""}
                    alt="Prévia do plano"
                  />
                )}
              </label>
              <label className="span2">
                Descrição (texto que a IA apresenta)
                <textarea
                  value={planoForm.descricao || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, descricao: e.target.value })}
                  rows={6}
                  placeholder="Texto comercial completo com ✅ benefícios…"
                />
              </label>
              <label className="span2">
                Benefícios (checklist; um por linha)
                <textarea
                  value={planoForm.beneficios || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, beneficios: e.target.value })}
                  rows={4}
                />
              </label>
              <label className="span2">
                Condição pontualidade
                <input
                  value={planoForm.condicao_valor_pontualidade || ""}
                  onChange={(e) =>
                    setPlanoForm({ ...planoForm, condicao_valor_pontualidade: e.target.value })
                  }
                  placeholder="Pagando até o vencimento…"
                />
              </label>
              <label>
                Ordem
                <input
                  type="number"
                  value={planoForm.ordem ?? 100}
                  onChange={(e) => setPlanoForm({ ...planoForm, ordem: Number(e.target.value) })}
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={!!planoForm.ativo}
                  onChange={(e) => setPlanoForm({ ...planoForm, ativo: e.target.checked })}
                />
                Ativo
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={!!planoForm.destaque}
                  onChange={(e) => setPlanoForm({ ...planoForm, destaque: e.target.checked })}
                />
                Plano inicial (IA apresenta primeiro)
              </label>
              <div className="actions span2">
                <button type="submit">{editPlanoId ? "Atualizar" : "Criar plano"}</button>
                {editPlanoId ? (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      setEditPlanoId(null);
                      setPlanoForm({
                        nome: "",
                        valor: 0,
                        ativo: true,
                        ordem: 100,
                        imagem_url: "",
                        descricao: "",
                        beneficios: "",
                        valor_pontualidade: null,
                        condicao_valor_pontualidade: "",
                      });
                      setPlanoImagemFile(null);
                      setPlanoImagemPreview("");
                    }}
                  >
                    Cancelar
                  </button>
                ) : null}
              </div>
            </form>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Nome</th>
                    <th>Valor</th>
                    <th>Inicial</th>
                    <th>Img</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {planos.map((p) => (
                    <tr key={p.id}>
                      <td>
                        {p.nome}
                        {!p.ativo ? " (inativo)" : ""}
                      </td>
                      <td>
                        R$ {Number(p.valor).toFixed(2)}
                        {p.valor_pontualidade != null
                          ? ` · pont. R$ ${Number(p.valor_pontualidade).toFixed(2)}`
                          : ""}
                      </td>
                      <td>{p.destaque ? "★ sim" : "—"}</td>
                      <td>
                        {p.imagem_url ? (
                          <img className="plano-thumb-sm" src={p.imagem_url} alt={p.nome} />
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="row-actions">
                        {!p.destaque ? (
                          <button
                            type="button"
                            className="ghost"
                            onClick={async () => {
                              try {
                                await setPlanoInicial(p.id);
                                setOkMsg(`${p.nome} definido como plano inicial`);
                                await refreshPlanos();
                              } catch (err) {
                                setError(err instanceof Error ? err.message : String(err));
                              }
                            }}
                          >
                            Definir inicial
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="ghost"
                          onClick={() => {
                            setEditPlanoId(p.id);
                            setPlanoForm(p);
                            setPlanoImagemFile(null);
                            setPlanoImagemPreview("");
                          }}
                        >
                          Editar
                        </button>
                        <button
                          type="button"
                          className="ghost danger"
                          onClick={() =>
                            void deletePlano(p.id).then(refreshPlanos).catch((err) =>
                              setError(err instanceof Error ? err.message : String(err)),
                            )
                          }
                        >
                          Excluir
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === "promocoes" && (
          <section className="panel">
            <h1>Promoções</h1>
            <form className="form-grid" onSubmit={savePromo}>
              <label>
                Código
                <input
                  required
                  value={promoForm.codigo || ""}
                  onChange={(e) => setPromoForm({ ...promoForm, codigo: e.target.value })}
                />
              </label>
              <label>
                Título
                <input
                  value={promoForm.titulo || ""}
                  onChange={(e) => setPromoForm({ ...promoForm, titulo: e.target.value })}
                />
              </label>
              <label className="span2">
                Descrição
                <textarea
                  value={promoForm.descricao || ""}
                  onChange={(e) => setPromoForm({ ...promoForm, descricao: e.target.value })}
                />
              </label>
              <label>
                Válido até
                <input
                  value={promoForm.valido_ate || ""}
                  onChange={(e) => setPromoForm({ ...promoForm, valido_ate: e.target.value })}
                  placeholder="YYYY-MM-DD"
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={!!promoForm.ativo}
                  onChange={(e) => setPromoForm({ ...promoForm, ativo: e.target.checked })}
                />
                Ativa
              </label>
              <div className="actions span2">
                <button type="submit">Salvar promoção</button>
              </div>
            </form>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Código</th>
                    <th>Título</th>
                    <th>Unidade</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {promos.map((p) => (
                    <tr key={p.id}>
                      <td>{p.codigo}</td>
                      <td>{p.titulo}</td>
                      <td>{p.unidade_id ?? "global"}</td>
                      <td>
                        <button
                          type="button"
                          className="ghost danger"
                          onClick={() =>
                            void deletePromocao(p.id).then(refreshPromos).catch((err) =>
                              setError(err instanceof Error ? err.message : String(err)),
                            )
                          }
                        >
                          Excluir
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === "config" && (
          <section className="panel">
            <h1>Configurações IA</h1>
            <p className="muted">
              Motor OpenAI, identidade e chaves. Escopo: {uid ? `unidade #${uid}` : "global"}.
            </p>
            <form className="form-grid config-ia" onSubmit={saveConfig}>
              <label className="span2">
                Nome da IA
                <input
                  value={iaForm.nome_ia}
                  onChange={(e) => setIaForm({ ...iaForm, nome_ia: e.target.value })}
                />
              </label>
              <label className="span2">
                Tom de voz
                <textarea
                  value={iaForm.tom_voz}
                  onChange={(e) => setIaForm({ ...iaForm, tom_voz: e.target.value })}
                  rows={2}
                />
              </label>
              <label className="check span2" style={{ marginTop: 0 }}>
                <input
                  type="checkbox"
                  checked={iaForm.pode_emoji}
                  onChange={(e) => setIaForm({ ...iaForm, pode_emoji: e.target.checked })}
                />
                Pode usar emoji nas respostas
              </label>

              <label>
                Provedor
                <select
                  value={iaForm.llm_provider}
                  onChange={(e) => setIaForm({ ...iaForm, llm_provider: e.target.value })}
                >
                  <option value="openai">OpenAI</option>
                  <option value="ollama">Ollama (local)</option>
                </select>
              </label>
              <label>
                Modelo
                <select
                  value={iaForm.openai_model}
                  onChange={(e) => setIaForm({ ...iaForm, openai_model: e.target.value })}
                >
                  <option value="gpt-4.1-mini">gpt-4.1-mini</option>
                  <option value="gpt-4o-mini">gpt-4o-mini</option>
                  <option value="gpt-4o">gpt-4o</option>
                  <option value="gpt-4.1">gpt-4.1</option>
                </select>
              </label>
              <label>
                Temperatura
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={iaForm.llm_temperature}
                  onChange={(e) =>
                    setIaForm({ ...iaForm, llm_temperature: Number(e.target.value) })
                  }
                />
              </label>

              <label className="span2">
                API Key OpenAI{" "}
                {iaMasks.openai ? (
                  <span className="key-mask">(atual: {iaMasks.openai})</span>
                ) : (
                  <span className="key-mask muted-inline">(não configurada)</span>
                )}
                <input
                  type="password"
                  value={iaForm.openai_api_key}
                  onChange={(e) => setIaForm({ ...iaForm, openai_api_key: e.target.value })}
                  placeholder="•••• cole nova key para rotacionar"
                  autoComplete="off"
                />
              </label>

              <label className="span2">
                API Key transcrição de áudio{" "}
                {iaMasks.transcription ? (
                  <span className="key-mask">(atual: {iaMasks.transcription})</span>
                ) : (
                  <span className="key-mask muted-inline">(ainda não usada)</span>
                )}
                <input
                  type="password"
                  value={iaForm.transcription_api_key}
                  onChange={(e) =>
                    setIaForm({ ...iaForm, transcription_api_key: e.target.value })
                  }
                  placeholder="•••• cole nova key para rotacionar"
                  autoComplete="off"
                />
                <small className="field-hint">
                  Reserva para quando o cliente mandar áudio: transcreve pra texto antes da Eva
                  processar. Pode ser Groq/Whisper — implementação em seguida.
                </small>
              </label>

              <div className="config-box span2">
                <strong>RAG / conhecimento</strong>
                <small className="field-hint">
                  A Eva consulta este webhook do painel (não depende mais só do .env).
                </small>
                <label>
                  Modo RAG
                  <select
                    value={iaForm.rag_provider}
                    onChange={(e) => setIaForm({ ...iaForm, rag_provider: e.target.value })}
                  >
                    <option value="webhook">Webhook n8n (produção)</option>
                    <option value="mock">Mock local (teste)</option>
                    <option value="none">Desligada</option>
                  </select>
                </label>
                <label>
                  RAG webhook URL
                  <input
                    value={iaForm.rag_webhook_url}
                    onChange={(e) =>
                      setIaForm({
                        ...iaForm,
                        rag_webhook_url: e.target.value,
                        rag_provider: e.target.value.trim() ? "webhook" : iaForm.rag_provider,
                      })
                    }
                    placeholder="https://n8n.../webhook/RAG_VENDAS"
                  />
                </label>
                <label>
                  RAG webhook token{" "}
                  {iaMasks.rag_token ? (
                    <span className="key-mask">(atual: {iaMasks.rag_token})</span>
                  ) : null}
                  <input
                    type="password"
                    value={iaForm.rag_webhook_token}
                    onChange={(e) =>
                      setIaForm({ ...iaForm, rag_webhook_token: e.target.value })
                    }
                    placeholder="•••• cole novo token para rotacionar"
                    autoComplete="off"
                  />
                </label>
              </div>

              <div className="actions span2">
                <button type="submit">Salvar</button>
              </div>
            </form>
          </section>
        )}

        {tab === "ferramentas" && (
          <section className="panel tool-panel">
            <div className="tool-layout">
              <form className="tool-form" onSubmit={saveTool}>
                <h1>{editToolId ? "Editar ferramenta" : "Criar ferramenta"}</h1>
                <div className="seg">
                  <button
                    type="button"
                    className={toolForm.integracao !== "unidade" ? "active" : ""}
                    onClick={() => setToolForm({ ...toolForm, integracao: "global", unidade_id: null })}
                  >
                    Personalizada
                  </button>
                  <button
                    type="button"
                    className={toolForm.integracao === "unidade" ? "active" : ""}
                    onClick={() => setToolForm({ ...toolForm, integracao: "unidade" })}
                  >
                    Por unidade
                  </button>
                </div>
                <label>
                  Chave da ferramenta
                  <input
                    required
                    value={toolForm.tool_key}
                    onChange={(e) => setToolForm({ ...toolForm, tool_key: e.target.value })}
                    placeholder="transferir_atendimento"
                  />
                </label>
                <label>
                  Nome da ferramenta
                  <input
                    required
                    value={toolForm.nome}
                    onChange={(e) => setToolForm({ ...toolForm, nome: e.target.value })}
                  />
                </label>
                <label>
                  Descrição
                  <textarea
                    value={toolForm.descricao}
                    onChange={(e) => setToolForm({ ...toolForm, descricao: e.target.value })}
                    rows={3}
                  />
                </label>
                <label>
                  URL do webhook
                  <input
                    value={toolForm.webhook_url}
                    onChange={(e) => setToolForm({ ...toolForm, webhook_url: e.target.value })}
                    placeholder="https://..."
                  />
                </label>
                {toolForm.integracao === "unidade" && (
                  <label>
                    Unidade
                    <select
                      value={toolForm.unidade_id ?? ""}
                      onChange={(e) =>
                        setToolForm({
                          ...toolForm,
                          unidade_id: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    >
                      <option value="">Selecione</option>
                      {unidades.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.nome}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <div className="checks-row">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={toolForm.destaque_dashboard}
                      onChange={(e) =>
                        setToolForm({ ...toolForm, destaque_dashboard: e.target.checked })
                      }
                    />
                    Destaque no dashboard
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={toolForm.ativo}
                      onChange={(e) => setToolForm({ ...toolForm, ativo: e.target.checked })}
                    />
                    Ativa
                  </label>
                </div>

                <div className="params-head">
                  <h2>Parâmetros</h2>
                  <button type="button" className="ghost" onClick={addParam}>
                    + Parâmetro
                  </button>
                </div>
                {toolForm.parametros.map((p, i) => (
                  <div className="param-row" key={i}>
                    <input
                      placeholder="Nome"
                      value={p.nome}
                      onChange={(e) => updateParam(i, { nome: e.target.value })}
                    />
                    <select
                      value={p.tipo}
                      onChange={(e) => updateParam(i, { tipo: e.target.value })}
                    >
                      <option value="texto">Texto</option>
                      <option value="numero">Número</option>
                      <option value="bool">Bool</option>
                    </select>
                    <input
                      placeholder="Descrição"
                      value={p.descricao}
                      onChange={(e) => updateParam(i, { descricao: e.target.value })}
                    />
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={p.obrigatorio}
                        onChange={(e) => updateParam(i, { obrigatorio: e.target.checked })}
                      />
                      Obrigatório
                    </label>
                    <button type="button" className="ghost danger" onClick={() => removeParam(i)}>
                      ×
                    </button>
                  </div>
                ))}

                <div className="actions">
                  <button type="submit">{editToolId ? "Atualizar" : "Criar ferramenta"}</button>
                  {editToolId ? (
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => {
                        setEditToolId(null);
                        setToolForm(emptyTool());
                      }}
                    >
                      Cancelar
                    </button>
                  ) : null}
                </div>
              </form>

              <div className="tool-list">
                <h2>Cadastradas</h2>
                {tools.map((t) => (
                  <div className="tool-card" key={t.id}>
                    <div>
                      <strong>{t.nome}</strong>
                      <small>{t.tool_key}</small>
                      <p>{t.descricao || "Sem descrição"}</p>
                      <small>
                        {t.parametros?.length || 0} params · {t.chamadas_sucesso} sucessos
                        {t.destaque_dashboard ? " · destaque" : ""}
                      </small>
                    </div>
                    <div className="row-actions">
                      <button type="button" className="ghost" onClick={() => editTool(t)}>
                        Editar
                      </button>
                      <button
                        type="button"
                        className="ghost danger"
                        onClick={() =>
                          void deleteFerramenta(t.id).then(refreshTools).catch((err) =>
                            setError(err instanceof Error ? err.message : String(err)),
                          )
                        }
                      >
                        Excluir
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {tab === "unidades" && (
          <section className="panel">
            <h1>Unidades</h1>
            <p className="muted">Filiais / cidades operacionais.</p>
            <form className="form-grid narrow" onSubmit={saveUnidade}>
              <label>
                Código
                <input
                  required
                  value={novaUnidade.codigo}
                  onChange={(e) => setNovaUnidade({ ...novaUnidade, codigo: e.target.value })}
                />
              </label>
              <label>
                Nome
                <input
                  required
                  value={novaUnidade.nome}
                  onChange={(e) => setNovaUnidade({ ...novaUnidade, nome: e.target.value })}
                />
              </label>
              <div className="actions span2">
                <button type="submit">Criar unidade</button>
              </div>
            </form>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Código</th>
                    <th>Nome</th>
                    <th>Ativo</th>
                  </tr>
                </thead>
                <tbody>
                  {unidades.map((u) => (
                    <tr key={u.id}>
                      <td>{u.codigo}</td>
                      <td>{u.nome}</td>
                      <td>{u.ativo ? "sim" : "não"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
