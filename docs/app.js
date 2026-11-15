/* Atest.AI — documentação interativa.
   Os dados da régua abaixo espelham config/rubric.toml (versão 2026-11-v9) e a conta de atest/score.py e
   atest/scoring.py. Se a régua mudar, atualize aqui. */

"use strict";

// ============================================================================ dados da régua
const WEIGHTS = { scope: 20, quote: 40, photos: 40 };
const DISCOUNT = { critical: 60, high: 35, medium: 15, low: 5 };
const FLOOR = 0.5; // proportional_floor: desconto = severidade × (piso + (1 − piso) × fração atingida)
const RELEVANT_PCT = 10; // relevant_amount_at_issue_pct: a partir daqui o valor em questão limita a nota de Orçamento
const RETURN_PCT = 30; // max_amount_at_issue_for_caveats_pct: a partir daqui devolve ao fornecedor
const APPROVE_PCT = 10; // max_amount_at_issue_for_approve_pct: acima disso "Aprovar" vira "Aprovar com ressalvas"
const SEV_LABEL = { critical: "crítica", high: "alta", medium: "média", low: "baixa" };
const VALIDATION_LABEL = { scope: "Escopo", quote: "Orçamento", photos: "Fotos" };
const AREA_LABEL = { scope: "Escopo", quote: "Orçamento", photos: "Fotos", docs: "Documentos" };
const CONFIDENCE = { medium: 1, low: 2 }; // nº de redutores de confiança
const BANDS = [
  { min: 85, reco: "approve" },
  { min: 70, reco: "approve_with_caveats" },
  { min: 0, reco: "return_to_supplier" },
];
const RECO = {
  approve: "Aprovar",
  approve_with_caveats: "Aprovar com ressalvas",
  return_to_supplier: "Devolver ao fornecedor",
  return_locked: "Devolver (trava de integridade)",
  detailed_review: "Análise detalhada",
  checklist_returned: "Devolvido: checklist incompleto",
};
const BAND_REASON = {
  approve: "Score de 85 ou mais, sem travas",
  approve_with_caveats: "Score entre 70 e 84",
  return_to_supplier: "Score abaixo de 70, com apontamentos",
};
// redutores de confiança que não são apontamentos (vêm das etapas quando algo não pôde ser lido)
const EXTRA_REDUCERS = {
  unreadable_quote: "orçamento não lido",
  photos_not_analyzed: "fotos não analisadas pelo modelo",
  documents_not_analyzed: "documentos não lidos pelo modelo",
};
// a que o desconto é proporcional (extent) e a fração sugerida ao marcar o apontamento no simulador
const EXTENT = {
  value: { label: "do orçamento", short: "valor", def: 10 },
  photos: { label: "das fotos", short: "fotos", def: 33 },
  items: { label: "dos itens a conferir", short: "itens", def: 50 },
  documents: { label: "dos documentos", short: "documentos", def: 100 },
  services: { label: "dos serviços pedidos", short: "serviços pedidos", def: 50 },
  whole: { label: "", short: "chamado inteiro", def: 100 },
};

