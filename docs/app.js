/* Atest.AI — documentação interativa.
   Os dados da régua abaixo espelham config/rubric.toml (versão 2026-11-v3). Se a régua mudar, atualize aqui. */

"use strict";

// ============================================================================ dados da régua
const WEIGHTS = { scope: 20, quote: 40, photos: 40 };
const DISCOUNT = { critical: 60, high: 35, medium: 15, low: 5 };
const SEV_LABEL = { critical: "crítica", high: "alta", medium: "média", low: "baixa" };
const VALIDATION_LABEL = { scope: "Escopo", quote: "Orçamento", photos: "Fotos" };
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

// who: "ai" = o modelo aponta; "rule" = regra determinística; "mix" = o modelo lê, a regra confirma/calcula
const FINDINGS = {
  vague_scope: {
    v: "scope", sev: "medium", phase: 1, reducer: true, amount: "—", who: "ai",
    label: "Escopo vago ou sem ambiente definido",
    how: "O modelo lê o escopo e responde se dá para saber o que fazer, onde e em quê (campo vague_scope).",
  },
  inconsistent_scope: {
    v: "scope", sev: "medium", phase: 1, reducer: true, amount: "—", who: "ai",
    label: "Escopo incoerente com a categoria ou o sintoma",
    how: "O modelo compara o texto do escopo com a categoria e o sintoma informados (consistent_with_category_symptom).",
  },
  out_of_scope_item: {
    v: "quote", sev: "high", phase: 1, amount: "item inteiro", who: "ai",
    label: "Item fora do escopo",
    how: "O modelo classifica o item do orçamento como out_of_scope (serviço, local ou equipamento não pedido).",
  },
  unjustified_replacement: {
    v: "quote", sev: "high", phase: 1, amount: "item inteiro", who: "ai",
    label: "Troca ou peça sem justificativa técnica",
    how: "O modelo classifica o item como to_justify (troca quando o pedido era ajuste, limpeza ou reparo, sem laudo).",
  },
  duplicate_item: {
    v: "quote", sev: "high", phase: 1, amount: "item inteiro", who: "mix",
    label: "Item cobrado em duplicidade",
    how: "O modelo indica duplicate_of; a regra também procura linhas com mesma unidade, quantidade e preço e descrição ≥ 80% parecida.",
  },
  quantity_above_expected: {
    v: "quote", sev: "medium", phase: 1, amount: "excedente", who: "mix",
    label: "Quantidade acima do esperado",
    how: "O modelo estima a quantidade máxima plausível pelo escopo; a regra calcula o excedente em R$.",
  },
  price_above_reference: {
    v: "quote", sev: "medium", phase: 1, amount: "excedente", who: "mix",
    label: "Preço acima da referência",
    how: "O modelo só indica o código equivalente na LPU; a regra compara o preço: acima de referência + 10% vira apontamento.",
  },
  spreadsheet_mismatch: {
    v: "quote", sev: "medium", phase: 1, amount: "—", who: "rule",
    label: "Planilha divergente do chamado",
    how: "Regra: nº do chamado, categoria, sintoma, escopo e valor total (tolerância de R$ 1,00) da planilha × chamado.",
  },
  photo_mismatch: {
    v: "photos", sev: "high", phase: 1, amount: "—", who: "ai",
    label: "Foto não corresponde ao escopo",
    how: "O modelo de visão responde matches_scope = \"no\" para uma foto legível (outro ambiente, equipamento ou local).",
  },
  missing_after_photo: {
    v: "photos", sev: "high", phase: 1, amount: "—", who: "ai",
    label: "Sem foto do serviço concluído",
    how: "Só no momento “execução”: o modelo diz se alguma foto legível comprova o RESULTADO pedido, no local do escopo.",
  },
  missing_before_photo: {
    v: "photos", sev: "medium", phase: 2, amount: "—", who: "ai",
    label: "Sem foto do “antes”",
    how: "Quando a leitura do escopo diz que o “antes” se aplica (reparo, troca, pintura) e o modelo não acha foto do estado anterior.",
  },
  unreadable_photo: {
    v: "photos", sev: "low", phase: 2, reducer: true, amount: "—", who: "ai",
    label: "Foto ilegível",
    how: "O modelo marca a foto como ilegível (escura, tremida, sem foco).",
  },
  photo_dated_before: {
    v: "photos", sev: "medium", phase: 2, amount: "—", who: "rule",
    label: "Foto com data anterior à abertura do chamado",
    how: "Regra: data EXIF da foto anterior à abertura do chamado (tolerância de 1 dia).",
  },
  reused_photo: {
    v: "photos", sev: "critical", phase: 2, lock: true, amount: "—", who: "rule",
    label: "Foto reaproveitada de outro chamado",
    how: "Regra: hash perceptual (phash + dhash) próximo de foto de chamado anterior. Devolve qualquer que seja a nota.",
  },
};

