# 11 — Segurança

## Autenticação

- **E-mail/senha**: senha com hash `bcrypt` (salt automático por `bcrypt.gensalt()`), nunca
  armazenada nem logada em texto puro. Sessão representada por um JWT assinado (HS256,
  `jwt_secret_key`), guardado em `st.session_state` — não persiste em cookie, portanto não
  sobrevive a um refresh de página.
- **Google OAuth (opcional)**: delega toda a autenticação ao Google via `st.login()` nativo do
  Streamlit; sessão em cookie assinado pelo próprio Streamlit.
- **E-mail não é uma prova de identidade verificada** em nenhum dos dois modos — é tratado
  puramente como chave de conta.

## Autorização

- Não há papéis/permissões (todo usuário autenticado tem acesso às mesmas funcionalidades).
- O único controle de acesso é "autenticado vs. não autenticado" (`auth.is_logged_in`).
- Dados são isolados por usuário apenas no nível de credenciais do Earth Engine (cada usuário só
  enxerga/usa a própria credencial, indexada pelo próprio e-mail).

## Proteção de dados sensíveis

| Dado | Proteção |
| --- | --- |
| Senha da conta do app | Hash bcrypt (nunca reversível) |
| Credencial de conta de serviço do Earth Engine | Criptografia simétrica autenticada (Fernet), chave única do app (`app_encryption_key`) |
| `secrets.toml` (chaves/segredos) | Nunca commitado (`.gitignore`); montado como volume somente-leitura no container, nunca copiado para dentro da imagem Docker |
| `data/app.db` (banco SQLite) | Fora da imagem Docker, montado como volume; ignorado pelo Git |

## Validação de entrada / upload de arquivos

- Extensão e tamanho de arquivo validados antes de qualquer processamento
  (`validate_file_upload`).
- Nome de arquivo nunca usado diretamente como caminho em disco — sempre gerado via `uuid4`.
- Caracteres de path traversal (`.. / \`) e caracteres inválidos bloqueados como defesa em
  profundidade, mesmo não sendo estritamente necessários dado o ponto acima.
- Caminho final do arquivo temporário é resolvido e validado como estando dentro do diretório
  temporário do sistema antes da escrita.
- Arquivo temporário sempre removido em bloco `finally`, mesmo em caso de erro.

## Transporte (produção)

- HTTPS obrigatório via Caddy (`docker-compose.prod.yml` + `Caddyfile`), com certificado emitido e
  renovado automaticamente via Let's Encrypt.
- Em desenvolvimento local (`docker-compose.yml`), o tráfego não é criptografado (HTTP direto na
  porta 8501) — aceitável apenas para uso local.

## Riscos e limitações conhecidas

| Risco | Detalhe | Mitigação atual |
| --- | --- | --- |
| Chave de criptografia única para todos os usuários | Qualquer processo com `app_encryption_key` decifra credenciais de todos os usuários | Nenhuma além de tratar a chave como segredo de produção |
| `except:` genérico no botão "Status GEE" | Engole qualquer exceção, inclusive erros de programação, não só falha de conectividade | Nenhuma — melhoria sugerida em `app.py` |
| Sessão via `session_state` (modo e-mail/senha) | Não sobrevive a refresh; não é revogável antes da expiração de 24h | Nenhuma — trade-off aceito de design |
| Sem verificação de e-mail | E-mail não comprova posse do endereço | Nenhuma — aceitável para o modelo de ameaça atual (uso individual, não multi-tenant crítico) |
| `InvalidToken` mascarado como "sem credencial" | Ver [04_database.md](04_database.md) | Nenhuma — melhoria sugerida: logar o evento sem vazar o payload |

## Boas práticas já aplicadas

- Segredos nunca hardcoded no código — sempre via `st.secrets` / `.streamlit/secrets.toml`.
- Nenhuma credencial de terceiro (Earth Engine) é compartilhada entre usuários.
- Falha de extração de dados nunca é mascarada com dados fictícios (ver
  [09_business_rules.md](09_business_rules.md)) — reduz o risco de um usuário tratar uma análise
  inválida como confiável.