// who: "ai" = o modelo aponta; "rule" = regra determinística; "mix" = o modelo lê, a regra confirma/calcula
// moment: "execution" = só no retorno após a execução; "quote" = só na aprovação do orçamento; vazio = nos dois
const FINDINGS = {
  vague_scope: {
    v: "scope", area: "scope", sev: "high", phase: 1, extent: "whole", reducer: true, amount: "—", who: "ai",
    label: "Escopo vago ou sem ambiente definido",
    how: "O modelo lê o escopo e responde se dá para saber o que fazer, onde e em quê. Severidade alta: escopo vago impede conferir orçamento e fotos.",
  },
  inconsistent_scope: {
    v: "scope", area: "scope", sev: "medium", phase: 1, extent: "whole", reducer: true, amount: "—", who: "ai",
    label: "Escopo incoerente com a categoria ou o sintoma",
    how: "O modelo compara o texto do escopo com a categoria e o sintoma informados.",
  },
  scope_not_quoted: {
    v: "scope", area: "scope", sev: "critical", phase: 1, extent: "services", returns: true, amount: "—", who: "ai",
    label: "Serviço pedido no chamado sem item no orçamento",
    how: "Para cada serviço pedido (escopo ou descrição da solução), o modelo diz que itens o executam. Sem item: apontamento. Coberto só em parte conta metade e vira observação. Mão de obra, visita e deslocamento não contam como serviço.",
  },
  service_before_approval: {
    v: "scope", area: "docs", sev: "high", phase: 1, extent: "whole", moment: "quote", amount: "—", who: "mix",
    label: "Serviço executado antes da aprovação do orçamento",
    how: "Só na aprovação do orçamento: um documento anexado afirma com verbo no passado que o serviço já foi feito (“foi instalada”, termo assinado), com data até o envio.",
  },
  out_of_scope_item: {
    v: "quote", area: "quote", sev: "high", phase: 1, extent: "value", returns: true, amount: "item inteiro", who: "ai",
    label: "Item fora do escopo",
    how: "O modelo classifica o item como fora do escopo (serviço, local ou equipamento não pedido).",
  },
  unjustified_replacement: {
    v: "quote", area: "quote", sev: "high", phase: 1, extent: "value", amount: "item inteiro", who: "ai",
    label: "Troca ou peça sem justificativa técnica",
    how: "O modelo classifica o item como “a justificar” (troca quando o pedido era ajuste, limpeza ou reparo, sem laudo).",
  },
  duplicate_item: {
    v: "quote", area: "quote", sev: "high", phase: 1, extent: "value", returns: true, amount: "item inteiro", who: "mix",
    label: "Item cobrado em duplicidade",
    how: "O modelo indica a linha repetida; a regra também procura linhas com mesma unidade, quantidade e preço e descrição ≥ 80% parecida.",
  },
  quantity_above_expected: {
    v: "quote", area: "quote", sev: "medium", phase: 1, extent: "value", amount: "excedente", who: "mix",
    label: "Quantidade acima do esperado",
    how: "O modelo estima a quantidade máxima plausível pelo escopo; a regra calcula o excedente em R$.",
  },
  unverifiable_quantity: {
    v: "quote", area: "quote", sev: "medium", phase: 1, extent: "value", reducer: true, amount: "item inteiro", who: "mix",
    label: "Quantidade não verificável pelo escopo",
    how: "O modelo diz que o escopo não permite estimar a quantidade. Não é “acima”, é “não dá para conferir”.",
  },
  price_above_reference: {
    v: "quote", area: "quote", sev: "medium", phase: 1, extent: "value", amount: "excedente", who: "mix",
    label: "Preço acima da referência",
    how: "O modelo só indica o código equivalente na LPU; a regra compara: acima de referência + 10% vira apontamento.",
  },
  price_above_market: {
    v: "quote", area: "docs", sev: "medium", phase: 1, extent: "value", amount: "excedente", who: "mix",
    label: "Preço acima do valor de mercado apresentado em documento",
    how: "O modelo lê o preço num print de anúncio ou cotação anexado e liga ao item; a regra aponta acima de mercado + 25%. Não repete o que a LPU já pegou.",
  },
  quantity_above_photos: {
    v: "quote", area: "photos", sev: "medium", phase: 1, extent: "value", amount: "excedente", who: "mix",
    label: "Quantidade cobrada acima do que as fotos mostram",
    how: "O modelo conta nas fotos (peças, luminárias, área pelo tamanho das peças); a regra aponta o que passa de 25% acima da contagem.",
  },
  spreadsheet_mismatch: {
    v: "quote", area: "quote", sev: "medium", phase: 1, extent: "whole", amount: "—", who: "rule",
    label: "Planilha divergente do chamado",
    how: "Regra: nº do chamado, categoria, sintoma, escopo e valor total (tolerância de R$ 1,00) da planilha × chamado.",
  },
  relevant_amount_at_issue: {
    v: "quote", area: "quote", sev: "medium", phase: 1, extent: "value", auto: true, amount: "—", who: "rule",
    label: "Valor potencial divergente relevante no orçamento",
    how: "Automático: com 10% ou mais do orçamento em questão, a nota de Orçamento fica limitada a 100 − % em questão. Desconta só o que falta para o teto.",
  },
  photo_mismatch: {
    v: "photos", area: "photos", sev: "high", phase: 1, extent: "photos", amount: "—", who: "ai",
    label: "Foto não corresponde ao escopo",
    how: "O modelo de visão diz que uma foto legível mostra outro ambiente, equipamento ou local.",
  },
  missing_after_photo: {
    v: "photos", area: "photos", sev: "high", phase: 1, extent: "whole", moment: "execution", absorbs: ["photo_mismatch"], amount: "—", who: "ai",
    label: "Sem foto do serviço concluído",
    how: "Só na execução: nenhuma foto legível comprova o RESULTADO pedido. Absorve a “foto de outro ambiente” (mesmo problema visto por outro ângulo).",
  },
  after_photo_unconfirmed_location: {
    v: "photos", area: "photos", sev: "medium", phase: 1, extent: "whole", moment: "execution", reducer: true, amount: "—", who: "ai",
    label: "Foto do depois sem local confirmado",
    how: "Só na execução: a foto mostra o resultado, mas não dá para confirmar o local (um forro é igual ao outro). Não é “sem foto”: a pessoa confere.",
  },
  item_without_photo: {
    v: "photos", area: "photos", sev: "medium", phase: 1, extent: "items", moment: "execution", amount: "—", who: "ai",
    label: "Item cobrado sem evidência fotográfica",
    how: "Só na execução: itens físicos cobrados que nenhuma foto mostra (inclusive quando as fotos mostram menos unidades). Um apontamento lista todos.",
  },
  missing_before_photo: {
    v: "photos", area: "photos", sev: "medium", phase: 2, extent: "whole", amount: "—", who: "ai",
    label: "Sem foto do “antes”",
    how: "Quando a leitura do escopo diz que o “antes” se aplica (reparo, troca, pintura) e o modelo não acha foto do estado anterior.",
  },
  unreadable_photo: {
    v: "photos", area: "photos", sev: "low", phase: 2, extent: "photos", reducer: true, amount: "—", who: "ai",
    label: "Foto ilegível",
    how: "O modelo marca a foto como ilegível (escura, tremida, sem foco).",
  },
  photo_dated_before: {
    v: "photos", area: "photos", sev: "medium", phase: 2, extent: "photos", amount: "—", who: "rule",
    label: "Foto com data anterior à abertura do chamado",
    how: "Regra: data EXIF da foto anterior à abertura do chamado (tolerância de 1 dia).",
  },
  reused_photo: {
    v: "photos", area: "photos", sev: "critical", phase: 2, extent: "whole", lock: true, amount: "—", who: "rule",
    label: "Foto reaproveitada de outro chamado",
    how: "Regra: hash perceptual (phash + dhash) próximo de foto de chamado anterior, também comparando com recortes da foto antiga.",
  },
  unreadable_document: {
    v: "photos", area: "docs", sev: "low", phase: 1, extent: "documents", reducer: true, amount: "—", who: "ai",
    label: "Documento ilegível",
    how: "O modelo não consegue ler o documento (foto de papel, manuscrito ou PDF).",
  },
  document_mismatch: {
    v: "photos", area: "docs", sev: "high", phase: 1, extent: "documents", amount: "—", who: "ai",
    label: "Documento não corresponde ao chamado",
    how: "Algo ESCRITO no documento contradiz o chamado: outra agência, outro serviço, outro equipamento. Documento genérico não conta.",
  },
  document_date_inconsistent: {
    v: "photos", area: "docs", sev: "medium", phase: 2, extent: "documents", amount: "—", who: "mix",
    label: "Data do documento fora do período do chamado",
    how: "O modelo transcreve a data do atendimento; a regra confere se cai entre a abertura e o envio pelo fornecedor (± 1 dia).",
  },
};