const WHO_LABEL = { ai: "IA aponta", rule: "Regra", mix: "IA + regra" };

// ============================================================================ jornada de um chamado
const STEPS = [
  {
    t: "Entrada", who: ["human"], code: "data/tickets/&lt;id&gt;/ticket.json · atest/repository.py",
    what: "A agência abre o chamado com <b>categoria</b> (ex.: pintura, CFTV), <b>sintoma</b> (a queixa em uma expressão) e <b>escopo</b> em texto livre. O fornecedor executa e envia o <b>orçamento</b> (sempre na planilha Excel padrão) e as <b>fotos</b>. A pessoa gestora faz a primeira checagem e encaminha ao backoffice.",
    input: ["Chamado (categoria, sintoma, escopo, datas, esteira SETA/SISR)", "Planilha Excel com abas Chamado e Itens", "Fotos e documentos (termo, laudo)"],
    output: ["Chamado carregado e validado (modelo Pydantic Ticket)"],
    example: "Chamado 00482193: “Repintura de paredes e teto do backoffice (aprox. 240 m²)”. Orçamento de R$ 12.480 com 4 itens e 6 fotos.",
  },
  {
    t: "0 · Checklist mínimo", who: ["rule", "ai"], code: "atest/checklist.py · config/checklists.toml",
    what: "Confere se chegaram as evidências obrigatórias para aquele tipo de serviço. A planilha é lida por <b>regra</b>. Cada foto ou documento é <b>identificado pela IA</b> (o que é, se é antes ou depois, se dá para ler). A decisão completo/incompleto é <b>regra</b>.",
    input: ["Anexos do chamado", "Regras do checklist por categoria × tipo de manutenção × momento"],
    output: ["Lista de requisitos atendidos e faltantes", "Se faltar algo: devolução automática com mensagem ao fornecedor, <b>sem score</b>"],
    example: "Troca de 12 luminárias (00523310) sem foto do depois, sem foto das luminárias retiradas e sem termo assinado: devolvido no checklist, nem chega à pessoa analista.",
  },
  {
    t: "1 · Escopo", who: ["ai"], code: "atest/scope.py · tarefa scope",
    what: "A IA traduz o texto livre do escopo em <b>critérios de aceite verificáveis</b>: local, ambiente, serviços pedidos, quantidades citadas, que fotos comprovariam o resultado e se faz sentido exigir foto do “antes”. Também aponta escopo <b>vago</b> ou <b>incoerente</b>.",
    input: ["Categoria, sintoma e escopo do chamado"],
    output: ["Leitura estruturada do escopo (usada pelas etapas seguintes)", "Apontamentos possíveis: escopo vago, escopo incoerente"],
    example: "“Verificar porta. Urgente.” (00533402) é vago: qual porta? qual defeito? Vira apontamento e reduz a confiança.",
  },
  {
    t: "2 · Orçamento × escopo", who: ["ai", "rule"], code: "atest/quote.py · tarefa quote_review",
    what: "Item a item, a IA decide se o que foi cobrado tem relação com o que foi pedido (aderente, fora do escopo, a justificar), estima a quantidade máxima plausível e indica o código equivalente na tabela de preços de referência (<b>LPU</b>). As <b>regras</b> comparam preço com a LPU, procuram duplicidade, conferem planilha × chamado e calculam o <b>valor em questão</b>.",
    input: ["Itens da planilha", "Leitura do escopo", "LPU da esteira (SETA ou SISR)"],
    output: ["Cada item classificado, com motivo", "Apontamentos de orçamento", "Valor em questão (R$ e % do orçamento)"],
    example: "Em 00482193, “pintura de fachada” (R$ 3.150) está fora do escopo (o pedido era interno) e a massa corrida veio com 320 m² para uma área de 240 m² (excedente de R$ 232,50).",
  },
  {
    t: "3 · Evidências fotográficas", who: ["ai", "rule"], code: "atest/photos.py · tarefa photos",
    what: "A IA olha <b>foto a foto</b>: onde foi tirada, o que mostra, se é antes ou depois, se é legível e se corresponde ao escopo; e no conjunto, se alguma foto comprova o serviço concluído. As <b>regras de integridade</b> conferem a data da foto (EXIF) e se ela é cópia de foto de outro chamado (hash perceptual).",
    input: ["Fotos do chamado", "Leitura do escopo e itens do orçamento", "Índice de fotos de chamados anteriores"],
    output: ["Leitura de cada foto", "Apontamentos de fotos e de integridade"],
    example: "Em 00517706 (câmera desfocada), duas fotos eram cópias de fotos de outro chamado, aberto em junho: trava de integridade, devolve qualquer que seja a nota.",
  },
  {
    t: "4 · Score", who: ["rule"], code: "atest/score.py · atest/scoring.py · config/rubric.toml",
    what: "A <b>régua</b> transforma os apontamentos em nota por validação (escopo, orçamento, fotos), score de 0 a 100, nível de confiança e recomendação. <b>O modelo não dá nota.</b> Mudar pesos, faixas ou descontos é mudar um arquivo de configuração, sem tocar no código.",
    input: ["Todos os apontamentos", "Régua (pesos 20/40/40, descontos por severidade, faixas 85/70)"],
    output: ["Notas, score, confiança, recomendação e motivo"],
    example: "00482193: escopo 100, orçamento 50, fotos 50 → score 60 → Devolver ao fornecedor.",
  },
  {
    t: "5 · Parecer", who: ["ai"], code: "atest/assessment.py · tarefa assessment",
    what: "A IA <b>redige</b> o resumo para a pessoa analista e a mensagem ao fornecedor a partir do resultado da régua. Ela não muda a decisão. Se a redação falhar, um texto por regra é usado: o parecer nunca deixa de sair.",
    input: ["Resultado da régua e apontamentos"],
    output: ["Resumo (2 a 3 frases)", "Mensagem ao fornecedor (uma ação por apontamento)"],
    example: "“Remover o item 3 (pintura de fachada), que está fora do escopo; justificar ou ajustar a quantidade do item 4; substituir as fotos que não mostram o backoffice; enviar foto do estado anterior.”",
  },
  {
    t: "Pessoa analista", who: ["human"], code: "panel/ · atest/api.py · tabela feedbacks",
    what: "Modo <b>copiloto</b>: a pessoa analista vê o parecer, as evidências e o motivo de cada apontamento no painel e decide. Ela pode <b>aceitar</b>, <b>ajustar</b> ou <b>discordar</b>; o feedback fica gravado e vira dado rotulado para a próxima validação.",
    input: ["Parecer com evidências"],
    output: ["Decisão final", "Feedback (aceitar, ajustar, discordar, apontamentos indevidos)"],
    example: "A recomendação é sempre uma sugestão. A decisão é da pessoa.",
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
function initRoles() {
  const buttons = $$(".role-btn");
  const apply = (role) => {
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.role === role)));
    $$("section.doc").forEach((s) => {
      const roles = (s.dataset.roles || "").split(" ");
      const hide = role !== "all" && !roles.includes(role);
      s.classList.toggle("hidden-by-role", hide);
      const link = $(`.sidebar a[href="#${s.id}"]`);
      if (link) link.classList.toggle("hidden-by-role", hide);
    });
    $$(".reading-path").forEach((p) => p.classList.toggle("show", p.dataset.for === role));
    store.set("atest-doc-role", role);
  };
  buttons.forEach((b) => b.addEventListener("click", () => apply(b.dataset.role)));
  $$("[data-go-role]").forEach((c) =>
    c.addEventListener("click", () => {
      apply(c.dataset.goRole);
      $("#papeis").scrollIntoView();
    })
  );
  apply(store.get("atest-doc-role") || "all");
}

