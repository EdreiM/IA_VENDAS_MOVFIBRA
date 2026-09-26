import { ReactNode } from "react";

export type Tab =
  | "chat"
  | "metricas"
  | "conversas"
  | "clientes"
  | "planos"
  | "promocoes"
  | "config"
  | "integracao"
  | "cobertura"
  | "ferramentas"
  | "unidades";

export const NAV_GROUPS: { title: string; tabs: { id: Tab; label: string }[] }[] = [
  {
    title: "Operação",
    tabs: [
      { id: "chat", label: "Simulador" },
      { id: "metricas", label: "Métricas" },
      { id: "conversas", label: "Conversas" },
      { id: "clientes", label: "Clientes" },
    ],
  },
  {
    title: "Catálogo",
    tabs: [
      { id: "planos", label: "Planos" },
      { id: "promocoes", label: "Promoções" },
    ],
  },
  {
    title: "Integrações",
    tabs: [
      { id: "config", label: "Config IA" },
      { id: "integracao", label: "Chatwoot" },
      { id: "cobertura", label: "Viabilidade" },
      { id: "ferramentas", label: "Ferramentas" },
    ],
  },
  {
    title: "Administração",
    tabs: [{ id: "unidades", label: "Unidades" }],
  },
];

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        <h1>{title}</h1>
        {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
      </div>
      {action ? <div className="page-header-action">{action}</div> : null}
    </header>
  );
}

export type ConfirmExclusaoRequest = {
  item: string;
  consequencia: string;
  resolve: (confirmed: boolean) => void;
};

/** @deprecated Prefer ConfirmDialog + pedirConfirmacaoExclusao no App */
export function confirmarExclusao(item: string, consequencia: string): boolean {
  return window.confirm(
    `Tem certeza que deseja excluir ${item}?\n\n${consequencia}`,
  );
}

export function ConfirmDialog({
  request,
  onDismiss,
}: {
  request: ConfirmExclusaoRequest | null;
  onDismiss: () => void;
}) {
  if (!request) return null;

  const fechar = (confirmed: boolean) => {
    request.resolve(confirmed);
    onDismiss();
  };

  return (
    <div
      className="confirm-overlay"
      role="presentation"
      onClick={() => fechar(false)}
      onKeyDown={(e) => {
        if (e.key === "Escape") fechar(false);
      }}
    >
      <div
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-desc"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-title">Confirmar exclusão</h2>
        <p>
          Tem certeza que deseja excluir <strong>{request.item}</strong>?
        </p>
        <p id="confirm-desc" className="confirm-consequencia">
          {request.consequencia}
        </p>
        <div className="confirm-actions">
          <button type="button" className="ghost" onClick={() => fechar(false)}>
            Não
          </button>
          <button type="button" className="danger" onClick={() => fechar(true)}>
            Sim, excluir
          </button>
        </div>
      </div>
    </div>
  );
}

export function ToastStack({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  if (!message) return null;
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      <div className="toast toast-ok">
        <span>{message}</span>
        <button type="button" className="toast-close" onClick={onDismiss} aria-label="Fechar">
          ×
        </button>
      </div>
    </div>
  );
}