// ============================================================================ jornada de um chamado
const STEPS = [
  {
    t: "Entrada", stage: "Antes da análise", who: ["human"], code: "data/tickets/&lt;id&gt;/ticket.json · atest/repository.py",
    what: "A agência abre o chamado com <b>categoria</b> e <b>sintoma</b> (do cadastro, como no Salesforce), <b>local</b> e <b>escopo</b> em texto livre; opcionalmente, a <b>descrição da solução</b> e se o problema <b>impede a abertura da agência</b>. O fornecedor envia o <b>orçamento</b> (planilha Excel padrão), <b>fotos</b> e <b>documentos</b> (termo, relatório manuscrito, laudo, print de preço). O chamado chega em um de dois momentos: <b>aprovação do orçamento</b> (antes de executar) ou <b>atestação da execução</b> (depois).",
    input: ["Chamado (esteira SETA/SISR, categoria, sintoma, local, escopo, datas, momento)", "Planilha Excel com abas Chamado e Itens", "Fotos e documentos, em imagem ou PDF"],
    output: ["Chamado carregado e validado (modelo Pydantic Ticket)"],
    example: "Chamado 00482193: “Repintura de paredes e teto do backoffice (aprox. 240 m²)”, momento execução. Orçamento de R$ 12.480 com 4 itens e 6 fotos.",
  },
  {
    t: "Checklist mínimo", stage: "Etapa 0 · triagem", who: ["rule", "ai"], code: "atest/checklist.py · config/checklists.toml",
    what: "Confere se chegaram as evidências obrigatórias para aquele tipo de serviço e momento. A planilha é lida por <b>regra</b>. Cada foto ou documento é <b>identificado pela IA</b> (o que é, se é antes ou depois, se dá para ler). A decisão completo/incompleto é <b>regra</b>.",
    input: ["Anexos do chamado", "Regras do checklist por esteira × categoria × tipo de manutenção × momento"],
    output: ["Lista de requisitos atendidos e faltantes", "Se faltar algo: devolução automática com mensagem ao fornecedor, <b>sem score</b>"],
    example: "Troca de 12 luminárias (00523310) sem foto do depois, sem foto das luminárias retiradas e sem termo assinado: devolvido no checklist, nem chega à pessoa analista.",
  },
  {
    t: "Escopo", stage: "Validação 1 · peso 20", who: ["ai"], code: "atest/scope.py · tarefa scope",
    what: "A IA traduz o texto livre em <b>critérios de aceite verificáveis</b>: local, ambiente, serviços pedidos, quantidades citadas, que evidência comprovaria o resultado e se faz sentido exigir foto do “antes”. Aponta escopo <b>vago</b> (severidade alta) ou <b>incoerente</b>. Os serviços pedidos viram a lista que o orçamento precisa cobrir.",
    input: ["Categoria, sintoma, local, escopo e descrição da solução"],
    output: ["Leitura estruturada do escopo (contexto das etapas seguintes)", "Apontamentos possíveis: escopo vago, escopo incoerente"],
    example: "“Verificar porta. Urgente.” (00533402) é vago: qual porta? qual defeito? Vira apontamento alto e reduz a confiança.",
  },
  {
    t: "Orçamento", stage: "Validação 2 · peso 40", who: ["ai", "rule"], code: "atest/quote.py · tarefa quote_review",
    what: "Com o olhar de engenheiro, a IA confere duas coisas: <b>serviço a serviço</b>, se cada serviço pedido tem item que o executa (sem item = falta do fornecedor); e <b>item a item</b>, se o que foi cobrado tem relação com o pedido (aderente, fora do escopo, a justificar), a quantidade máxima plausível e o código equivalente na <b>LPU</b>. As <b>regras</b> comparam preço com a LPU, procuram duplicidade, conferem planilha × chamado e calculam o <b>valor em questão</b>.",
    input: ["Itens da planilha", "Leitura do escopo e lista de serviços pedidos", "LPU da esteira (SETA ou SISR)"],
    output: ["Cobertura de cada serviço pedido", "Cada item classificado, com motivo", "Apontamentos de orçamento e valor em questão (R$ e %)"],
    example: "Caso 04159084 (aprovação do orçamento): o chamado pede proteger o quadro, organizar a fiação e desativar uma medição; o orçamento só traz a chapa de acrílico. Dois de três serviços sem item: devolver ao fornecedor.",
  },
  {
    t: "Fotos", stage: "Validação 3 · peso 40", who: ["ai", "rule"], code: "atest/photos.py · tarefa photos",
    what: "A IA olha <b>foto a foto</b> (onde foi tirada, o que mostra, antes ou depois, se é legível, se corresponde ao escopo), <b>conta</b> nas fotos os itens físicos cobrados (peças, luminárias, área) e diz se o resultado está comprovado: <b>sim</b>, <b>em parte</b>, <b>não</b> ou <b>não dá para confirmar</b>. As <b>regras de integridade</b> conferem a data da foto (EXIF) e se ela é cópia de foto de outro chamado (hash perceptual). Se o modelo falhar, tenta de novo e, com muitas fotos, em lotes de 6; sem leitura, o chamado segue com redutor de confiança.",
    input: ["Fotos do chamado", "Leitura do escopo e itens do orçamento", "Índice de fotos de chamados anteriores"],
    output: ["Leitura de cada foto e contagem por item", "Apontamentos de fotos e de integridade"],
    example: "Caso 04164650 (piso quebrado): as fotos somam 9 peças, cerca de 3,2 m², contra 4,6 m² cobrados em demolição, piso e rejunte: quantidade acima do que as fotos mostram.",
  },
  {
    t: "Documentos", stage: "Validação 3 · leitura por OCR", who: ["ai", "rule"], code: "atest/documents.py · tarefa documents",
    what: "A IA <b>transcreve</b> cada documento anexado, inclusive manuscrito ou em PDF, e extrai data e horário do atendimento, agência, problema, solução, assinatura e preços. As regras apontam documento ilegível, de outro chamado, com data fora da janela do chamado, <b>preço de mercado</b> abaixo do cobrado e, na aprovação do orçamento, <b>serviço já executado</b> antes da aprovação.",
    input: ["PDFs e fotos identificadas como documento", "Chamado e itens do orçamento (para ligar preço a item)"],
    output: ["Transcrição e campos lidos de cada documento", "Divergências com o chamado", "Apontamentos de documentos"],
    example: "Em 04159084, o fornecedor anexou um print de anúncio com o preço da chapa: o item 1 foi cobrado acima do valor de mercado mais a tolerância de 25%.",
  },
  {
    t: "Score", stage: "Régua", who: ["rule"], code: "atest/score.py · atest/scoring.py · config/rubric.toml",
    what: "A <b>régua</b> transforma os apontamentos em nota por validação, score de 0 a 100, nível de confiança e recomendação. <b>O modelo não dá nota.</b> O desconto é <b>proporcional</b> ao que o problema atinge (1 foto ruim em 6 pesa menos que 6 em 6), o valor em questão <b>limita</b> a nota de Orçamento e faltas do fornecedor <b>devolvem</b> o chamado qualquer que seja a nota.",
    input: ["Todos os apontamentos", "O que foi enviado (fotos, itens, documentos, serviços pedidos, valor)", "Régua da esteira (pesos 20/40/40, severidades, faixas 85/70)"],
    output: ["Notas, score, confiança, recomendação e motivo"],
    example: "00482193: escopo 100, orçamento 70, fotos 59 → score 72. Como há item fora do escopo (falta do fornecedor), a recomendação é Devolver.",
  },
  {
    t: "Parecer", stage: "Redação", who: ["ai"], code: "atest/assessment.py · tarefa assessment",
    what: "A IA <b>redige</b> o parecer como o engenheiro que aprova o orçamento explicaria: recomendação, motivo principal, o <b>racional técnico</b> (cobertura de cada serviço, contagem nas fotos, preço × referência) e a mensagem ao fornecedor. Ela não muda a decisão. Se a redação falhar, um texto por regra é usado: o parecer nunca deixa de sair.",
    input: ["Resultado da régua, apontamentos, observações e racional técnico das etapas"],
    output: ["Resumo (3 a 4 frases)", "Mensagem ao fornecedor (uma ação por apontamento)"],
    example: "“Recomendo devolver ao fornecedor: o orçamento tem só a chapa de acrílico (item 1) e não traz item para organizar a fiação do quadro nem para desativar a medição, ambos pedidos no chamado.” (04159084)",
  },
  {
    t: "Pessoa analista", stage: "Depois da análise", who: ["human"], code: "panel/ · atest/api.py · tabelas feedbacks e finding_feedbacks",
    what: "Modo <b>copiloto</b>: no painel, a pessoa analista vê o parecer, a <b>conta do score explicada</b> e a evidência de cada apontamento, e decide. Pode <b>aceitar</b>, <b>ajustar</b> ou <b>discordar</b> do parecer e marcar cada apontamento como <b>procedente ou improcedente</b>; o painel refaz a conta sem o apontamento descartado. Tudo fica gravado e vira dado rotulado para a próxima validação.",
    input: ["Parecer com evidências"],
    output: ["Decisão final", "Feedback do parecer e de cada apontamento"],
    example: "Em 04159084, a pessoa analista marcou os dois apontamentos (serviço sem item e preço acima do mercado) como procedentes.",
  },
];

