# CI — Git push → Docker Hub

Pipeline automática: cada **push na `main`** publica novas imagens no Docker Hub.

| Imagem | Repositório Hub |
|--------|-----------------|
| API | `edreimp/iavendas-backend:latest` |
| Painel | `edreimp/iavendas-frontend:latest` |

Workflow: [`.github/workflows/docker-publish.yml`](workflows/docker-publish.yml)

> O **container** da API continua se chamando `iavendas-api`; no Hub a imagem é `iavendas-backend`.

---

## Secrets no GitHub

Repositório: **EdreiM/IA_VENDAS_MOVFIBRA** → Settings → Secrets → Actions

| Nome | Valor |
|------|-------|
| `DOCKERHUB_USERNAME` | `edreimp` |
| `DOCKERHUB_TOKEN` | Personal access token do Docker Hub (Read + Write) |

---

## Atualizar produção

1. `git push origin main` → Actions verde
2. Portainer → stack `iavendas` → **Pull and redeploy**

Variáveis mínimas da stack: ver [`DEPLOY_PORTAINER.md`](../DEPLOY_PORTAINER.md) §5.
