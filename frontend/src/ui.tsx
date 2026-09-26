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

export function confirmarExclusao(item: string, consequencia: string): boolean {
  return window.confirm(
    `Tem certeza que deseja excluir ${item}?\n\n${consequencia}`,
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