// ============================================================================ utilidades
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const brl = (v) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* sem armazenamento: segue sem lembrar */ } },
};
const WHO_PILL = { ai: '<span class="who ai">IA</span>', rule: '<span class="who rule">Regra</span>', human: '<span class="who human">Pessoa</span>', mix: '<span class="who mix">IA + regra</span>' };
// arredondamento do Python (round): empate vai para o par
function pyRound(x) {
  const f = Math.floor(x);
  const d = x - f;
  if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
  return Math.round(x);
}
const lower = (s) => s.charAt(0).toLowerCase() + s.slice(1);

// ============================================================================ tema
function initTheme() {
  const btn = $("#theme-btn");
  const saved = store.get("atest-doc-theme");
  if (saved) document.documentElement.dataset.theme = saved;
  const label = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    btn.textContent = dark ? "☀︎ Claro" : "☾ Escuro";
    return dark;
  };
  label();
  btn.addEventListener("click", () => {
    const next = label() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set("atest-doc-theme", next);
    label();
  });
}

// ============================================================================ papéis (filtro de leitura)
const ROLE_NAME = { exec: "Executivo", prod: "Produto", ds: "Ciência de dados", eng: "Engenharia" };

function initRoles() {
  const buttons = $$(".role-btn");
  const sections = $$("section.doc");
  const banner = $("#role-banner");
  const apply = (role, scrollTop) => {
    let shown = 0;
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.role === role)));
    sections.forEach((s) => {
      const hide = role !== "all" && !(s.dataset.roles || "").split(" ").includes(role);
      if (!hide) shown++;
      s.classList.toggle("hidden-by-role", hide);
      const link = $(`#nav-links a[href="#${s.id}"]`);
      if (link) link.classList.toggle("hidden-by-role", hide);
    });
    $$(".reading-path").forEach((p) => p.classList.toggle("show", p.dataset.for === role));
    banner.hidden = role === "all";
    if (role !== "all") {
      $("[data-banner-text]", banner).innerHTML = `Mostrando <b>${shown}</b> de ${sections.length} seções para <b>${ROLE_NAME[role]}</b>.`;
    }
    refreshNavGroups();
    store.set("atest-doc-role", role);
    if (scrollTop) scrollTo({ top: 0, behavior: "smooth" });
  };
  buttons.forEach((b) => b.addEventListener("click", () => apply(b.dataset.role, true)));
  $("#role-reset").addEventListener("click", () => apply("all", false));
  $$("[data-go-role]").forEach((c) =>
    c.addEventListener("click", () => {
      apply(c.dataset.goRole, false);
      $(`.reading-path[data-for="${c.dataset.goRole}"]`).scrollIntoView({ behavior: "smooth", block: "center" });
    })
  );
  apply(store.get("atest-doc-role") || "all", false);
}

// esconde os títulos de grupo do sumário quando nenhum link do grupo está visível
function refreshNavGroups() {
  let label = null;
  let visible = 0;
  let total = 0;
  const close = () => label && label.classList.toggle("empty", visible === 0);
  $$("#nav-links > *").forEach((el) => {
    if (el.classList.contains("label")) {
      close();
      label = el;
      visible = 0;
    } else if (!el.classList.contains("hidden-by-role") && !el.classList.contains("no-match")) {
      visible++;
      total++;
    }
  });
  close();
  $("#nav-empty").classList.toggle("show", total === 0);
}

