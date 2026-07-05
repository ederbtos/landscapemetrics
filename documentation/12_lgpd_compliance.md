# 12 — Conformidade com a LGPD

> Este documento descreve como o sistema trata dados pessoais **hoje**, com base no código atual.
> Não representa aconselhamento jurídico — para uma avaliação formal de conformidade, consulte um
> profissional jurídico especializado em proteção de dados.

## Dados pessoais tratados pelo sistema

| Dado | Categoria (LGPD) | Onde fica armazenado | Finalidade |
| --- | --- | --- | --- |
| E-mail | Dado pessoal (identificador) | Tabelas `users` e `user_credentials` (SQLite) | Identidade de conta / chave de associação às credenciais do Earth Engine |
| Senha (hash) | Dado pessoal sensível de autenticação | Tabela `users`, como hash bcrypt | Autenticação |
| JSON da conta de serviço do Earth Engine | Dado de terceiro (credencial de projeto GCP do usuário), cifrado | Tabela `user_credentials`, cifrado com Fernet | Executar análises em nome do usuário, usando a cota dele |
| Dados de sessão (JWT) | Dado pessoal (contém o e-mail) | `st.session_state` (memória do processo, não persistido em disco) | Manter a sessão de login |
| E-mail via Google OAuth (`st.user.email`) | Dado pessoal | Sessão gerenciada pelo Streamlit (cookie), não persistida pelo app além do necessário para o login | Identidade de conta (modo Google) |

O sistema **não coleta** dados de geolocalização pessoal do usuário (o ponto desenhado no mapa é
um dado de análise geoespacial sobre o território, não um dado pessoal do usuário) nem dados
sensíveis (saúde, biometria, origem étnica etc.).

## Base legal aplicável (a se confirmar com jurídico)

- **Execução de contrato / prestação do serviço**: tratamento do e-mail e senha para permitir o
  login é necessário para o próprio funcionamento do serviço solicitado pelo usuário.
- **Consentimento implícito no cadastro**: ao criar uma conta, o usuário fornece ativamente
  e-mail, senha e, posteriormente, sua própria credencial do Earth Engine.

## Minimização de dados

- O sistema não coleta nome, telefone, CPF ou qualquer outro dado pessoal além do e-mail e da
  senha (hash).
- Nenhum dado de terceiros é coletado sobre outras pessoas.

## Segurança no tratamento (art. 46 da LGPD)

Ver [11_security.md](11_security.md) para o detalhamento técnico. Resumo relevante à LGPD:

- Senha nunca em texto puro (hash bcrypt).
- Credencial do Earth Engine cifrada em repouso (Fernet).
- Segredos de aplicação (`secrets.toml`) fora do controle de versão e fora da imagem Docker.
- Transporte criptografado (HTTPS) em produção, via Caddy/Let's Encrypt.

## Direitos do titular — estado atual (gaps conhecidos)

| Direito (LGPD art. 18) | Suportado hoje? | Observação |
| --- | --- | --- |
| Confirmação/acesso aos dados | Parcial | O usuário vê seu e-mail (badge na sidebar) e pode recadastrar credenciais, mas não há uma tela de "meus dados" |
| Correção de dados | Parcial | E-mail não pode ser alterado (é a chave primária); senha não tem fluxo de "esqueci minha senha" |
| Eliminação dos dados (exclusão de conta) | **Não implementado** | Não existe função para o usuário excluir a própria conta/credenciais — remoção hoje exigiria intervenção manual direta no banco por quem opera o sistema |
| Portabilidade | **Não implementado** | Não há exportação dos dados de conta do próprio usuário (diferente do CSV de métricas, que não é dado pessoal) |
| Revogação de consentimento | Parcial | Logout encerra a sessão, mas não remove dados armazenados |

> **Recomendação**: se o sistema for operado com usuários reais fora de um contexto interno/de
> confiança, implementar ao menos um fluxo de exclusão de conta (remoção de linhas em `users` e
> `user_credentials` pelo próprio e-mail autenticado) antes de tratar o sistema como conforme à
> LGPD em produção.

## Retenção e backup

- Dados de conta e credenciais são retidos indefinidamente — não há expiração/purga automática.
- Backups (`scripts/backup-db.sh`) copiam o banco inteiro, incluindo dados pessoais e credenciais
  cifradas, para o próprio servidor e, opcionalmente, para um destino remoto configurado via
  `BACKUP_REMOTE`. Quem define esse destino remoto é responsável por garantir que ele também
  atenda aos requisitos de segurança/LGPD (ex.: não usar um destino sem controle de acesso
  adequado).

## Compartilhamento com terceiros

- A credencial do Earth Engine, uma vez cadastrada, é usada para autenticar diretamente contra a
  API do Google Earth Engine — isso não é "compartilhamento de dados pessoais do usuário com
  terceiro" no sentido da LGPD, mas sim o uso da própria credencial de nuvem do usuário para
  executar a análise que ele solicitou.
- Não há envio de dados pessoais a nenhum outro serviço de terceiros além do Google (Earth Engine
  e, opcionalmente, OAuth).