// ============================================================================ navegação
function initNav() {
  $("#menu-btn").addEventListener("click", () => document.body.classList.toggle("nav-open"));
  $$(".sidebar a").forEach((a) => a.addEventListener("click", () => document.body.classList.remove("nav-open")));

  const links = new Map($$(".sidebar a").map((a) => [a.getAttribute("href").slice(1), a]));
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
function initJourney() {
  const bar = $("#stepper");
  const detail = $("#step-detail");
  STEPS.forEach((s, i) => {
    const b = document.createElement("button");
    b.className = "step";
    b.type = "button";
    b.setAttribute("role", "tab");
    b.innerHTML = `<span class="n">PASSO ${i + 1}</span><span class="t">${s.t}</span>${s.who.map((w) => WHO_PILL[w]).join(" ")}`;
    b.addEventListener("click", () => show(i));
    bar.appendChild(b);
  });
  function show(i) {
    const s = STEPS[i];
    $$(".step", bar).forEach((b, j) => b.setAttribute("aria-selected", String(i === j)));
    detail.innerHTML = `
      <div class="card">
        <div class="meta">${s.who.map((w) => WHO_PILL[w]).join(" ")} <code>${s.code}</code></div>
        <h3 style="margin-top:0">${s.t}</h3>
        <p>${s.what}</p>
        <div class="io">
          <div class="card"><h5>Entra</h5><ul>${s.input.map((x) => `<li>${x}</li>`).join("")}</ul></div>
          <div class="card"><h5>Sai</h5><ul>${s.output.map((x) => `<li>${x}</li>`).join("")}</ul></div>
        </div>
        <div class="callout info"><strong>Exemplo</strong><p>${s.example}</p></div>
        <div class="small muted">${i > 0 ? `<a href="#" data-step="${i - 1}">← ${STEPS[i - 1].t}</a>` : ""}
          ${i < STEPS.length - 1 ? `<span style="float:right"><a href="#" data-step="${i + 1}">${STEPS[i + 1].t} →</a></span>` : ""}</div>
      </div>`;
    $$("[data-step]", detail).forEach((a) =>
      a.addEventListener("click", (e) => {
        e.preventDefault();
        show(Number(a.dataset.step));
      })
    );
  }
  show(0);
}

// ============================================================================ tabela de apontamentos
function initFindingsTable() {
  const tbody = $("#findings-body");
  const state = { v: "all", who: "all" };
  function render() {
    tbody.innerHTML = Object.entries(FINDINGS)
      .filter(([, f]) => (state.v === "all" || f.v === state.v) && (state.who === "all" || f.who === state.who))
      .map(
        ([k, f]) => `<tr>
          <td><b>${f.label}</b><br><code>${k}</code></td>
          <td>${VALIDATION_LABEL[f.v]}</td>
          <td><span class="sev ${f.sev}">${SEV_LABEL[f.sev]}</span></td>
          <td class="num">−${DISCOUNT[f.sev]}</td>
          <td>${WHO_PILL[f.who]}</td>
          <td class="small">${f.how}${f.lock ? " <b>Trava.</b>" : ""}${f.reducer ? " <b>Reduz a confiança.</b>" : ""}</td>
          <td class="nowrap">${f.phase === 2 ? "Fase 2" : "Fase 1"}</td>
          <td class="nowrap small">${f.amount}</td>
        </tr>`
      )
      .join("");
  }
  $$("[data-filter-v]").forEach((b) =>
    b.addEventListener("click", () => {
      state.v = b.dataset.filterV;
      $$("[data-filter-v]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
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

// ============================================================================ simulador da régua (espelha atest/score.py)
function compute({ findings, phase, checklistOk, unreadableQuote }) {
  if (!checklistOk) {
    return { reco: "checklist_returned", reason: "Checklist mínimo incompleto: o chamado volta ao fornecedor sem score e não segue para a pessoa analista.", score: null };
  }
  const active = findings.filter((k) => FINDINGS[k].phase <= phase);
  const discounts = { scope: {}, quote: {}, photos: {} };
  active.forEach((k) => (discounts[FINDINGS[k].v][k] = DISCOUNT[FINDINGS[k].sev]));
  const grades = {};
  Object.keys(WEIGHTS).forEach((v) => {
    grades[v] = Math.max(0, 100 - Object.values(discounts[v]).reduce((a, b) => a + b, 0));
  });
  const totalW = Object.values(WEIGHTS).reduce((a, b) => a + b, 0);
  const score = Math.round(Object.keys(WEIGHTS).reduce((a, v) => a + grades[v] * WEIGHTS[v], 0) / totalW);
  const reducers = active.filter((k) => FINDINGS[k].reducer);
  if (unreadableQuote) reducers.push("unreadable_quote");
  const confidence = reducers.length >= CONFIDENCE.low ? "low" : reducers.length >= CONFIDENCE.medium ? "medium" : "high";
  const lock = active.find((k) => FINDINGS[k].lock);
  let reco, reason;
  if (lock) {
    reco = "return_locked";
    reason = `Trava de integridade: ${FINDINGS[lock].label.toLowerCase()}. Devolver qualquer que seja a nota.`;
  } else if (confidence === "low") {
    reco = "detailed_review";
    reason = `Confiança baixa (${reducers.join(", ")}): entrada insuficiente para concluir.`;
  } else {
    reco = BANDS.find((b) => score >= b.min).reco;
    reason = BAND_REASON[reco] + (confidence === "medium" ? "; confiança média: revisar com atenção." : ".");
  }
  return { grades, score, confidence, reducers, reco, reason, active };
}

const PRESETS = [
  { name: "Pintura do backoffice · 00482193", findings: ["out_of_scope_item", "quantity_above_expected", "photo_mismatch", "missing_before_photo"] },
  { name: "Câmera com foto reaproveitada · 00517706", findings: ["unjustified_replacement", "out_of_scope_item", "reused_photo", "missing_after_photo", "photo_dated_before"] },
  { name: "Ar-condicionado PMOC · 00531877", findings: ["quantity_above_expected", "price_above_reference", "missing_before_photo"] },
  { name: "“Verificar porta. Urgente.” · 00533402", findings: ["vague_scope", "unreadable_photo"] },
  { name: "Tudo certo · 00530121", findings: [] },
  { name: "Checklist incompleto · 00523310", findings: [], checklistOk: false },
];

function initSimulator() {
  const box = $("#sim-findings");
  ["scope", "quote", "photos"].forEach((v) => {
    const g = document.createElement("div");
    g.className = "group";
    g.innerHTML = `<div class="group-title">${VALIDATION_LABEL[v]} · peso ${WEIGHTS[v]}</div>` +
      Object.entries(FINDINGS)
        .filter(([, f]) => f.v === v)
        .map(([k, f]) => `<label class="check" data-k="${k}"><input type="checkbox" value="${k}"><span>${f.label}${f.phase === 2 ? ' <span class="small muted">(fase 2)</span>' : ""}${f.lock ? ' <span class="small muted">· trava</span>' : ""}${f.reducer ? ' <span class="small muted">· reduz confiança</span>' : ""}</span><span class="sev ${f.sev}">−${DISCOUNT[f.sev]}</span></label>`)
        .join("");
    box.appendChild(g);
  });

  const presets = $("#sim-presets");
  PRESETS.forEach((p) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip-btn";
    b.textContent = p.name;
    b.addEventListener("click", () => {
      $$("input[type=checkbox]", box).forEach((c) => (c.checked = p.findings.includes(c.value)));
      $("#sim-checklist").checked = p.checklistOk !== false;
      $("#sim-unreadable-quote").checked = false;
      $("#sim-phase2").checked = true;
      $$(".chip-btn", presets).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      update();
    });
    presets.appendChild(b);
  });

  const update = () => {
    const phase = $("#sim-phase2").checked ? 2 : 1;
    $$(".check", box).forEach((l) => l.classList.toggle("disabled", FINDINGS[l.dataset.k].phase > phase));
    const r = compute({
      findings: $$("input[type=checkbox]:checked", box).map((c) => c.value),
      phase,
      checklistOk: $("#sim-checklist").checked,
      unreadableQuote: $("#sim-unreadable-quote").checked,
    });
    const out = $("#sim-out");
    if (r.score === null) {
      out.innerHTML = `<div class="score-big"><span class="v">—</span><span class="of">sem score</span></div>
        <div class="reco checklist_returned">${RECO[r.reco]}<small>${r.reason}</small></div>`;
      return;
    }
    const conf = { high: "alta", medium: "média", low: "baixa" }[r.confidence];
    out.innerHTML = `
      <div class="score-big"><span class="v">${r.score}</span><span class="of">/ 100</span></div>
      <div class="small muted" style="margin:4px 0 10px">Confiança <b>${conf}</b>${r.reducers.length ? ` · redutores: ${r.reducers.map((x) => `<code>${x}</code>`).join(" ")}` : ""}</div>
      ${Object.keys(WEIGHTS).map((v) => `<div class="grade-row"><span>${VALIDATION_LABEL[v]} <span class="w">×${WEIGHTS[v]}</span></span><div class="bar"><span style="width:${r.grades[v]}%"></span></div><b class="num">${r.grades[v]}</b></div>`).join("")}
      <div class="reco ${r.reco}">${RECO[r.reco]}<small>${r.reason}</small></div>
      <div class="formula">(${r.grades.scope}×20 + ${r.grades.quote}×40 + ${r.grades.photos}×40) ÷ 100 = ${r.score}</div>`;
  };
  $$("input", $("#simulator")).forEach((i) => i.addEventListener("change", () => {
    $$(".chip-btn", presets).forEach((x) => x.setAttribute("aria-pressed", "false"));
    update();
  }));
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
      <div class="row"><span>Tempo de análise por chamado (síncrono, medido)</span><b>26 a 46 s</b></div>`;
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
  initNav();
  initCopy();
  initJourney();
  initFindingsTable();
  initSimulator();
  initCostCalc();
});