// ============================================================================ busca no sumário
function initSearch() {
  const input = $("#nav-search");
  const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const index = $$("#nav-links a").map((a) => {
    const section = document.getElementById(a.getAttribute("href").slice(1));
    return { a, text: norm(`${a.textContent} ${section ? section.textContent : ""}`) };
  });
  const visible = () => index.filter(({ a }) => !a.classList.contains("no-match") && !a.classList.contains("hidden-by-role"));
  input.addEventListener("input", () => {
    const words = norm(input.value.trim()).split(/\s+/).filter(Boolean);
    index.forEach(({ a, text }) => a.classList.toggle("no-match", words.length > 0 && !words.every((w) => text.includes(w))));
    refreshNavGroups();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const first = visible()[0];
      if (first) first.a.click();
    } else if (e.key === "Escape") {
      input.value = "";
      input.dispatchEvent(new Event("input"));
      input.blur();
    }
  });
  document.addEventListener("keydown", (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
    if ((e.key === "/" && !typing) || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) {
      e.preventDefault();
      document.body.classList.add("nav-open");
      input.focus();
      input.select();
    }
  });
}

// ============================================================================ pequenos auxílios de leitura
function toast(message) {
  const t = $("#toast");
  t.textContent = message;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 1600);
}

function initAnchors() {
  $$("section.doc").forEach((s) => {
    const h = $(".section-head h2", s);
    if (!h) return;
    const a = document.createElement("a");
    a.className = "anchor";
    a.href = `#${s.id}`;
    a.textContent = "#";
    a.setAttribute("aria-label", "Copiar o link desta seção");
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      history.replaceState(null, "", `#${s.id}`);
      s.scrollIntoView({ behavior: "smooth" });
      try {
        await navigator.clipboard.writeText(location.href);
        toast("Link da seção copiado");
      } catch {
        toast("O link está na barra de endereço");
      }
    });
    h.appendChild(a);
  });
}

function initScrollUi() {
  const bar = $("#read-progress");
  const top = $("#to-top");
  const onScroll = () => {
    const h = document.documentElement;
    const max = h.scrollHeight - h.clientHeight;
    bar.style.width = `${max > 0 ? (h.scrollTop / max) * 100 : 0}%`;
    top.classList.toggle("show", h.scrollTop > 700);
  };
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  top.addEventListener("click", () => scrollTo({ top: 0, behavior: "smooth" }));
}

function initTools() {
  const btn = $("#toggle-details");
  btn.addEventListener("click", () => {
    const all = $$("details.tech");
    const open = !all.every((d) => d.open);
    all.forEach((d) => (d.open = open));
    btn.textContent = open ? "Recolher detalhes técnicos" : "Expandir detalhes técnicos";
  });
  $("#print-btn").addEventListener("click", () => print());
  $("#nav-backdrop").addEventListener("click", () => document.body.classList.remove("nav-open"));
}

// ============================================================================ navegação
function initNav() {
  $("#menu-btn").addEventListener("click", () => document.body.classList.toggle("nav-open"));
  $$("#nav-links a").forEach((a) => a.addEventListener("click", () => document.body.classList.remove("nav-open")));

  const links = new Map($$("#nav-links a").map((a) => [a.getAttribute("href").slice(1), a]));
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        links.forEach((a) => a.classList.remove("active"));
        const a = links.get(e.target.id);
        if (a) a.classList.add("active");
      });
    },
    { rootMargin: "-20% 0px -70% 0px" }
  );
  $$("section.doc").forEach((s) => observer.observe(s));
}

// ============================================================================ blocos de código
function initCopy() {
  $$("pre").forEach((pre) => {
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.type = "button";
    btn.textContent = "copiar";
    btn.addEventListener("click", async () => {
      const text = pre.innerText.replace(/copiar$|copiado$/, "").trim();
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = "copiado";
      } catch {
        btn.textContent = "não copiou";
      }
      setTimeout(() => (btn.textContent = "copiar"), 1400);
    });
    pre.appendChild(btn);
  });
}

// ============================================================================ jornada
let showStep = () => {};

function initJourney() {
  const bar = $("#stepper");
  const detail = $("#step-detail");
  const progress = $("#step-progress > span");
  const buttons = STEPS.map((s, i) => {
    const b = document.createElement("button");
    b.className = "step";
    b.type = "button";
    b.id = `step-tab-${i}`;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-controls", "step-detail");
    b.innerHTML = `<span class="num">${i + 1}</span><span class="t">${s.t}</span><span class="pills">${s.who.map((w) => WHO_PILL[w]).join("")}</span>`;
    b.addEventListener("click", () => show(i));
    bar.appendChild(b);
    return b;
  });

  // setas do teclado entre os passos (padrão de abas)
  bar.addEventListener("keydown", (e) => {
    const i = buttons.indexOf(document.activeElement);
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: STEPS.length - 1 }[e.key];
    if (i < 0 || next === undefined || next < 0 || next >= STEPS.length) return;
    e.preventDefault();
    show(next);
    buttons[next].focus();
  });

  function show(i) {
    const s = STEPS[i];
    const prev = STEPS[i - 1];
    const next = STEPS[i + 1];
    buttons.forEach((b, j) => {
      b.setAttribute("aria-selected", String(i === j));
      b.tabIndex = i === j ? 0 : -1;
      b.classList.toggle("done", j < i);
    });
    progress.style.width = `${((i + 1) / STEPS.length) * 100}%`;
    detail.setAttribute("aria-labelledby", `step-tab-${i}`);
    detail.innerHTML = `
      <div class="card step-card">
        <div class="meta"><span class="stage-tag">${s.stage}</span>${s.who.map((w) => WHO_PILL[w]).join("")}<code>${s.code}</code></div>
        <h3>${s.t}</h3>
        <p>${s.what}</p>
        <div class="io">
          <div class="card"><h5>Entra</h5><ul>${s.input.map((x) => `<li>${x}</li>`).join("")}</ul></div>
          <div class="card"><h5>Sai</h5><ul>${s.output.map((x) => `<li>${x}</li>`).join("")}</ul></div>
        </div>
        <div class="callout info"><strong>Exemplo</strong><p>${s.example}</p></div>
        <nav class="step-nav" aria-label="Navegar entre os passos">
          ${prev ? `<button type="button" class="step-nav-btn" data-step="${i - 1}"><span class="dir">← Anterior</span><span class="name">${prev.t}</span></button>` : "<span></span>"}
          <span class="step-count">Passo ${i + 1} de ${STEPS.length}</span>
          ${next ? `<button type="button" class="step-nav-btn next" data-step="${i + 1}"><span class="dir">Próximo →</span><span class="name">${next.t}</span></button>` : "<span></span>"}
        </nav>
      </div>`;
    $$("[data-step]", detail).forEach((b) => b.addEventListener("click", () => show(Number(b.dataset.step))));
  }
  showStep = show;
  show(0);
}

