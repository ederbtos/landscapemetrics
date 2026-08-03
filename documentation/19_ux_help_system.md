# 19. Módulo de Ajuda Inteligente (UX Help System)

Este documento descreve a arquitetura de ajuda contextual da plataforma, desenhada para eliminar a dependência de suporte humano e orientar usuários (gestores públicos e pesquisadores) de forma didática e acionável.

## 🧭 Mapeamento de Ajuda Contextual (Tooltips)

As ajudas não apenas definem termos, mas explicam "o que fazer" e "como interpretar".

### 1. Seleção de Amostra Espacial
- **Quando usar:** Escolha "Ponto Central" se quiser focar em um projeto/propriedade local. Escolha "Município" se a análise for para gestão governamental ampla.
- **Possíveis Erros:** Se a API do IBGE falhar, o usuário é instruído a aguardar alguns minutos (timeout do órgão oficial).

### 2. Resultados das Métricas
- **Dica Prática (Índice de Shannon - SHDI):** "Quanto mais próximo de 0, mais dominada por uma única classe (ex: só pasto). Valores maiores indicam diversidade (ex: mata, água, pasto dividindo o espaço)."
- **Erro Comum:** Falha no MapBiomas por polígono muito pequeno. Solução orientada: "Aumente o raio do buffer ou faça upload de um GeoTIFF local de altíssima resolução."

### 3. Agrupamento (Matriz SSE)
- **Como Interpretar:** A curva do cotovelo mostra onde o gráfico 'quebra'. Esse é o número sugerido de grupos (clusters) sociodemográficos para seus dados.

## 📊 Níveis de Profundidade
1. **Básico (Iniciante):** Focado no gestor público. Linguagem sem jargões. Usa analogias.
2. **Intermediário:** Focado no analista de geoprocessamento. Explica recortes de buffer e limites municipais.
3. **Avançado:** Focado em pesquisadores. Acesso ao glossário completo do FRAGSTATS, detalhes sobre a matriz de transição de Markov e K-Means.

## ⚙️ Tratamento Amigável de Erros
- Erro: `Earth Engine API credentials missing`
  - *Mensagem Genérica:* Erro 401.
  - *Mensagem de Ajuda Inteligente:* "Parece que suas credenciais do Earth Engine não estão configuradas ou expiraram. Clique aqui para acessar as configurações e colar seu novo JSON."
