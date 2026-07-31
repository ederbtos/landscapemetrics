"""
Descrição da funcionalidade
---------------------------
Dependências compartilhadas do FastAPI — o gate de login vira uma
`Depends(get_current_user)` reutilizável em toda rota autenticada, lendo o
access token do header `Authorization: Bearer`.
"""
from fastapi import Header, HTTPException, Request, status

from app.core.config import get_settings
from app.core.security import decode_access_token

# Requisições de fora dessas origens nunca acionam o bypass de login abaixo,
# mesmo com `dev_auth_bypass_email` configurado — ver comentário no bypass.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1"}


def get_current_user(request: Request, authorization: str | None = Header(default=None)) -> str:
    # --- BYPASS TEMPORÁRIO (remover depois — pedido do usuário 2026-07-30 para
    # rodar cálculos reais sem a fricção do login enquanto isso). Só ativa se
    # `dev_auth_bypass_email` estiver setado em backend/.env; ausente por
    # padrão, então isso não afeta ninguém que não configure explicitamente.
    #
    # Restrito a requisições de loopback (127.0.0.1/::1): `cookie_secure=false`
    # sozinho (verificado no boot por `assert_dev_bypass_is_safe`, core/config.py)
    # não garante que o host esteja inacessível pela rede — o próprio
    # `docker-compose.yml` de desenvolvimento já roda com `cookie_secure=false`
    # E publica a porta 8000 (revisão de segurança, 2026-07-30). Sem essa
    # checagem, ligar o bypass nesse mesmo compose exporia a API inteira sem
    # credencial nenhuma para qualquer um com acesso à rede do host. Note que
    # isso só cobre o caminho `uvicorn` direto (`README.md` — "Local sem
    # Docker"); rodando via `docker-compose.yml`, o NAT do Docker faz a
    # conexão não aparecer como loopback de dentro do container mesmo para
    # quem acessa via `localhost` no host — por isso `docker-compose.yml`
    # também passou a publicar a porta só em `127.0.0.1` (mitigação na
    # camada de rede, não depende dessa checagem em Python).
    bypass_email = get_settings().dev_auth_bypass_email
    client_host = request.client.host if request.client else None
    if bypass_email and client_host in _LOOPBACK_HOSTS:
        return bypass_email
    # --- fim do bypass ---

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado.")
    token = authorization.removeprefix("Bearer ").strip()
    email = decode_access_token(token)
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada.")
    return email