// fluxo resumido no topo da página: atalho para cada passo da jornada
function initHeroFlow() {
  const box = $("#hero-flow");
  STEPS.forEach((s, i) => {
    if (i) box.insertAdjacentHTML("beforeend", '<span class="sep" aria-hidden="true">→</span>');
    const kind = s.who.includes("ai") && s.who.includes("rule") ? "mix" : s.who[0];
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = `<i class="dot ${kind}"></i>${s.t}`;
    b.addEventListener("click", () => {
      showStep(i);
      $("#jornada").scrollIntoView();
    });
    box.appendChild(b);
  });
}

// ============================================================================ tabela de apontamentos
function flagBadges(f) {
  const out = [];
  if (f.lock) out.push('<span class="flag lock">trava</span>');
  if (f.returns) out.push('<span class="flag ret">devolve</span>');
  if (f.reducer) out.push('<span class="flag red">reduz confiança</span>');
  if (f.absorbs) out.push('<span class="flag abs">absorve “foto não corresponde”</span>');
  if (f.moment === "execution") out.push('<span class="flag mom">só execução</span>');
  if (f.moment === "quote") out.push('<span class="flag mom">só aprovação do orçamento</span>');
  if (f.phase === 2) out.push('<span class="flag ph">fase 2</span>');
  if (f.auto) out.push('<span class="flag ph">automático</span>');
  return out.join(" ");
}

