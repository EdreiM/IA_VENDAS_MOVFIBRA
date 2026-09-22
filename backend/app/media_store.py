"""Upload local de imagens de planos."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import BACKEND_ROOT, get_settings

UPLOAD_ROOT = BACKEND_ROOT / "uploads" / "planos"
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_CT = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "application/octet-stream",
}
MAX_BYTES = 8 * 1024 * 1024  # 8 MB


def ensure_upload_dirs() -> Path:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    return UPLOAD_ROOT


def public_url(filename: str) -> str:
    return f"/media/planos/{filename}"


def caminho_local_imagem(imagem_url: str | None) -> Path | None:
    """Resolve arquivo em disco a partir de /media/planos/..."""
    if not imagem_url:
        return None
    url = str(imagem_url).strip()
    prefix = "/media/planos/"
    if not url.startswith(prefix):
        return None
    name = url[len(prefix) :]
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    path = UPLOAD_ROOT / name
    return path if path.is_file() else None


def url_absoluta_imagem(imagem_url: str | None) -> str:
    """URL acessível por n8n/WhatsApp (PUBLIC_BASE_URL + path relativo)."""
    if not imagem_url:
        return ""
    url = str(imagem_url).strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    from app.chatwoot_config import resolver_public_base_url

    base = resolver_public_base_url().rstrip("/")
    if not base:
        return url
    if not url.startswith("/"):
        url = "/" + url
    return f"{base}{url}"


async def salvar_imagem_plano(plano_id: int, file: UploadFile) -> str:
    ensure_upload_dirs()
    name = (file.filename or "plano.png").strip()
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail="Envie PNG, JPG ou WEBP",
        )
    ct = (file.content_type or "").lower()
    if ct and ct not in ALLOWED_CT:
        raise HTTPException(status_code=400, detail=f"Tipo de arquivo inválido: {ct}")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Imagem maior que 8 MB")

    if ext == ".jpeg":
        ext = ".jpg"
    filename = f"plano_{plano_id}_{uuid.uuid4().hex[:10]}{ext}"
    dest = UPLOAD_ROOT / filename
    dest.write_bytes(raw)
    return public_url(filename)


def remover_arquivo_se_local(imagem_url: str | None) -> None:
    path = caminho_local_imagem(imagem_url)
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass
