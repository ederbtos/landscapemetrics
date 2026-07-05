# 07 — Fluxos de Usuário

## Fluxo 1 — Primeiro acesso (cadastro + credenciais)

```mermaid
flowchart TD
    A[Acessa o app] --> B{Autenticado?}
    B -- Não --> C[Landing page]
    C --> D{Tem conta?}
    D -- Não --> E["Aba 'Criar conta'<br/>e-mail + senha (8+ caracteres)"]
    D -- Sim --> F["Aba 'Entrar'<br/>e-mail + senha"]
    C -.opcional, se configurado.-> G["Entrar com Google"]
    E --> H[Conta criada, sessão JWT iniciada]
    F --> I{Credenciais corretas?}
    I -- Não --> F
    I -- Sim --> H
    G --> H
    H --> J{Credencial GEE já cadastrada?}
    J -- Não --> K["Formulário: colar JSON da<br/>conta de serviço do Earth Engine"]
    K --> L[Validação estrutural do JSON]
    L -- inválido --> K
    L -- válido --> M[Credencial salva, cifrada]
    J -- Sim --> M
    M --> N[Earth Engine inicializado]
    N --> O[Tela principal de análise]
```

## Fluxo 2 — Cálculo de métricas de paisagem

```mermaid
flowchart TD
    A[Tela principal, já logado] --> B[Desenha 1 ponto no mapa e exporta GeoJSON]
    B --> C[Faz upload do GeoJSON]
    C --> D{Quantos pontos no arquivo?}
    D -- "0 ou > 1" --> E[Erro explícito, processamento não continua]
    D -- "exatamente 1" --> F[Escolhe fonte de dados]
    F --> G{MapBiomas ou GeoTIFF próprio?}
    G -- MapBiomas --> H[Define raio do buffer]
    G -- GeoTIFF --> I[Faz upload do GeoTIFF] --> H
    H --> J["Clica em 'Calcular métricas'"]
    J --> K[Pipeline roda dentro de st.status]
    K --> L{Extração de pixels teve sucesso?}
    L -- Não --> M["Processamento interrompido (st.stop)<br/>nenhuma métrica exibida"]
    L -- Sim --> N[PyLandStats calcula métricas por classe]
    N --> O[Resultado salvo em session_state]
    O --> P[Mapa + gráfico + tabela renderizados]
    P --> Q["Download do CSV (opcional)"]
```

## Fluxo 3 — Atualização de credenciais do Earth Engine

```mermaid
flowchart LR
    A[Usuário já logado, com credencial cadastrada] --> B["Abre expander<br/>'Atualizar credenciais'"]
    B --> C[Cola novo JSON da conta de serviço]
    C --> D{JSON válido estruturalmente?}
    D -- Não --> C
    D -- Sim --> E["Credencial anterior é substituída<br/>(upsert, sem histórico)"]
    E --> F[Página recarrega com a nova credencial ativa]
```

## Fluxo 4 — Logout

```mermaid
flowchart LR
    A[Botão 'Sair' na sidebar] --> B{Modo de login ativo}
    B -- Google OAuth --> C["st.logout()<br/>encerra sessão nativa do Streamlit"]
    B -- E-mail/senha --> D["Remove jwt_token de session_state"]
    C --> E[Retorna à landing page]
    D --> E
```