function initFindingsTable() {
  const tbody = $("#findings-body");
  const state = { area: "all", who: "all" };
  $("#findings-count").textContent = Object.keys(FINDINGS).length;
  function render() {
    tbody.innerHTML = Object.entries(FINDINGS)
      .filter(([, f]) => (state.area === "all" || f.area === state.area) && (state.who === "all" || f.who === state.who))
      .map(
        ([k, f]) => `<tr>
          <td><b>${f.label}</b><br><code>${k.replace(/_/g, "_<wbr>")}</code></td>
          <td class="nowrap">${VALIDATION_LABEL[f.v]}${f.area === "docs" ? '<br><span class="small muted">documentos</span>' : ""}</td>
          <td class="nowrap"><span class="sev ${f.sev}">${SEV_LABEL[f.sev]}</span><br><span class="small muted">até −${DISCOUNT[f.sev]}</span></td>
          <td>${WHO_PILL[f.who]}</td>
          <td class="small">${f.how}<div class="flags">${flagBadges(f)}</div></td>
          <td class="small">${EXTENT[f.extent].short}${f.amount !== "—" ? `<br><span class="muted">em questão: ${f.amount}</span>` : ""}</td>
        </tr>`
      )
      .join("");
  }
  $$("[data-filter-area]").forEach((b) =>
    b.addEventListener("click", () => {
      state.area = b.dataset.filterArea;
      $$("[data-filter-area]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      render();
    })
  );
  $$("[data-filter-who]").forEach((b) =>
    b.addEventListener("click", () => {
      state.who = b.dataset.filterWho;
      $$("[data-filter-who]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      render();
    })
  );
  render();
}

// ============================================================================ simulador da régua (espelha atest/score.py e atest/scoring.py)
// selected: { tipo: fração atingida em % (ignorada nos tipos "whole") }
function applicable(k, phase, moment) {
  const f = FINDINGS[k];
  if (f.auto || f.phase > phase) return false;
  if (f.moment && f.moment !== moment) return false;
  return true;
}

function absorbedSet(kinds) {
  const present = new Set(kinds);
  const out = new Set();
  kinds.forEach((k) => (FINDINGS[k].absorbs || []).forEach((a) => present.has(a) && FINDINGS[a].v === FINDINGS[k].v && out.add(a)));
  return out;
}

function gradesOf(entries) {
  const absorbed = absorbedSet(entries.map((e) => e.kind));
  const disc = { scope: 0, quote: 0, photos: 0 };
  entries.forEach((e) => { if (!absorbed.has(e.kind)) disc[FINDINGS[e.kind].v] += e.discount; });
  const g = {};
  Object.keys(WEIGHTS).forEach((v) => (g[v] = Math.max(0, 100 - disc[v])));
  return { grades: g, absorbed };
}

function compute({ selected, phase, moment, checklistOk, extraReducers }) {
  if (!checklistOk) {
    return { reco: "checklist_returned", reason: "Checklist mínimo incompleto: o chamado volta ao fornecedor sem score e não segue para a pessoa analista.", score: null };
  }
  const kinds = Object.keys(selected).filter((k) => applicable(k, phase, moment));
  // desconto proporcional ao que o apontamento atinge
  const entries = kinds.map((k) => {
    const f = FINDINGS[k];
    const share = f.extent === "whole" ? 1 : Math.min(1, Math.max(0, selected[k] / 100));
    return { kind: k, share, discount: pyRound(DISCOUNT[f.sev] * (FLOOR + (1 - FLOOR) * share)) };
  });
  // valor em questão: soma das frações dos apontamentos medidos pelo valor (aproximação do cálculo item a item)
  const amountPct = Math.min(100, entries.filter((e) => FINDINGS[e.kind].extent === "value").reduce((a, e) => a + 100 * e.share, 0));
  // materialidade: a nota de Orçamento fica limitada a 100 − % em questão
  let cap = null;
  if (amountPct > 0 && amountPct >= RELEVANT_PCT) {
    cap = Math.max(0, pyRound(100 - amountPct));
    const gap = gradesOf(entries).grades.quote - cap;
    if (gap > 0) entries.push({ kind: "relevant_amount_at_issue", share: Math.min(1, amountPct / 100), discount: gap });
  }
  const { grades, absorbed } = gradesOf(entries);
  const totalW = Object.values(WEIGHTS).reduce((a, b) => a + b, 0);
  const score = pyRound(Object.keys(WEIGHTS).reduce((a, v) => a + grades[v] * WEIGHTS[v], 0) / totalW);
  const reducers = [...new Set([...entries.filter((e) => FINDINGS[e.kind].reducer).map((e) => e.kind), ...extraReducers])].sort();
  const confidence = reducers.length >= CONFIDENCE.low ? "low" : reducers.length >= CONFIDENCE.medium ? "medium" : "high";
  const reducerLabel = (k) => (FINDINGS[k] ? lower(FINDINGS[k].label) : EXTRA_REDUCERS[k]);
  const lock = entries.find((e) => FINDINGS[e.kind].lock);
  const gaps = [...new Set(entries.filter((e) => FINDINGS[e.kind].returns && !absorbed.has(e.kind)).map((e) => lower(FINDINGS[e.kind].label)))];
  let reco, reason;
  if (lock) {
    reco = "return_locked";
    reason = `Trava de integridade: ${lower(FINDINGS[lock.kind].label)}. Devolver qualquer que seja a nota.`;
  } else if (gaps.length) {
    reco = "return_to_supplier";
    reason = `O fornecedor precisa ajustar: ${gaps.join("; ")}.`;
  } else if (confidence === "low") {
    reco = "detailed_review";
    reason = `Confiança baixa (${reducers.map(reducerLabel).join("; ")}): entrada insuficiente para concluir.`;
  } else if (amountPct >= RETURN_PCT) {
    reco = "return_to_supplier";
    reason = `${pyRound(amountPct)}% do orçamento está em questão (a partir de ${RETURN_PCT}% volta ao fornecedor): o fornecedor precisa ajustar.`;
  } else {
    reco = BANDS.find((b) => score >= b.min).reco;
    if (reco === "approve" && amountPct > APPROVE_PCT) {
      reco = "approve_with_caveats";
      reason = `Score ${score}, mas ${pyRound(amountPct)}% do orçamento está em questão (acima de ${APPROVE_PCT}%)`;
    } else {
      reason = BAND_REASON[reco];
    }
    reason += confidence === "medium" ? "; confiança média: revisar com atenção." : ".";
  }
  return { grades, score, confidence, reducers, reco, reason, entries, absorbed, amountPct, cap, reducerLabel };
}

// casos reais: frações calculadas a partir dos itens, fotos e serviços de cada chamado (o resultado bate com o gabarito
// ou, nos casos 04…, com a análise feita pelo modelo real na versão atual)
const PRESETS = [
  {
    name: "Pintura do backoffice · 00482193", moment: "execution",
    selected: { out_of_scope_item: 25, quantity_above_expected: 2, photo_mismatch: 50, missing_before_photo: 100 },
  },
  {
    name: "Câmera com foto reaproveitada · 00517706", moment: "execution",
    selected: { unjustified_replacement: 57, out_of_scope_item: 32, reused_photo: 100, missing_after_photo: 100, photo_dated_before: 50 },
  },
  {
    name: "Ar-condicionado PMOC · 00531877", moment: "execution",
    selected: { quantity_above_expected: 13, price_above_reference: 4, missing_before_photo: 100 },
  },
  { name: "“Verificar porta. Urgente.” · 00533402", moment: "execution", selected: { vague_scope: 100, unreadable_photo: 33 } },
  { name: "Foto do depois de outro ambiente · 03000017", moment: "execution", selected: { missing_after_photo: 100, photo_mismatch: 33 } },
  { name: "Troca de câmera sem justificativa · 03000008", moment: "execution", selected: { unjustified_replacement: 83 } },
  { name: "Serviço pedido sem item · caso 04159084", moment: "quote", selected: { scope_not_quoted: 67, price_above_market: 27 } },
  { name: "Tudo certo · 00530121", moment: "execution", selected: {} },
  { name: "Checklist incompleto · 00523310", moment: "execution", selected: {}, checklistOk: false },
];

// lista de descontos aplicados: explica de onde vem cada nota
function deductionList(selected, r, phase, moment) {
  const kinds = Object.keys(selected);
  if (!kinds.length) return '<p class="small muted deductions-empty">Nenhum apontamento: as três notas ficam em 100.</p>';
  const byKind = new Map(r.entries.map((e) => [e.kind, e]));
  const rows = kinds.map((k) => {
    const f = FINDINGS[k];
    const e = byKind.get(k);
    let value;
    if (!e) {
      const why = f.phase > phase ? "ignorado na Fase 1" : f.moment === "execution" ? "não vale na aprovação do orçamento" : "só vale na aprovação do orçamento";
      value = `<span class="small muted">${why}</span>`;
    } else if (r.absorbed.has(k)) {
      value = '<span class="small muted">absorvido: não desconta</span>';
    } else {
      value = `<span class="sev ${f.sev}">−${e.discount}</span>`;
    }
    const share = e && f.extent !== "whole" ? ` <span class="muted">· ${pyRound(100 * e.share)}% ${EXTENT[f.extent].label}</span>` : "";
    return `<li class="${!e || r.absorbed.has(k) ? "off" : ""}"><span>${f.label} <span class="muted">· ${VALIDATION_LABEL[f.v]}</span>${share}</span>${value}</li>`;
  });
  const rel = byKind.get("relevant_amount_at_issue");
  if (rel) rows.push(`<li><span>${FINDINGS.relevant_amount_at_issue.label} <span class="muted">· teto ${r.cap} na nota de Orçamento</span></span><span class="sev medium">−${rel.discount}</span></li>`);
  return `<div class="deductions-title">Descontos aplicados</div><ul class="deductions">${rows.join("")}</ul>`;
}

function initSimulator() {
  const box = $("#sim-findings");
  const groups = [["scope", "Escopo · peso 20"], ["quote", "Orçamento · peso 40"], ["photos", "Fotos e documentos · peso 40"]];
  groups.forEach(([v, title]) => {
    const g = document.createElement("div");
    g.className = "group";
    g.innerHTML = `<div class="group-title">${title}</div>` +
      Object.entries(FINDINGS)
        .filter(([, f]) => f.v === v && !f.auto)
        .map(([k, f]) => {
          const ext = EXTENT[f.extent];
          const slider = f.extent === "whole" ? "" : `
            <div class="extent" hidden>
              <span class="small muted">Atinge</span>
              <input type="range" min="1" max="100" value="${ext.def}" data-extent="${k}" aria-label="Fração atingida: ${f.label}">
              <output class="small"><b>${ext.def}%</b> ${ext.label}</output>
            </div>`;
          return `<div class="check-row" data-k="${k}">
            <label class="check"><input type="checkbox" value="${k}"><span>${f.label}<span class="flags">${flagBadges(f)}</span></span><span class="sev ${f.sev}">até −${DISCOUNT[f.sev]}</span></label>${slider}
          </div>`;
        })
        .join("");
    box.appendChild(g);
  });

  const setExtent = (k, pct) => {
    const input = $(`input[data-extent="${k}"]`, box);
    if (!input) return;
    input.value = pct;
    input.nextElementSibling.innerHTML = `<b>${pct}%</b> ${EXTENT[FINDINGS[k].extent].label}`;
  };

  const presets = $("#sim-presets");
  PRESETS.forEach((p) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip-btn";
    b.textContent = p.name;
    b.addEventListener("click", () => {
      $$(".check input[type=checkbox]", box).forEach((c) => (c.checked = c.value in p.selected));
      Object.entries(p.selected).forEach(([k, pct]) => setExtent(k, pct));
      $("#sim-checklist").checked = p.checklistOk !== false;
      $$("#sim-extra input").forEach((c) => (c.checked = false));
      $("#sim-phase2").checked = true;
      $(`input[name="sim-moment"][value="${p.moment}"]`).checked = true;
      $$(".chip-btn", presets).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      update();
    });
    presets.appendChild(b);
  });

  function update() {
    const phase = $("#sim-phase2").checked ? 2 : 1;
    const moment = $('input[name="sim-moment"]:checked').value;
    const selected = {};
    $$(".check-row", box).forEach((row) => {
      const k = row.dataset.k;
      const on = $("input[type=checkbox]", row).checked;
      const ok = applicable(k, phase, moment);
      row.classList.toggle("disabled", !ok);
      const ext = $(".extent", row);
      if (ext) ext.hidden = !on || !ok;
      if (on) selected[k] = Number($(`input[data-extent="${k}"]`, row)?.value || 100);
    });
    const extraReducers = $$("#sim-extra input:checked").map((c) => c.value);
    const r = compute({ selected, phase, moment, checklistOk: $("#sim-checklist").checked, extraReducers });
    const out = $("#sim-out");
    if (r.score === null) {
      out.innerHTML = `<div class="score-big"><span class="v">—</span><span class="of">sem score</span></div>
        <div class="reco checklist_returned">${RECO[r.reco]}<small>${r.reason}</small></div>`;
      return;
    }
    const conf = { high: "alta", medium: "média", low: "baixa" }[r.confidence];
    const amount = r.amountPct > 0
      ? `<div class="small muted" style="margin-top:8px">Valor em questão: <b>${pyRound(r.amountPct)}% do orçamento</b>${r.cap !== null ? ` · teto da nota de Orçamento: ${r.cap}` : ""}</div>`
      : "";
    out.innerHTML = `
      <div class="score-big"><span class="v">${r.score}</span><span class="of">/ 100</span></div>
      <div class="small muted" style="margin:4px 0 10px">Confiança <b>${conf}</b>${r.reducers.length ? ` · redutores: ${r.reducers.map(r.reducerLabel).join("; ")}` : ""}</div>
      ${Object.keys(WEIGHTS).map((v) => `<div class="grade-row"><span>${VALIDATION_LABEL[v]} <span class="w">×${WEIGHTS[v]}</span></span><div class="bar"><span style="width:${r.grades[v]}%"></span></div><b class="num">${r.grades[v]}</b></div>`).join("")}
      ${amount}
      <div class="reco ${r.reco}">${RECO[r.reco]}<small>${r.reason}</small></div>
      <div class="formula">(${r.grades.scope}×20 + ${r.grades.quote}×40 + ${r.grades.photos}×40) ÷ 100 = ${r.score}</div>
      ${deductionList(selected, r, phase, moment)}`;
  }

  const clearPreset = () => $$(".chip-btn", presets).forEach((x) => x.setAttribute("aria-pressed", "false"));
  $("#simulator").addEventListener("change", (e) => {
    if (e.target.matches("input")) { clearPreset(); update(); }
  });
  box.addEventListener("input", (e) => {
    if (!e.target.matches("input[data-extent]")) return;
    setExtent(e.target.dataset.extent, e.target.value);
    clearPreset();
    update();
  });
  presets.firstChild.click();
}

// ============================================================================ calculadora de custo
function initCostCalc() {
  const vol = $("#calc-volume");
  const volN = $("#calc-volume-n");
  const per = $("#calc-per");
  const mode = $("#calc-mode");
  const out = $("#calc-out");
  const update = () => {
    const n = Math.max(0, Number(volN.value) || 0);
    const p = Math.max(0, Number(per.value) || 0);
    const factor = mode.value === "batch" ? 0.5 : 1;
    const ticket = p * factor;
    out.innerHTML = `
      <div class="row"><span>Custo por chamado</span><b>${brl(ticket)}</b></div>
      <div class="row"><span>Custo por mês (${n.toLocaleString("pt-BR")} chamados)</span><b>${brl(ticket * n)}</b></div>
      <div class="row"><span>Custo por ano</span><b>${brl(ticket * n * 12)}</b></div>
      <div class="row"><span>Tempo de análise por chamado (síncrono, medido)</span><b>39 a 76 s</b></div>`;
  };
  vol.addEventListener("input", () => { volN.value = vol.value; update(); });
  volN.addEventListener("input", () => { vol.value = Math.min(Number(vol.max), Number(volN.value) || 0); update(); });
  [per, mode].forEach((el) => el.addEventListener("input", update));
  update();
}

// ============================================================================ início
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initRoles();
  initSearch();
  initNav();
  initAnchors();
  initScrollUi();
  initTools();
  initCopy();
  initJourney();
  initHeroFlow();
  initFindingsTable();
  initSimulator();
  initCostCalc();
});
