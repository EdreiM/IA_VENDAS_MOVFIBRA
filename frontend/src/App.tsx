import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  deleteConversa,
  deleteFerramenta,
  deletePlano,
  deletePromocao,
  fetchAgents,
  fetchConfigIa,
  fetchConfigChatwoot,
  fetchConfigCobertura,
  fetchExemploPayloadChatwoot,
  CoberturaTestResult,
  fetchInboxes,
  saveConfigIa,
  saveConfigChatwoot,
  saveConfigCobertura,
  testCobertura,
  testParseChatwoot,
  ChatwootParseResult,
  fetchCliente,
  fetchClientes,
  fetchConversas,
  fetchMensagensCliente,
  patchCliente,
  Cliente,
  MensagemHistorico,
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
  clearAdminToken,
  fetchAdminMe,
  getAdminToken,
  postAdminLogin,
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
import { NAV_GROUPS, PageHeader, Tab, ToastStack } from "./ui";

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
    dica: "Informe cidade e bairro — consulta real IXC + Google Maps.",
    msgs: ["Santarém, Diamantino"],
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

function mapInboxes(raw: unknown): Option[] {
  return asList(raw)
    .map((item) => {
      const box = item as Record<string, unknown>;
      const id = Number(box.id);
      if (!Number.isFinite(id)) return null;
      const channel = String(box.channel_type || box.provider || "").trim();
      const suffix = channel ? ` (${channel})` : "";
      return { id, label: `${String(box.name || `Inbox ${id}`)}${suffix}` };
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

function fmtCampo(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  return String(v);
}

function rotuloCliente(c: { nome?: string | null; telefone?: string | null; id_cliente: string }) {
  return (c.nome || "").trim() || (c.telefone || "").trim() || c.id_cliente;
}

const EMPTY_PLANO: Partial<Plano> = {
  nome: "",
  valor: 0,
  ativo: true,
  ordem: 100,
  imagem_url: "",
  descricao: "",
  beneficios: "",
  valor_pontualidade: null,
  condicao_valor_pontualidade: "",
};

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
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [userEmail, setUserEmail] = useState("");
  const [loginEmail, setLoginEmail] = useState("admin@movfibra.com");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [unidades, setUnidades] = useState<Unidade[]>([]);
  const [unidadeFiltro, setUnidadeFiltro] = useState<number | "">("");
  const [error, setError] = useState("");
  const [okMsg, setOkMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [apiOk, setApiOk] = useState<boolean | null>(null);

  const [chatId, setChatId] = useState("");
  const [chatConversationId, setChatConversationId] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatMsgs, setChatMsgs] = useState<ChatMsg[]>([
    {
      who: "sistema",
      text: "Simulador da Eva. Use as sugestões à direita ou digite livremente. Reinicie a conversa antes de um fluxo novo.",
    },
  ]);
  const [chatEstado, setChatEstado] = useState<string>("—");

  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [funil, setFunil] = useState<Funil | null>(null);
  const [conversas, setConversas] = useState<Conversa[]>([]);
  const [statusFiltro, setStatusFiltro] = useState("");
  const [convBusca, setConvBusca] = useState("");
  const [sel, setSel] = useState<Conversa | null>(null);
  const [turnos, setTurnos] = useState<unknown[]>([]);
  const [mensagensConv, setMensagensConv] = useState<MensagemHistorico[]>([]);
  const selIdRef = useRef<string | null>(null);
  const convMsgsRef = useRef<HTMLDivElement>(null);
  const prevMsgCountRef = useRef(0);
  const [clientes, setClientes] = useState<Cliente[]>([]);
  const [clienteBusca, setClienteBusca] = useState("");
  const [selCliente, setSelCliente] = useState<Cliente | null>(null);
  const [clienteForm, setClienteForm] = useState<Record<string, string>>({});
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
  const [planoEditorOpen, setPlanoEditorOpen] = useState(false);
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

  const [cwForm, setCwForm] = useState({
    inbound_enabled: true,
    inbox_id: "",
    inbound_mode: "allowlist",
    allowlist_phones: "",
    buffer_enabled: false,
    public_base_url: "",
    webhook_token: "",
    chatwoot_base_url: "https://chatwoot.mov.pro.br",
    chatwoot_api_token: "",
  });
  const [cwMeta, setCwMeta] = useState({
    webhook_url: "",
    envio_ok: false,
    token_mask: "",
    token_configured: false,
    api_mask: "",
    api_configured: false,
  });
  const [inboxes, setInboxes] = useState<Option[]>([]);
  const [cwTestPayload, setCwTestPayload] = useState("");
  const [cwTestResult, setCwTestResult] = useState<ChatwootParseResult | null>(null);

  const [cobForm, setCobForm] = useState({
    coverage_provider: "ixc",
    google_maps_api_key: "",
    ixc_base_url: "https://ixc.mov.pro.br/webservice/v1",
    ixc_user: "",
    ixc_password: "",
  });
  const [cobMeta, setCobMeta] = useState({
    google_mask: "",
    google_configured: false,
    ixc_user_mask: "",
    ixc_user_configured: false,
    ixc_pass_configured: false,
    ixc_pass_mask: "",
    pronta: false,
    faltando: [] as string[],
  });
  const [cobTest, setCobTest] = useState({
    cidade: "Santarém",
    bairro: "Diamantino",
    localizacao_fixa: "-2.4494913,-54.7120315",
  });
  const [cobTestResult, setCobTestResult] = useState<CoberturaTestResult | null>(null);

  const [tools, setTools] = useState<Ferramenta[]>([]);
  const [toolForm, setToolForm] = useState(emptyTool());
  const [editToolId, setEditToolId] = useState<number | null>(null);
  const [toolEditorOpen, setToolEditorOpen] = useState(false);

  const [novaUnidade, setNovaUnidade] = useState({ codigo: "", nome: "" });

  const uid = unidadeFiltro === "" ? undefined : Number(unidadeFiltro);

  const doLogin = async (e: FormEvent) => {
    e.preventDefault();
    setLoginBusy(true);
    setError("");
    try {
      const r = await postAdminLogin(loginEmail.trim(), loginPassword);
      setAdminToken(r.token);
      setUserEmail(r.email);
      setAuthed(true);
      setLoginPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoginBusy(false);
    }
  };

  const doLogout = () => {
    clearAdminToken();
    setAuthed(false);
    setUserEmail("");
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

  const pollConversas = useCallback(async () => {
    try {
      const c = await fetchConversas(60, {
        unidade_id: uid,
        status: statusFiltro || undefined,
      });
      const items = c.items || [];
      setConversas(items);

      const activeId = selIdRef.current;
      if (activeId) {
        const atualizada = items.find((x) => x.id_cliente === activeId);
        if (atualizada) {
          setSel((prev) => (prev ? { ...prev, ...atualizada } : atualizada));
        }
        const m = await fetchMensagensCliente(activeId, 80);
        const msgs = m.items || [];
        setMensagensConv((prev) => {
          if (
            prev.length === msgs.length &&
            prev.length > 0 &&
            prev[prev.length - 1]?.id === msgs[msgs.length - 1]?.id
          ) {
            return prev;
          }
          if (prev.length === 0 && msgs.length === 0) return prev;
          return msgs;
        });
      }
    } catch {
      /* polling silencioso */
    }
  }, [uid, statusFiltro]);

  const refreshClientes = useCallback(async () => {
    const c = await fetchClientes({
      q: clienteBusca.trim() || undefined,
      unidade_id: uid,
      limite: 100,
    });
    setClientes(c.items || []);
  }, [uid, clienteBusca]);

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

  const refreshIntegracao = useCallback(async () => {
    const cfg = await fetchConfigChatwoot(uid);
    setCwForm({
      inbound_enabled: !!cfg.inbound_enabled,
      inbox_id: cfg.inbox_id || "",
      inbound_mode: cfg.inbound_mode || "allowlist",
      allowlist_phones: cfg.allowlist_phones || "",
      buffer_enabled: !!cfg.buffer_enabled,
      public_base_url: cfg.public_base_url || "",
      webhook_token: "",
      chatwoot_base_url: cfg.chatwoot_base_url || "https://chatwoot.mov.pro.br",
      chatwoot_api_token: "",
    });
    setCwMeta({
      webhook_url: cfg.webhook_url || "",
      envio_ok: !!cfg.envio_resposta_configurado,
      token_mask: cfg.webhook_token_mask || "",
      token_configured: !!cfg.webhook_token_configured,
      api_mask: cfg.chatwoot_api_token_mask || "",
      api_configured: !!cfg.chatwoot_api_configured,
    });
    try {
      const inb = await fetchInboxes();
      if (inb.ok) setInboxes(mapInboxes(inb.data));
    } catch {
      /* lista de inboxes — salve o token Chatwoot abaixo e atualize */
    }
    try {
      const ex = await fetchExemploPayloadChatwoot();
      setCwTestPayload(JSON.stringify(ex.payload, null, 2));
    } catch {
      /* opcional */
    }
  }, [uid]);

  const refreshCobertura = useCallback(async () => {
    const cfg = await fetchConfigCobertura(uid);
    setCobForm({
      coverage_provider: cfg.coverage_provider || "ixc",
      google_maps_api_key: "",
      ixc_base_url: cfg.ixc_base_url || "https://ixc.mov.pro.br/webservice/v1",
      ixc_user: "",
      ixc_password: "",
    });
    setCobMeta({
      google_mask: cfg.google_maps_api_key_mask || "",
      google_configured: !!cfg.google_maps_configured,
      ixc_user_mask: cfg.ixc_user_mask || "",
      ixc_user_configured: !!cfg.ixc_configured,
      ixc_pass_configured: !!cfg.ixc_password_configured,
      ixc_pass_mask: cfg.ixc_password_mask || "",
      pronta: !!cfg.cobertura_pronta,
      faltando: cfg.faltando || [],
    });
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
      if (tab === "clientes") await refreshClientes();
      if (tab === "planos") await refreshPlanos();
      if (tab === "promocoes") await refreshPromos();
      if (tab === "config") await refreshConfig();
      if (tab === "integracao") await refreshIntegracao();
      if (tab === "cobertura") await refreshCobertura();
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
    refreshClientes,
    refreshPlanos,
    refreshPromos,
    refreshConfig,
    refreshIntegracao,
    refreshCobertura,
    refreshTools,
  ]);

  useEffect(() => {
    void (async () => {
      const tok = getAdminToken();
      if (!tok) {
        setAuthed(false);
        return;
      }
      try {
        const me = await fetchAdminMe();
        setUserEmail(me.email);
        setAuthed(true);
      } catch {
        clearAdminToken();
        setAuthed(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (authed) void refreshAll();
  }, [authed, refreshAll]);

  useEffect(() => {
    selIdRef.current = sel?.id_cliente ?? null;
  }, [sel?.id_cliente]);

  useEffect(() => {
    if (!authed || tab !== "conversas") return;
    let cancelled = false;
    const tick = () => {
      if (cancelled || document.hidden) return;
      void pollConversas();
    };
    const onVisible = () => {
      if (!cancelled && !document.hidden) void pollConversas();
    };
    document.addEventListener("visibilitychange", onVisible);
    const id = window.setInterval(tick, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [authed, tab, pollConversas]);

  useEffect(() => {
    if (mensagensConv.length > prevMsgCountRef.current) {
      const el = convMsgsRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
    prevMsgCountRef.current = mensagensConv.length;
  }, [mensagensConv]);

  const maxFunil = useMemo(
    () => Math.max(1, ...(funil?.etapas.map((e) => e.quantidade) || [1])),
    [funil],
  );

  useEffect(() => {
    if (!okMsg) return;
    const t = window.setTimeout(() => setOkMsg(""), 4500);
    return () => window.clearTimeout(t);
  }, [okMsg]);

  function resetPlanoForm() {
    setEditPlanoId(null);
    setPlanoEditorOpen(false);
    setPlanoForm({ ...EMPTY_PLANO });
    setPlanoImagemFile(null);
    setPlanoImagemPreview("");
  }

  function openCreatePlano() {
    setEditPlanoId(null);
    setPlanoForm({ ...EMPTY_PLANO });
    setPlanoImagemFile(null);
    setPlanoImagemPreview("");
    setPlanoEditorOpen(true);
  }

  function openEditPlano(p: Plano) {
    setEditPlanoId(p.id);
    setPlanoForm(p);
    setPlanoImagemFile(null);
    setPlanoImagemPreview("");
    setPlanoEditorOpen(true);
  }

  function resetToolForm() {
    setEditToolId(null);
    setToolEditorOpen(false);
    setToolForm(emptyTool());
  }

  function openCreateTool() {
    setEditToolId(null);
    setToolForm(emptyTool());
    setToolEditorOpen(true);
  }

  const conversasFiltradas = useMemo(() => {
    const q = convBusca.trim().toLowerCase();
    if (!q) return conversas;
    return conversas.filter((c) => {
      const blob = [c.nome, c.telefone, c.id_cliente, c.conversation_id, c.fase, c.cidade]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }, [conversas, convBusca]);

  async function onSelectConversa(c: Conversa) {
    setSel(c);
    setMensagensConv([]);
    try {
      const [t, m] = await Promise.all([
        fetchTurnos(c.id_cliente),
        fetchMensagensCliente(c.id_cliente, 80),
      ]);
      setTurnos(t.items || []);
      setMensagensConv(m.items || []);
    } catch {
      setTurnos([]);
      setMensagensConv([]);
    }
  }

  function clienteFormFromDetail(c: Cliente) {
    return {
      nome: c.nome || "",
      cpf: c.cpf || "",
      email: c.email || "",
      telefone: c.telefone || "",
      data_nascimento: c.data_nascimento || "",
      rg: c.rg || "",
      cep: c.cep || "",
      rua: c.rua || "",
      numero: c.numero || "",
      complemento: c.complemento || "",
      cidade: c.cidade || "",
      bairro: c.bairro || "",
      metodo_pagamento: c.metodo_pagamento || "",
    };
  }

  async function onSelectCliente(c: Cliente) {
    setSelCliente(null);
    try {
      const full = await fetchCliente(c.id_cliente);
      setSelCliente(full);
      setClienteForm(clienteFormFromDetail(full));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveCliente(e: FormEvent) {
    e.preventDefault();
    if (!selCliente) return;
    setError("");
    try {
      const saved = await patchCliente(selCliente.id_cliente, clienteForm);
      setSelCliente(saved);
      setClienteForm(clienteFormFromDetail(saved));
      setOkMsg("Cliente salvo");
      await refreshClientes();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function buscarClientes(e: FormEvent) {
    e.preventDefault();
    await refreshClientes();
  }

  async function deletarConversaSelecionada() {
    if (!sel) return;
    const rotulo = sel.nome || sel.telefone || sel.id_cliente;
    const ok = window.confirm(
      `Tem certeza que deseja excluir a conversa de "${rotulo}"?\n\nIsso apaga o histórico, estado e turnos. Não pode ser desfeito.`,
    );
    if (!ok) return;
    setError("");
    try {
      await deleteConversa(sel.id_cliente);
      setSel(null);
      setTurnos([]);
      setMensagensConv([]);
      setOkMsg("Conversa excluída");
      await refreshConversas();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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
      resetPlanoForm();
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

  async function saveIntegracao(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const saved = await saveConfigChatwoot({
        ...cwForm,
        unidade_id: uid ?? null,
      });
      setCwMeta({
        webhook_url: saved.webhook_url || "",
        envio_ok: !!saved.envio_resposta_configurado,
        token_mask: saved.webhook_token_mask || "",
        token_configured: !!saved.webhook_token_configured,
        api_mask: saved.chatwoot_api_token_mask || "",
        api_configured: !!saved.chatwoot_api_configured,
      });
      setCwForm((f) => ({ ...f, webhook_token: "", chatwoot_api_token: "" }));
      if (saved.chatwoot_api_configured) {
        try {
          const inb = await fetchInboxes();
          if (inb.ok) setInboxes(mapInboxes(inb.data));
        } catch {
          /* ignore */
        }
      }
      setOkMsg("Integração Chatwoot salva");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function runTestParse() {
    setError("");
    setCwTestResult(null);
    try {
      const payload = JSON.parse(cwTestPayload) as Record<string, unknown>;
      const r = await testParseChatwoot(payload);
      setCwTestResult(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveCobertura(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const saved = await saveConfigCobertura({
        ...cobForm,
        coverage_provider: "ixc",
        unidade_id: uid ?? null,
      });
      setCobMeta({
        google_mask: saved.google_maps_api_key_mask || "",
        google_configured: !!saved.google_maps_configured,
        ixc_user_mask: saved.ixc_user_mask || "",
        ixc_user_configured: !!saved.ixc_configured,
        ixc_pass_configured: !!saved.ixc_password_configured,
        ixc_pass_mask: saved.ixc_password_mask || "",
        pronta: !!saved.cobertura_pronta,
        faltando: saved.faltando || [],
      });
      setCobForm((f) => ({
        ...f,
        google_maps_api_key: "",
        ixc_user: "",
        ixc_password: "",
      }));
      setOkMsg("Viabilidade salva");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function runTestCobertura() {
    setError("");
    setCobTestResult(null);
    try {
      const r = await testCobertura({
        ...cobTest,
        unidade_id: uid ?? null,
      });
      setCobTestResult(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function copyWebhookUrl() {
    if (!cwMeta.webhook_url) return;
    void navigator.clipboard.writeText(cwMeta.webhook_url);
    setOkMsg("URL copiada");
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
      resetToolForm();
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
    setToolEditorOpen(true);
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
        id_cliente: chatId.trim() || `sim-${Date.now()}`,
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
      const cid = chatId.trim() || `sim-${Date.now()}`;
      if (!chatId.trim()) setChatId(cid);
      await postReset(cid);
      setChatMsgs([
        {
          who: "sistema",
          text: `Conversa reiniciada (${cid}). Pode mandar um oi.`,
        },
      ]);
      setChatEstado("inicio");
      setOkMsg("Chat reiniciado");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (authed === null) {
    return (
      <div className="login-shell">
        <p className="muted">Carregando…</p>
      </div>
    );
  }

  if (!authed) {
    return (
      <div className="login-shell">
        <form className="login-card" onSubmit={(e) => void doLogin(e)}>
          <div className="brand" style={{ marginBottom: "1.5rem" }}>
            <span className="brand-mark">E</span>
            <div>
              <strong>Eva</strong>
              <small>Painel operacional MOV</small>
            </div>
          </div>
          <h1>Entrar</h1>
          <label>
            Email
            <input
              type="email"
              value={loginEmail}
              onChange={(e) => setLoginEmail(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Senha
            <input
              type="password"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {error ? <div className="alert bad">{error}</div> : null}
          <button type="submit" disabled={loginBusy}>
            {loginBusy ? "Entrando…" : "Entrar"}
          </button>
        </form>
      </div>
    );
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
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className="nav-group">
              <p className="nav-group-title">{group.title}</p>
              <div className="nav-group-items">
                {group.tabs.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={tab === t.id ? "nav-item active" : "nav-item"}
                    onClick={() => setTab(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className={apiOk ? "dot ok" : apiOk === false ? "dot bad" : "dot"} />
          API {apiOk ? "online" : apiOk === false ? "offline" : "…"}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="user-bar">
            <span className="user-email">{userEmail}</span>
            <button type="button" className="ghost" onClick={doLogout}>
              Sair
            </button>
          </div>
          <div className="top-filters">
            <label className="filter-unidade">
              <span className="filter-label">Unidade</span>
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
        <ToastStack message={okMsg} onDismiss={() => setOkMsg("")} />

        {tab === "chat" && (
          <section className="panel chat-panel">
            <div className="chat-layout">
              <div className="chat-main">
                <PageHeader
                  title="Simulador"
                  subtitle="Simule uma conversa com a Eva, como no WhatsApp."
                  action={
                    <button type="button" className="ghost" onClick={() => void reiniciarChat()}>
                      Reiniciar conversa
                    </button>
                  }
                />
                <div className="chat-toolbar">
                    <label className="chat-id">
                      id_cliente
                      <input
                        value={chatId}
                        onChange={(e) => setChatId(e.target.value)}
                        placeholder="telefone ou id_cliente"
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
                    Preencha <code>conversation_id</code> (Chatwoot) para simular cadastro, termos e
                    agendamento via n8n. A cobertura usa IXC real — informe endereço com viabilidade.
                  </small>
                </div>
              </aside>
            </div>
          </section>
        )}

        {tab === "metricas" && (
          <section className="panel">
            <PageHeader
              title="Métricas"
              subtitle="Indicadores essenciais do funil comercial e desempenho operacional da Eva."
            />
            <div className="metrics-hero">
              <div className="stat-hero">
                <span className="stat-hero-label">Conversas</span>
                <strong className="stat-hero-value">{resumo?.conversas ?? "—"}</strong>
                <span className="stat-hero-hint">Total no período</span>
              </div>
              <div className="stat-hero">
                <span className="stat-hero-label">Com IA</span>
                <strong className="stat-hero-value">{resumo?.com_ia ?? "—"}</strong>
                <span className="stat-hero-hint">Atendidas pela Eva</span>
              </div>
              <div className="stat-hero">
                <span className="stat-hero-label">Transferidos</span>
                <strong className="stat-hero-value">{resumo?.transferidos_humano ?? "—"}</strong>
                <span className="stat-hero-hint">Handoff humano</span>
              </div>
              <div className="stat-hero">
                <span className="stat-hero-label">Agendamentos</span>
                <strong className="stat-hero-value">{resumo?.agendamentos_confirmados ?? "—"}</strong>
                <span className="stat-hero-hint">Instalações confirmadas</span>
              </div>
            </div>
            <div className="metrics-secondary">
              <div className="stat-compact">
                <span>Cobertura</span>
                <strong>{resumo?.com_cobertura ?? "—"}</strong>
              </div>
              <div className="stat-compact">
                <span>Mensagens</span>
                <strong>{resumo?.mensagens ?? "—"}</strong>
              </div>
              {(resumo?.ferramentas_destaque || []).map((f) => (
                <div className="stat-compact" key={f.id}>
                  <span>{f.nome}</span>
                  <strong>{f.chamadas_sucesso}</strong>
                </div>
              ))}
            </div>
            <div className="funil-section">
              <h2>Funil comercial</h2>
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
            </div>
          </section>
        )}

        {tab === "conversas" && (
          <section className="panel conv-panel">
            <PageHeader
              title="Conversas"
              subtitle="Histórico de atendimentos, mensagens e handoff para equipe humana."
              action={
              <select value={statusFiltro} onChange={(e) => setStatusFiltro(e.target.value)}>
                <option value="">Todos status</option>
                <option value="com_ia">Com IA</option>
                <option value="transferido">Transferido</option>
                <option value="finalizado">Finalizado</option>
              </select>
              }
            />

            <div className="conv-layout">
              <aside className="conv-list">
                <div className="conv-list-tools">
                  <input
                    value={convBusca}
                    onChange={(e) => setConvBusca(e.target.value)}
                    placeholder="Buscar nome, telefone ou ID…"
                  />
                </div>
                <ul>
                  {conversasFiltradas.map((c) => (
                    <li
                      key={c.id_cliente}
                      className={
                        sel?.id_cliente === c.id_cliente ? "conv-item active" : "conv-item"
                      }
                      onClick={() => void onSelectConversa(c)}
                    >
                      <strong>{c.nome || c.telefone || c.id_cliente}</strong>
                      <small>
                        {c.telefone || c.conversation_id || c.id_cliente}
                        {c.status ? ` · ${c.status.replace(/_/g, " ")}` : ""}
                      </small>
                      <small className="conv-item-meta">
                        {c.fase}
                        {c.cidade ? ` · ${c.cidade}` : ""}
                      </small>
                    </li>
                  ))}
                  {conversasFiltradas.length === 0 && (
                    <li className="muted conv-empty">Nenhuma conversa encontrada.</li>
                  )}
                </ul>
              </aside>

              <main className="conv-chat">
                {!sel ? (
                  <div className="conv-chat-empty muted">Selecione uma conversa na lista.</div>
                ) : (
                  <>
                    <header className="conv-chat-head">
                      <div>
                        <h2>{sel.nome || sel.telefone || sel.id_cliente}</h2>
                        <p className="muted">
                          {sel.telefone || sel.id_cliente}
                          {sel.conversation_id ? ` · CID ${sel.conversation_id}` : ""}
                        </p>
                      </div>
                      <div className="conv-chat-actions">
                        {statusBadge(sel.status)}
                        <span className="muted-inline">{sel.fase}</span>
                        <button
                          type="button"
                          className="ghost danger"
                          onClick={() => void deletarConversaSelecionada()}
                        >
                          Excluir
                        </button>
                      </div>
                    </header>

                    <div className="conv-messages" ref={convMsgsRef}>
                      {mensagensConv.length === 0 ? (
                        <p className="muted conv-chat-empty">Nenhuma mensagem registrada ainda.</p>
                      ) : (
                        mensagensConv.map((m) => (
                          <div
                            key={m.id}
                            className={
                              m.remetente === "cliente"
                                ? "conv-bubble conv-bubble-cliente"
                                : "conv-bubble conv-bubble-eva"
                            }
                          >
                            <small>
                              {m.remetente === "cliente" ? "Cliente" : "Eva"}
                              {m.created_at
                                ? ` · ${new Date(m.created_at).toLocaleString()}`
                                : ""}
                            </small>
                            <div>{m.mensagem}</div>
                          </div>
                        ))
                      )}
                    </div>

                    {sel.plano_confirmado && (
                      <p className="conv-meta-bar muted">
                        Plano: {sel.plano_confirmado}
                      </p>
                    )}

                    <details className="conv-handoff-drawer">
                      <summary>Handoff e turnos</summary>
                      <div className="conv-handoff-body">
                        <div className="conv-handoff-grid">
                          <label>
                            Atendente
                            <select
                              value={assigneeId}
                              onChange={(e) => setAssigneeId(e.target.value)}
                            >
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
                            <select
                              value={statusHandoff}
                              onChange={(e) => setStatusHandoff(e.target.value)}
                            >
                              <option value="open">open</option>
                              <option value="pending">pending</option>
                              <option value="resolved">resolved</option>
                            </select>
                          </label>
                        </div>
                        <button type="button" onClick={() => void doHandoff()}>
                          Transferir agora
                        </button>
                        <h4>Turnos recentes</h4>
                        <ul className="turnos conv-turnos">
                          {turnos.length === 0 ? (
                            <li className="muted">Nenhum turno.</li>
                          ) : (
                            turnos.slice(0, 8).map((t, i) => {
                              const row = t as Record<string, unknown>;
                              return (
                                <li key={i}>
                                  <small>
                                    {String(row.acao || row.fase || "")} —{" "}
                                    {String(row.created_at || "").slice(0, 19)}
                                  </small>
                                </li>
                              );
                            })
                          )}
                        </ul>
                      </div>
                    </details>
                  </>
                )}
              </main>
            </div>
          </section>
        )}

        {tab === "clientes" && (
          <section className="panel clientes-panel">
            <PageHeader
              title="Clientes"
              subtitle="Cadastro estruturado — a Eva grava nome, CPF, endereço, plano e dados operacionais durante a conversa."
            />
            <div className="clientes-layout">
              <aside className="clientes-list">
                <form className="clientes-search" onSubmit={(e) => void buscarClientes(e)}>
                  <input
                    value={clienteBusca}
                    onChange={(e) => setClienteBusca(e.target.value)}
                    placeholder="Buscar nome, telefone, CPF ou e-mail"
                  />
                  <button type="submit">Buscar</button>
                </form>
                <ul>
                  {clientes.map((c) => (
                    <li
                      key={c.id_cliente}
                      className={
                        selCliente?.id_cliente === c.id_cliente ? "client-item active" : "client-item"
                      }
                      onClick={() => void onSelectCliente(c)}
                    >
                      <strong>{rotuloCliente(c)}</strong>
                      <small>
                        {c.telefone || c.id_cliente}
                        {c.status ? ` · ${c.status}` : ""}
                      </small>
                    </li>
                  ))}
                  {clientes.length === 0 && (
                    <li className="muted" style={{ padding: "12px" }}>
                      Nenhum cliente encontrado.
                    </li>
                  )}
                </ul>
              </aside>

              <div className="clientes-detail">
                {!selCliente ? (
                  <p className="muted">Selecione um cliente na lista.</p>
                ) : (
                  <>
                    <div className="row-head">
                      <div>
                        <h2>{rotuloCliente(selCliente)}</h2>
                        <p className="muted">
                          ID: {selCliente.id_cliente} · {statusBadge(selCliente.status)} · fase{" "}
                          {selCliente.fase}
                          {selCliente.aguardando ? ` · aguardando ${selCliente.aguardando}` : ""}
                        </p>
                      </div>
                    </div>

                    <form className="form-grid client-form" onSubmit={(e) => void saveCliente(e)}>
                      <h3 className="span2">Identificação</h3>
                      <label>
                        Nome
                        <input
                          value={clienteForm.nome}
                          onChange={(e) => setClienteForm({ ...clienteForm, nome: e.target.value })}
                          placeholder="Preenchido pela IA na conversa"
                        />
                      </label>
                      <label>
                        CPF
                        <input
                          value={clienteForm.cpf}
                          onChange={(e) => setClienteForm({ ...clienteForm, cpf: e.target.value })}
                        />
                      </label>
                      <label>
                        E-mail
                        <input
                          value={clienteForm.email}
                          onChange={(e) => setClienteForm({ ...clienteForm, email: e.target.value })}
                        />
                      </label>
                      <label>
                        Telefone
                        <input
                          value={clienteForm.telefone}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, telefone: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Data de nascimento
                        <input
                          value={clienteForm.data_nascimento}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, data_nascimento: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        RG
                        <input
                          value={clienteForm.rg}
                          onChange={(e) => setClienteForm({ ...clienteForm, rg: e.target.value })}
                        />
                      </label>

                      <h3 className="span2">Endereço</h3>
                      <label>
                        CEP
                        <input
                          value={clienteForm.cep}
                          onChange={(e) => setClienteForm({ ...clienteForm, cep: e.target.value })}
                        />
                      </label>
                      <label>
                        Rua
                        <input
                          value={clienteForm.rua}
                          onChange={(e) => setClienteForm({ ...clienteForm, rua: e.target.value })}
                        />
                      </label>
                      <label>
                        Número
                        <input
                          value={clienteForm.numero}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, numero: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Complemento
                        <input
                          value={clienteForm.complemento}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, complemento: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Cidade
                        <input
                          value={clienteForm.cidade}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, cidade: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Bairro
                        <input
                          value={clienteForm.bairro}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, bairro: e.target.value })
                          }
                        />
                      </label>

                      <h3 className="span2">Plano e operação</h3>
                      <label>
                        Plano confirmado
                        <input readOnly value={fmtCampo(selCliente.plano_confirmado)} />
                      </label>
                      <label>
                        Plano apresentado
                        <input readOnly value={fmtCampo(selCliente.plano_apresentado)} />
                      </label>
                      <label>
                        Método pagamento
                        <input
                          value={clienteForm.metodo_pagamento}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, metodo_pagamento: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Cobertura
                        <input readOnly value={fmtCampo(selCliente.tem_cobertura)} />
                      </label>
                      <label>
                        Cadastro completo
                        <input readOnly value={fmtCampo(selCliente.cadastro_completo)} />
                      </label>
                      <label>
                        Termos enviados
                        <input readOnly value={fmtCampo(selCliente.termos_enviados)} />
                      </label>
                      <label>
                        Agendamento
                        <input
                          readOnly
                          value={fmtCampo(
                            selCliente.data_agendamento
                              ? `${selCliente.data_agendamento} ${selCliente.horario_escolhido || ""}`.trim()
                              : selCliente.agendamento_confirmado,
                          )}
                        />
                      </label>

                      <h3 className="span2">Chatwoot / IXC</h3>
                      <label>
                        Conversation ID
                        <input readOnly value={fmtCampo(selCliente.conversation_id)} />
                      </label>
                      <label>
                        Contact ID
                        <input readOnly value={fmtCampo(selCliente.contact_id)} />
                      </label>
                      <label>
                        Cliente IXC
                        <input readOnly value={fmtCampo(selCliente.ixc_cliente_id)} />
                      </label>
                      <label>
                        Contrato / OS
                        <input
                          readOnly
                          value={fmtCampo(
                            [selCliente.id_contrato_ixc, selCliente.os_id].filter(Boolean).join(" / ") ||
                              null,
                          )}
                        />
                      </label>

                      <div className="actions span2">
                        <button type="submit">Salvar cadastro</button>
                      </div>
                    </form>

                    <p className="muted">
                      Início:{" "}
                      {selCliente.created_at
                        ? new Date(selCliente.created_at).toLocaleString()
                        : "—"}{" "}
                      · Atualizado:{" "}
                      {selCliente.updated_at
                        ? new Date(selCliente.updated_at).toLocaleString()
                        : "—"}
                    </p>
                  </>
                )}
              </div>
            </div>
          </section>
        )}

        {tab === "planos" && (
          <section className="panel">
            <PageHeader
              title="Planos"
              subtitle="Catálogo comercial usado pela Eva nas conversas. Defina qual plano a IA apresenta primeiro."
              action={
                !planoEditorOpen ? (
                  <button type="button" onClick={openCreatePlano}>
                    Criar plano
                  </button>
                ) : null
              }
            />
            <div className={`page-split${planoEditorOpen ? " has-editor" : ""}`}>
              <div className="page-split-main">
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Plano</th>
                        <th>Valor</th>
                        <th>Status</th>
                        <th>Imagem</th>
                        <th aria-label="Ações" />
                      </tr>
                    </thead>
                    <tbody>
                      {planos.map((p) => (
                        <tr key={p.id}>
                          <td>
                            <strong>{p.nome}</strong>
                            {!p.ativo ? (
                              <span className="tool-tag" style={{ marginLeft: 8 }}>
                                Inativo
                              </span>
                            ) : null}
                          </td>
                          <td>
                            R$ {Number(p.valor).toFixed(2)}
                            {p.valor_pontualidade != null
                              ? ` · pont. R$ ${Number(p.valor_pontualidade).toFixed(2)}`
                              : ""}
                          </td>
                          <td>
                            {p.destaque ? (
                              <span className="plano-inicial-badge">★ Plano inicial</span>
                            ) : (
                              "—"
                            )}
                          </td>
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
                            <button type="button" className="ghost" onClick={() => openEditPlano(p)}>
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
              </div>

              {planoEditorOpen ? (
                <aside className="editor-panel">
                  <div className="editor-panel-head">
                    <h2>{editPlanoId ? "Editar plano" : "Novo plano"}</h2>
                    <button type="button" className="ghost" onClick={resetPlanoForm}>
                      Fechar
                    </button>
                  </div>
                  <form className="form-grid" onSubmit={savePlano}>
                    <div className="form-section span2">
                      <p className="form-section-title">Identificação e preço</p>
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
                    </div>
                    <div className="form-section span2">
                      <p className="form-section-title">Apresentação comercial</p>
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
                    </div>
                    <div className="form-section span2">
                      <p className="form-section-title">Publicação</p>
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
                <button type="submit">{editPlanoId ? "Salvar alterações" : "Criar plano"}</button>
                <button type="button" className="ghost" onClick={resetPlanoForm}>
                  Cancelar
                </button>
              </div>
                    </div>
                  </form>
                </aside>
              ) : null}
            </div>
          </section>
        )}

        {tab === "promocoes" && (
          <section className="panel">
            <PageHeader
              title="Promoções"
              subtitle="Códigos promocionais vinculados ao catálogo e à unidade selecionada."
            />
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
            <PageHeader
              title="Config IA"
              subtitle={`Motor OpenAI, identidade e chaves. Escopo: ${uid ? `unidade #${uid}` : "global"}.`}
            />
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
                  A Eva consulta este webhook configurado no painel.
                </small>
                <label>
                  Modo RAG
                  <select
                    value={iaForm.rag_provider}
                    onChange={(e) => setIaForm({ ...iaForm, rag_provider: e.target.value })}
                  >
                    <option value="webhook">Webhook n8n</option>
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

        {tab === "integracao" && (
          <section className="panel">
            <PageHeader
              title="Chatwoot"
              subtitle="Webhook de entrada, caixa da IA e URL pública da API para o Chatwoot enviar mensagens."
            />

            <div className="config-box" style={{ marginBottom: "1rem" }}>
              <strong>Status</strong>
              <ul className="muted" style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
                <li>
                  Entrada:{" "}
                  {cwForm.inbound_enabled ? (
                    <span className="badge badge-com_ia">Ativa</span>
                  ) : (
                    <span className="badge badge-finalizado">Desligada</span>
                  )}
                </li>
                <li>
                  Envio de respostas:{" "}
                  {cwMeta.envio_ok ? (
                    <span>OK (API Chatwoot ou ferramenta enviar_mensagem)</span>
                  ) : (
                    <span className="muted-inline">
                      Salve o <strong>Token API Chatwoot</strong> abaixo ou configure a ferramenta{" "}
                      <em>enviar_mensagem</em>
                    </span>
                  )}
                </li>
              </ul>
            </div>

            <form className="form-grid config-ia" onSubmit={saveIntegracao}>
              <label className="check span2">
                <input
                  type="checkbox"
                  checked={cwForm.inbound_enabled}
                  onChange={(e) => setCwForm({ ...cwForm, inbound_enabled: e.target.checked })}
                />
                Receber mensagens do Chatwoot (webhook inbound)
              </label>

              <label className="span2">
                URL do webhook (cole no Chatwoot → Configurações → Webhooks)
                <div className="row-head" style={{ gap: "0.5rem", marginTop: "0.35rem" }}>
                  <input readOnly value={cwMeta.webhook_url} />
                  <button type="button" className="secondary" onClick={copyWebhookUrl}>
                    Copiar
                  </button>
                </div>
                <small className="field-hint">
                  Evento recomendado: <strong>message_created</strong> apenas. A Eva ignora outgoing,
                  notas privadas, inbox errado e conversas com time humano.
                </small>
              </label>

              <label>
                URL do Chatwoot
                <input
                  value={cwForm.chatwoot_base_url}
                  onChange={(e) => setCwForm({ ...cwForm, chatwoot_base_url: e.target.value })}
                  placeholder="https://chatwoot.mov.pro.br"
                />
              </label>

              <label>
                Token API Chatwoot
                {cwMeta.api_configured ? (
                  <span className="key-mask"> (atual: {cwMeta.api_mask})</span>
                ) : (
                  <span className="key-mask"> (não configurado)</span>
                )}
                <input
                  type="password"
                  value={cwForm.chatwoot_api_token}
                  onChange={(e) => setCwForm({ ...cwForm, chatwoot_api_token: e.target.value })}
                  placeholder="Cole o access token do Chatwoot"
                  autoComplete="off"
                />
                <small className="field-hint">
                  Perfil Chatwoot → Access Token. Necessário para listar inboxes.
                </small>
              </label>

              <label>
                Caixa de entrada (inbox)
                <select
                  value={cwForm.inbox_id}
                  onChange={(e) => setCwForm({ ...cwForm, inbox_id: e.target.value })}
                >
                  <option value="">— selecione —</option>
                  {inboxes.map((box) => (
                    <option key={box.id} value={String(box.id)}>
                      {box.label}
                    </option>
                  ))}
                </select>
                <small className="field-hint">
                  Só mensagens desta inbox chegam na Eva. Salve o token acima e clique Atualizar.
                </small>
              </label>

              <label>
                Modo de entrada
                <select
                  value={cwForm.inbound_mode}
                  onChange={(e) => setCwForm({ ...cwForm, inbound_mode: e.target.value })}
                >
                  <option value="allowlist">Allowlist (números autorizados)</option>
                  <option value="open">Aberto</option>
                  <option value="closed">Fechado</option>
                </select>
              </label>

              <label className="span2">
                Allowlist (telefones autorizados, CSV)
                <input
                  value={cwForm.allowlist_phones}
                  onChange={(e) => setCwForm({ ...cwForm, allowlist_phones: e.target.value })}
                  placeholder="93992219098, 93991234567"
                  disabled={cwForm.inbound_mode !== "allowlist"}
                />
              </label>

              <label>
                URL pública da API
                <input
                  value={cwForm.public_base_url}
                  onChange={(e) => setCwForm({ ...cwForm, public_base_url: e.target.value })}
                  placeholder="https://api.seudominio.com"
                />
                <small className="field-hint">
                  Ex.: http://200.6.142.5:8002 — usada para montar a URL do webhook.
                </small>
              </label>

              <label>
                Token do webhook (opcional)
                {cwMeta.token_configured ? (
                  <span className="key-mask"> (atual: {cwMeta.token_mask})</span>
                ) : null}
                <input
                  type="password"
                  value={cwForm.webhook_token}
                  onChange={(e) => setCwForm({ ...cwForm, webhook_token: e.target.value })}
                  placeholder="Header X-Webhook-Token"
                  autoComplete="off"
                />
              </label>

              <label className="check span2">
                <input
                  type="checkbox"
                  checked={cwForm.buffer_enabled}
                  onChange={(e) => setCwForm({ ...cwForm, buffer_enabled: e.target.checked })}
                />
                Agrupar mensagens rápidas (debounce ~3,5s antes de responder)
              </label>

              <div className="actions span2">
                <button type="submit">Salvar integração</button>
              </div>
            </form>

            <div className="config-box span2" style={{ marginTop: "1.5rem" }}>
              <strong>Testar payload do Chatwoot</strong>
              <small className="field-hint">
                Cole o JSON que o Chatwoot envia (ou use o exemplo) e veja como a Eva interpreta.
              </small>
              <textarea
                value={cwTestPayload}
                onChange={(e) => setCwTestPayload(e.target.value)}
                rows={14}
                style={{ width: "100%", marginTop: "0.5rem", fontFamily: "monospace", fontSize: "0.85rem" }}
              />
              <div className="actions" style={{ marginTop: "0.5rem" }}>
                <button type="button" onClick={() => void runTestParse()}>
                  Testar parse
                </button>
              </div>
              {cwTestResult && (
                <pre
                  style={{
                    marginTop: "0.75rem",
                    padding: "0.75rem",
                    background: "var(--surface-elevated)",
                    borderRadius: "var(--radius-sm)",
                    overflow: "auto",
                    fontSize: "0.85rem",
                  }}
                >
                  {JSON.stringify(cwTestResult, null, 2)}
                </pre>
              )}
            </div>
          </section>
        )}

        {tab === "cobertura" && (
          <section className="panel">
            <PageHeader
              title="Viabilidade"
              subtitle="Configure IXC e Google Maps para consulta de cobertura. Pin GPS usa IXC; texto de endereço usa Google quando disponível."
            />
            <div className="viab-sections">
              <div className="config-box">
                <strong>Status da integração</strong>
                <div className="viab-status-grid">
                  <div className="viab-status-item">
                    <label>Modo</label>
                    <strong>
                      <span className="badge badge-com_ia">IXC + Google Maps</span>
                    </strong>
                  </div>
                  <div className={`viab-status-item${cobMeta.pronta ? " is-ok" : " is-warn"}`}>
                    <label>Pronto para atender</label>
                    <strong>
                      {cobMeta.pronta ? (
                        <span className="badge badge-com_ia">Sim — configurado</span>
                      ) : (
                        <span className="badge badge-finalizado">Falta configurar</span>
                      )}
                    </strong>
                  </div>
                  <div className={`viab-status-item${cobMeta.ixc_user_configured && cobMeta.ixc_pass_configured ? " is-ok" : " is-warn"}`}>
                    <label>IXC</label>
                    <strong>{cobMeta.ixc_user_configured && cobMeta.ixc_pass_configured ? "Credenciais OK" : "Pendente"}</strong>
                  </div>
                  <div className={`viab-status-item${cobMeta.google_configured ? " is-ok" : ""}`}>
                    <label>Google Maps</label>
                    <strong>{cobMeta.google_configured ? "Chave configurada" : "Opcional (texto)"}</strong>
                  </div>
                </div>
                {!cobMeta.pronta && cobMeta.faltando.length > 0 ? (
                  <p className="muted" style={{ margin: 0 }}>
                    Faltando: {cobMeta.faltando.join(", ")}
                  </p>
                ) : null}
              </div>

              <div className="config-box">
                <strong>Credenciais</strong>
                <p className="form-section-desc">Deixe em branco campos de senha/chave para manter o valor atual.</p>
            <form className="form-grid config-ia" onSubmit={saveCobertura}>
              <label className="span2">
                URL base IXC
                <input
                  value={cobForm.ixc_base_url}
                  onChange={(e) => setCobForm({ ...cobForm, ixc_base_url: e.target.value })}
                  placeholder="https://ixc.mov.pro.br/webservice/v1"
                />
              </label>

              <label>
                Usuário IXC
                {cobMeta.ixc_user_configured ? (
                  <span className="key-mask"> (atual: {cobMeta.ixc_user_mask})</span>
                ) : (
                  <span className="key-mask"> (não configurado)</span>
                )}
                <input
                  type="text"
                  value={cobForm.ixc_user}
                  onChange={(e) => setCobForm({ ...cobForm, ixc_user: e.target.value })}
                  placeholder="Usuário API IXC"
                  autoComplete="off"
                />
              </label>

              <label>
                Senha IXC
                {cobMeta.ixc_pass_configured ? (
                  <span className="key-mask"> (atual: {cobMeta.ixc_pass_mask})</span>
                ) : (
                  <span className="key-mask"> (não configurada)</span>
                )}
                <input
                  type="password"
                  value={cobForm.ixc_password}
                  onChange={(e) => setCobForm({ ...cobForm, ixc_password: e.target.value })}
                  placeholder="Cole nova senha para rotacionar"
                  autoComplete="off"
                />
              </label>

              <label className="span2">
                Google Maps API Key
                {cobMeta.google_configured ? (
                  <span className="key-mask"> (atual: {cobMeta.google_mask})</span>
                ) : (
                  <span className="key-mask"> (não configurada)</span>
                )}
                <input
                  type="password"
                  value={cobForm.google_maps_api_key}
                  onChange={(e) =>
                    setCobForm({ ...cobForm, google_maps_api_key: e.target.value })
                  }
                  placeholder="Chave Geocoding API"
                  autoComplete="off"
                />
                <small className="field-hint">
                  Necessária quando o cliente informa cidade/bairro em texto. Pin GPS funciona só com
                  IXC.
                </small>
              </label>

              <div className="actions span2">
                <button type="submit">Salvar credenciais</button>
              </div>
            </form>
              </div>

              <div className="config-box">
              <strong>Testar consulta</strong>
              <p className="form-section-desc">
                Simula a consulta com as credenciais salvas — não passa pelo LLM.
              </p>
              <div className="form-grid config-ia" style={{ marginTop: "0.75rem" }}>
                <label>
                  Cidade
                  <input
                    value={cobTest.cidade}
                    onChange={(e) => setCobTest({ ...cobTest, cidade: e.target.value })}
                  />
                </label>
                <label>
                  Bairro
                  <input
                    value={cobTest.bairro}
                    onChange={(e) => setCobTest({ ...cobTest, bairro: e.target.value })}
                  />
                </label>
                <label className="span2">
                  GPS (opcional — lat,lng)
                  <input
                    value={cobTest.localizacao_fixa}
                    onChange={(e) =>
                      setCobTest({ ...cobTest, localizacao_fixa: e.target.value })
                    }
                    placeholder="-2.4494913,-54.7120315"
                  />
                </label>
              </div>
              <button type="button" className="secondary" onClick={() => void runTestCobertura()}>
                Testar viabilidade
              </button>
              {cobTestResult && (
                <pre
                  style={{
                    marginTop: "0.75rem",
                    padding: "0.75rem",
                    background: "var(--surface-elevated)",
                    borderRadius: "var(--radius-sm)",
                    overflow: "auto",
                    fontSize: "0.85rem",
                  }}
                >
                  {JSON.stringify(cobTestResult.resultado, null, 2)}
                </pre>
              )}
            </div>
            </div>
          </section>
        )}

        {tab === "ferramentas" && (
          <section className="panel tool-panel">
            <PageHeader
              title="Ferramentas"
              subtitle="Webhooks e integrações que a Eva pode chamar durante o atendimento (cadastro, termos, transferência, etc.)."
              action={
                !toolEditorOpen ? (
                  <button type="button" onClick={openCreateTool}>
                    Nova ferramenta
                  </button>
                ) : null
              }
            />
            <div className={`page-split${toolEditorOpen ? " has-editor" : ""}`}>
              <div className="page-split-main tool-list">
                {tools.length === 0 ? (
                  <p className="muted">Nenhuma ferramenta cadastrada.</p>
                ) : null}
                {tools.map((t) => (
                  <div className="tool-card" key={t.id}>
                    <div>
                      <strong>{t.nome}</strong>
                      <small>{t.tool_key}</small>
                      <p>{t.descricao || "Sem descrição"}</p>
                      <div className="tool-card-meta">
                        <span className="tool-tag">{t.parametros?.length || 0} parâmetros</span>
                        <span className="tool-tag">{t.chamadas_sucesso} sucessos</span>
                        {t.destaque_dashboard ? <span className="tool-tag">Destaque</span> : null}
                        {!t.ativo ? <span className="tool-tag">Inativa</span> : null}
                        {t.integracao === "unidade" ? <span className="tool-tag">Por unidade</span> : null}
                      </div>
                    </div>
                    <div className="tool-card-actions">
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

              {toolEditorOpen ? (
                <aside className="editor-panel">
                  <div className="editor-panel-head">
                    <h2>{editToolId ? "Editar ferramenta" : "Nova ferramenta"}</h2>
                    <button type="button" className="ghost" onClick={resetToolForm}>
                      Fechar
                    </button>
                  </div>
              <form className="tool-form" onSubmit={saveTool} style={{ background: "transparent", border: 0, padding: 0, boxShadow: "none" }}>
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
                  <button type="submit">{editToolId ? "Salvar alterações" : "Criar ferramenta"}</button>
                  <button type="button" className="ghost" onClick={resetToolForm}>
                    Cancelar
                  </button>
                </div>
              </form>
                </aside>
              ) : null}
            </div>
          </section>
        )}

        {tab === "unidades" && (
          <section className="panel">
            <PageHeader
              title="Unidades"
              subtitle="Filiais e cidades operacionais — filtram dados e configurações por escopo."
            />
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
