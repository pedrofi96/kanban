/* Kanban PMS — estado global (Alpine.store) + componente de UI (Alpine.data) */

// ---------- Utilidades ----------
const pref = {
  get(chave, padrao) {
    try { return localStorage.getItem("kanban." + chave) ?? padrao; } catch { return padrao; }
  },
  set(chave, valor) {
    try { localStorage.setItem("kanban." + chave, valor); } catch { /* sem storage: ignora */ }
  },
};

function csrf() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function api(metodo, url, corpo) {
  const resp = await fetch(url, {
    method: metodo,
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
    body: corpo ? JSON.stringify(corpo) : undefined,
  });
  const dados = await resp.json().catch(() => ({}));
  // Sessão expirou: volta para a tela de login.
  if (resp.status === 401) {
    window.location.href = "/contas/entrar/?next=" + encodeURIComponent(window.location.pathname + window.location.search);
  }
  if (!resp.ok) throw new Error(dados.erro || `Erro ${resp.status}`);
  return dados;
}

// Cards criados de forma otimista recebem um id temporário até o servidor responder.
let seqTemp = 0;
const pendentes = new Map(); // idTemp -> Promise

// Evita que o "click" disparado ao soltar um card abra o modal.
let arrastando = false;

document.addEventListener("alpine:init", () => {
  const inicial = JSON.parse(document.getElementById("estado-inicial").textContent);

  // =====================================================================
  //  ESTADO GLOBAL
  // =====================================================================
  Alpine.store("kanban", {
    eu: inicial.eu,              // usuário logado
    andares: inicial.andares,    // andares onde posso criar quadros ([] = não posso)
    quadros: inicial.quadros,
    quadroAtualId: null,
    filtroAndar: "",             // "" = todos; senão o id do andar (texto, como vem do <select>)
    toasts: [],

    init() {
      // ?quadro=ID (vindo da página do projeto) tem prioridade sobre o último aberto.
      const daUrl = Number(new URLSearchParams(window.location.search).get("quadro"));
      const quadroUrl = this.quadros.find((q) => q.id === daUrl);

      // Andar: o do quadro da URL; senão o último escolhido; senão o meu (se tiver quadros nele).
      const andarSalvo = pref.get("andar", null);
      const valido = (id) => id === "" || this.opcoesAndar.some((a) => String(a.id) === id);
      if (quadroUrl) this.filtroAndar = String(quadroUrl.andar_id);
      else if (andarSalvo !== null && valido(andarSalvo)) this.filtroAndar = andarSalvo;
      else if (this.quadros.some((q) => q.andar_id === this.eu.andar_id)) this.filtroAndar = String(this.eu.andar_id);
      else this.filtroAndar = "";

      const salvo = daUrl || Number(pref.get("quadro", 0));
      const lista = this.quadrosDoAndar;
      this.quadroAtualId = lista.some((q) => q.id === salvo) ? salvo : lista[0]?.id ?? null;
    },

    get quadro() {
      return this.quadros.find((q) => q.id === this.quadroAtualId) || null;
    },

    // Andares do <select>: os que têm quadros visíveis + os que eu posso criar quadros.
    get opcoesAndar() {
      const mapa = new Map();
      for (const q of this.quadros) mapa.set(q.andar_id, q.andar);
      for (const a of this.andares) mapa.set(a.id, a.nome);
      return [...mapa].map(([id, nome]) => ({ id, nome })).sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR", { numeric: true }));
    },

    get quadrosDoAndar() {
      if (!this.filtroAndar) return this.quadros;
      return this.quadros.filter((q) => String(q.andar_id) === this.filtroAndar);
    },

    filtrarAndar(valor) {
      this.filtroAndar = valor;
      pref.set("andar", valor);
      // Se o quadro aberto não é deste andar, abre o primeiro do andar.
      if (!this.quadrosDoAndar.some((q) => q.id === this.quadroAtualId)) {
        const primeiro = this.quadrosDoAndar[0];
        this.quadroAtualId = primeiro?.id ?? null;
        if (primeiro) pref.set("quadro", primeiro.id);
      }
    },

    // Membros do quadro aberto (são os que podem ser responsáveis).
    get membros() {
      return this.quadro?.membros ?? [];
    },

    membro(id) {
      return this.membros.find((m) => m.id === id) || null;
    },

    coluna(id) {
      return this.quadro?.colunas.find((c) => c.id === id) || null;
    },

    cardsDaColuna(colunaId) {
      if (!this.quadro) return [];
      return this.quadro.cards
        .filter((c) => c.coluna_id === colunaId)
        .sort((a, b) => a.ordem - b.ordem);
    },

    acharCard(id) {
      for (const q of this.quadros) {
        const c = q.cards.find((c) => String(c.id) === String(id));
        if (c) return c;
      }
      return null;
    },

    avisar(msg) {
      const id = ++seqTemp;
      this.toasts.push({ id, msg });
      setTimeout(() => (this.toasts = this.toasts.filter((t) => t.id !== id)), 4000);
    },

    // Rollback: em caso de erro, volta ao que o servidor tem.
    async falhou(erro) {
      this.avisar(erro.message || "Não foi possível salvar. Recarregando dados…");
      try {
        const dados = await api("GET", "/api/estado/");
        this.eu = dados.eu;
        this.andares = dados.andares;
        this.quadros = dados.quadros;
        if (!this.quadro) this.quadroAtualId = this.quadros[0]?.id ?? null;
      } catch { /* servidor fora do ar */ }
    },

    async idReal(card) {
      if (card._tmp && pendentes.has(card._tmp)) await pendentes.get(card._tmp);
      return card.id;
    },

    // ---------- Quadros ----------
    selecionarQuadro(id) {
      this.quadroAtualId = id;
      pref.set("quadro", id);
    },

    async criarQuadro(nome, andarId) {
      try {
        const quadro = await api("POST", "/api/quadros/", { nome, andar_id: andarId });
        this.quadros.push(quadro);
        // Mostra o andar do quadro novo, para ele aparecer na lista.
        if (this.filtroAndar && this.filtroAndar !== String(quadro.andar_id)) this.filtrarAndar(String(quadro.andar_id));
        this.selecionarQuadro(quadro.id);
      } catch (e) { this.falhou(e); }
    },

    async sairDoQuadro(quadro) {
      try {
        const r = await api("POST", `/api/quadros/${quadro.id}/sair/`);
        if (r.ainda_ve) {
          // Admin do andar continua vendo o quadro do próprio andar: só atualiza os dados.
          const dados = await api("GET", "/api/estado/");
          this.quadros = dados.quadros;
        } else {
          this.quadros.splice(this.quadros.indexOf(quadro), 1);
          this.quadroAtualId = this.quadrosDoAndar[0]?.id ?? null;
        }
      } catch (e) { this.falhou(e); }
    },

    // Lista de quem pode entrar no quadro (só para quem administra).
    async candidatos(quadro) {
      const r = await api("GET", `/api/quadros/${quadro.id}/membros/`);
      return r.candidatos;
    },

    async adicionarMembro(quadro, usuarioId) {
      try {
        const atualizado = await api("POST", `/api/quadros/${quadro.id}/membros/`, { usuario_id: usuarioId });
        quadro.membros = atualizado.membros;
        quadro.e_membro = atualizado.e_membro;
        return true;
      } catch (e) { this.avisar(e.message); return false; }
    },

    // ---------- Colunas (só quem tem quadro.pode_gerenciar_colunas) ----------
    // Sem atualização otimista: espera o servidor e troca a lista de colunas pela que ele devolve.
    async criarColuna(quadro, titulo) {
      try {
        const r = await api("POST", `/api/quadros/${quadro.id}/colunas/`, { titulo });
        quadro.colunas = r.colunas;
        return true;
      } catch (e) { this.avisar(e.message); return false; }
    },

    async renomearColuna(quadro, coluna, titulo) {
      try {
        const r = await api("PATCH", `/api/colunas/${coluna.id}/`, { titulo });
        quadro.colunas = r.colunas;
        return true;
      } catch (e) { this.avisar(e.message); return false; }
    },

    async excluirColuna(quadro, coluna) {
      try {
        const r = await api("DELETE", `/api/colunas/${coluna.id}/`);
        quadro.colunas = r.colunas;
      } catch (e) { this.falhou(e); } // recarrega: outra pessoa pode ter posto um card na coluna
    },

    // Põe a coluna na `posicao` (0 = primeira). A "Concluído" fica sempre no fim.
    async moverColuna(quadro, colunaId, posicao) {
      const coluna = quadro.colunas.find((c) => c.id === colunaId);
      const comuns = quadro.colunas.filter((c) => !c.concluida && c.id !== colunaId);
      comuns.splice(posicao, 0, coluna);
      const concluida = quadro.colunas.filter((c) => c.concluida);
      // Muda a tela na hora; depois fica com a lista que o servidor devolver.
      quadro.colunas = [...comuns, ...concluida].map((c, i) => ({ ...c, ordem: i }));
      try {
        const r = await api("POST", `/api/colunas/${colunaId}/mover/`, { ordem: posicao });
        quadro.colunas = r.colunas;
      } catch (e) { this.falhou(e); }
    },

    // Por que a coluna não pode ser excluída ("" = pode). As mesmas regras são checadas no servidor.
    motivoNaoExcluirColuna(coluna) {
      if (coluna.concluida) return "A coluna “Concluído” não pode ser excluída.";
      if (this.cardsDaColuna(coluna.id).length) return "Só é possível excluir uma coluna vazia.";
      if ((this.quadro?.colunas.length ?? 0) <= 3) return "O projeto precisa ter pelo menos 3 colunas.";
      return "";
    },

    // ---------- Cards ----------
    // Na criação qualquer membro pode definir a data; depois, só quem tem pode_alterar_vencimento.
    criarCard(colunaId, titulo, vencimento = null) {
      const quadro = this.quadro;
      const tmp = "tmp" + ++seqTemp;
      const ordem = this.cardsDaColuna(colunaId).length;
      quadro.cards.push({
        id: tmp, _tmp: tmp, coluna_id: colunaId, titulo, descricao: "",
        prioridade: "media", responsavel_id: null, vencimento, ordem, checklist: [],
      });
      const card = quadro.cards[quadro.cards.length - 1]; // versão reativa (proxy)

      const promessa = api("POST", "/api/cards/", { coluna_id: colunaId, titulo, vencimento })
        .then((real) => {
          card.id = real.id;
          delete card._tmp;
        })
        .catch((e) => this.falhou(e))
        .finally(() => pendentes.delete(tmp));
      pendentes.set(tmp, promessa);
      return card;
    },

    // "Salvar mudanças": manda só o que mudou (campos e/ou checklist) numa chamada.
    // O card da tela só é atualizado depois que o servidor confirma.
    async salvarCard(card, corpo) {
      try {
        const id = await this.idReal(card);
        const real = await api("PATCH", `/api/cards/${id}/`, corpo);
        Object.assign(card, real);
        return true;
      } catch (e) { this.avisar(e.message); return false; }
    },

    async excluirCard(card) {
      const quadro = this.quadros.find((q) => q.cards.includes(card));
      const colunaId = card.coluna_id;
      quadro.cards.splice(quadro.cards.indexOf(card), 1);
      this.cardsDaColuna(colunaId).forEach((c, i) => (c.ordem = i));
      try {
        const id = await this.idReal(card);
        await api("DELETE", `/api/cards/${id}/`);
      } catch (e) { this.falhou(e); }
    },

    async moverCard(cardId, destinoId, posicao) {
      const card = this.acharCard(cardId);
      if (!card) return;
      const origemId = card.coluna_id;

      const destino = this.cardsDaColuna(destinoId).filter((c) => c !== card);
      destino.splice(posicao, 0, card);
      card.coluna_id = destinoId;
      destino.forEach((c, i) => (c.ordem = i));
      if (origemId !== destinoId) this.cardsDaColuna(origemId).forEach((c, i) => (c.ordem = i));

      try {
        const id = await this.idReal(card);
        await api("POST", `/api/cards/${id}/mover/`, { coluna_id: destinoId, ordem: posicao });
      } catch (e) { this.falhou(e); }
    },
  });

  // =====================================================================
  //  COMPONENTE DE INTERFACE (filtros, modais, tema)
  // =====================================================================
  Alpine.data("app", () => ({
    busca: "",
    filtroPrioridade: "",
    filtroMembro: "",
    tema: pref.get("tema", "dark"),

    cardAbertoId: null,
    confirmandoExclusao: false,
    novoItem: "",

    // Modo de edição do card. O modal mostra sempre o RASCUNHO (cópia do card);
    // o card de verdade só muda quando "Salvar mudanças" dá certo.
    editando: false,
    salvando: false,
    confirmandoFechar: false,
    rascunho: { titulo: "", descricao: "", prioridade: "media", vencimento: null, responsavel_id: null, checklist: [] },
    original: "",             // rascunho como estava ao clicar em "Editar" (texto JSON, para comparar)

    novoCardColuna: null,
    novoCardTitulo: "",
    novoCardVencimento: "",

    criandoQuadro: false,
    novoQuadroNome: "",
    novoQuadroAndar: null,

    criandoColuna: false,
    novaColunaTitulo: "",
    colunaEditandoId: null,   // id da coluna que está sendo renomeada
    colunaEditandoTitulo: "",

    atividades: [],
    carregandoAtividades: false,

    adicionandoMembro: false,
    candidatos: [],
    carregandoCandidatos: false,
    buscaCandidato: "",

    prioridades: [
      { valor: "alta", rotulo: "Alta", classe: "bg-red-500/15 text-red-400 ring-red-500/30", ponto: "bg-red-500" },
      { valor: "media", rotulo: "Média", classe: "bg-orange-500/15 text-orange-400 ring-orange-500/30", ponto: "bg-orange-500" },
      { valor: "baixa", rotulo: "Baixa", classe: "bg-green-500/15 text-green-400 ring-green-500/30", ponto: "bg-green-500" },
    ],

    get k() { return Alpine.store("kanban"); },

    init() {
      this.ajustarAndarDoNovoQuadro();
      // Ao trocar o filtro de andar, o "Novo quadro" passa a sugerir esse andar.
      this.$watch("$store.kanban.filtroAndar", () => this.ajustarAndarDoNovoQuadro());
      // Trocou de quadro: fecha a caixa de "Adicionar servidor" (a lista era do outro quadro).
      this.$watch("$store.kanban.quadroAtualId", () => {
        this.adicionandoMembro = false;
        this.criandoColuna = false;
        this.colunaEditandoId = null;
      });
    },

    // Andar padrão do "Novo quadro": o filtrado; senão o meu; senão o primeiro permitido.
    ajustarAndarDoNovoQuadro() {
      const andares = this.k.andares;
      const filtrado = andares.find((a) => String(a.id) === this.k.filtroAndar);
      const meu = andares.find((a) => a.id === this.k.eu.andar_id);
      this.novoQuadroAndar = (filtrado || meu || andares[0])?.id ?? null;
    },

    // ---------- Adicionar servidor ao quadro ----------
    get candidatosFiltrados() {
      const termo = this.normalizar(this.buscaCandidato.trim());
      if (!termo) return this.candidatos;
      return this.candidatos.filter((u) => this.normalizar(u.nome).includes(termo));
    },

    async alternarAdicionarMembro() {
      this.adicionandoMembro = !this.adicionandoMembro;
      if (!this.adicionandoMembro) return;
      this.buscaCandidato = "";
      this.candidatos = [];
      this.carregandoCandidatos = true;
      this.$nextTick(() => this.$refs.buscaCandidato?.focus());
      try { this.candidatos = await this.k.candidatos(this.k.quadro); }
      catch (e) { this.k.avisar(e.message); }
      this.carregandoCandidatos = false;
    },

    async adicionarMembro(usuario) {
      const ok = await this.k.adicionarMembro(this.k.quadro, usuario.id);
      if (ok) this.candidatos = this.candidatos.filter((u) => u.id !== usuario.id);
    },

    get cardAberto() {
      return this.cardAbertoId == null ? null : this.k.acharCard(this.cardAbertoId);
    },

    get filtrando() {
      return Boolean(this.busca.trim() || this.filtroPrioridade || this.filtroMembro);
    },

    // ---------- Filtros ----------
    // Remove acentos e ignora maiúsculas: "Revisão" -> "revisao"
    normalizar(texto) {
      return (texto || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    },

    cardVisivel(card) {
      if (!card) return false;

      const termo = this.normalizar(this.busca.trim());
      if (termo && !this.normalizar(card.titulo).includes(termo)) return false;

      if (this.filtroPrioridade && card.prioridade !== this.filtroPrioridade) return false;

      // O <select> devolve string ("2"); responsavel_id é número ou null.
      if (this.filtroMembro && card.responsavel_id !== Number(this.filtroMembro)) return false;

      return true;
    },

    contarVisiveis(colunaId) {
      return this.k.cardsDaColuna(colunaId).filter((c) => this.cardVisivel(c)).length;
    },

    limparFiltros() {
      this.busca = "";
      this.filtroPrioridade = "";
      this.filtroMembro = "";
    },

    // ---------- Tema ----------
    alternarTema() {
      this.tema = this.tema === "dark" ? "light" : "dark";
      pref.set("tema", this.tema);
    },

    // ---------- Drag and drop ----------
    iniciarSortable(el) {
      Sortable.create(el, {
        group: "kanban",
        draggable: ".kanban-card",
        animation: 200,
        easing: "cubic-bezier(0.2, 0.8, 0.2, 1)",
        ghostClass: "card-fantasma",
        chosenClass: "card-escolhido",
        dragClass: "card-arrastado",
        // Usa o arraste NATIVO do navegador. Não use forceFallback: ele clona o card
        // no <body>, o Alpine tenta ativar esse clone (fora do x-for) e o texto da
        // página fica selecionado durante o movimento.
        onStart: () => {
          arrastando = true;
          // Reforço para telas de toque, onde o Sortable usa o modo fallback.
          document.body.classList.add("arrastando-card");
          window.getSelection()?.removeAllRanges();
        },
        onEnd: (evt) => {
          setTimeout(() => (arrastando = false), 50);
          document.body.classList.remove("arrastando-card");
          window.getSelection()?.removeAllRanges();
          const { item, from, to, oldDraggableIndex: de, newDraggableIndex: para } = evt;
          if (from === to && de === para) return;

          // Devolve o elemento ao lugar original: quem redesenha o DOM é o Alpine,
          // a partir do estado. Se deixarmos o Sortable mexer, o x-for se perde.
          item.remove();
          const irmaos = from.querySelectorAll(":scope > .kanban-card");
          from.insertBefore(item, irmaos[de] || null);

          this.k.moverCard(item.dataset.cardId, Number(to.dataset.colunaId), para);
        },
      });
    },

    // Arraste das COLUNAS. Só começa pela alça (.alca-coluna), que só o admin vê.
    iniciarSortableColunas(el) {
      let proximo = null; // quem vinha depois da coluna antes do arraste
      Sortable.create(el, {
        group: "colunas",            // nome diferente de "kanban": card não cai aqui, coluna não cai na lista de cards
        draggable: ".kanban-coluna",
        handle: ".alca-coluna",
        animation: 200,
        ghostClass: "coluna-fantasma",
        // Nunca deixa soltar depois da "Concluído".
        onMove: (evt) => !(evt.related.classList.contains("coluna-concluida") && evt.willInsertAfter),
        onStart: (evt) => {
          arrastando = true;
          proximo = evt.item.nextSibling;
        },
        onEnd: (evt) => {
          setTimeout(() => (arrastando = false), 50);
          const { item, from, oldDraggableIndex: de, newDraggableIndex: para } = evt;
          // Devolve o elemento ao lugar original: quem redesenha é o Alpine.
          item.remove();
          from.insertBefore(item, proximo);
          if (de === para) return;
          this.k.moverColuna(this.k.quadro, Number(item.dataset.colunaId), para);
        },
      });
    },

    // ---------- Quadros ----------
    async confirmarNovoQuadro() {
      const nome = this.novoQuadroNome.trim();
      if (!nome) return;
      await this.k.criarQuadro(nome, this.novoQuadroAndar);
      this.novoQuadroNome = "";
      this.criandoQuadro = false;
    },

    sairDoQuadro() {
      const quadro = this.k.quadro;
      if (!quadro) return;
      const ok = window.confirm(`Sair do projeto "${quadro.nome}"? Os cards em que você é responsável ficarão sem responsável.`);
      if (ok) this.k.sairDoQuadro(quadro);
    },

    // ---------- Colunas ----------
    abrirNovaColuna() {
      this.criandoColuna = true;
      this.novaColunaTitulo = "";
      this.$nextTick(() => this.$refs.novaColuna?.focus());
    },

    async confirmarNovaColuna() {
      const titulo = this.novaColunaTitulo.trim();
      if (!titulo) return;
      if (await this.k.criarColuna(this.k.quadro, titulo)) this.criandoColuna = false;
    },

    editarColuna(coluna) {
      this.colunaEditandoId = coluna.id;
      this.colunaEditandoTitulo = coluna.titulo;
      this.$nextTick(() => document.getElementById("titulo-coluna-" + coluna.id)?.select());
    },

    async confirmarEdicaoColuna(coluna) {
      if (this.colunaEditandoId !== coluna.id) return; // já confirmou (Enter + perda de foco)
      const titulo = this.colunaEditandoTitulo.trim();
      this.colunaEditandoId = null;
      if (!titulo || titulo === coluna.titulo) return;
      await this.k.renomearColuna(this.k.quadro, coluna, titulo);
    },

    excluirColuna(coluna) {
      if (this.k.motivoNaoExcluirColuna(coluna)) return;
      if (window.confirm(`Excluir a coluna "${coluna.titulo}"?`)) this.k.excluirColuna(this.k.quadro, coluna);
    },

    // Cor da bolinha: "Concluído" é sempre verde; as outras seguem a posição.
    corDaColuna(coluna) {
      if (coluna.concluida) return "bg-emerald-500";
      return ["bg-slate-400", "bg-blue-500", "bg-amber-500", "bg-violet-500", "bg-pink-500", "bg-cyan-500"][coluna.ordem % 6];
    },

    // ---------- Novo card ----------
    abrirNovoCard(colunaId) {
      this.novoCardColuna = colunaId;
      this.novoCardTitulo = "";
      this.novoCardVencimento = "";
      this.$nextTick(() => document.getElementById("novo-card-" + colunaId)?.focus());
    },

    confirmarNovoCard() {
      const titulo = this.novoCardTitulo.trim();
      if (!titulo) return this.cancelarNovoCard();
      this.k.criarCard(this.novoCardColuna, titulo, this.novoCardVencimento || null);
      this.novoCardTitulo = ""; // mantém aberto para adicionar vários seguidos
      this.novoCardVencimento = "";
    },

    cancelarNovoCard() {
      this.novoCardColuna = null;
      this.novoCardTitulo = "";
      this.novoCardVencimento = "";
    },

    // ---------- Modal ----------
    abrirCard(card) {
      if (arrastando) return;
      this.cardAbertoId = card.id;
      this.confirmandoExclusao = false;
      this.confirmandoFechar = false;
      this.editando = false;
      this.novoItem = "";
      this.rascunho = this.copiaDoCard(card);
      this.carregarAtividades(card);
    },

    // ---------- Modo de edição ----------
    copiaDoCard(card) {
      return {
        titulo: card.titulo,
        descricao: card.descricao,
        prioridade: card.prioridade,
        vencimento: card.vencimento,
        responsavel_id: card.responsavel_id,
        // _k: chave só da tela (item novo ainda não tem id)
        checklist: card.checklist.map((i) => ({ _k: ++seqTemp, id: i.id, texto: i.texto, feito: i.feito })),
      };
    },

    iniciarEdicao() {
      this.rascunho = this.copiaDoCard(this.cardAberto);
      this.original = JSON.stringify(this.rascunho);
      this.novoItem = "";
      this.editando = true;
    },

    // true se o rascunho está diferente de como estava ao clicar em "Editar".
    get alterado() {
      return this.editando && JSON.stringify(this.rascunho) !== this.original;
    },

    async salvarEdicao() {
      const card = this.cardAberto;
      const r = this.rascunho;
      r.titulo = r.titulo.trim();
      if (!r.titulo) return this.k.avisar("O título é obrigatório.");
      if (!this.alterado) { this.editando = false; return; } // nada mudou: nem chama o servidor

      const antes = JSON.parse(this.original);
      const corpo = {};
      for (const campo of ["titulo", "descricao", "prioridade", "vencimento", "responsavel_id"]) {
        if (r[campo] !== antes[campo]) corpo[campo] = r[campo];
      }
      if (JSON.stringify(r.checklist) !== JSON.stringify(antes.checklist)) {
        corpo.checklist = r.checklist.map(({ id, texto, feito }) => ({ id, texto, feito }));
      }

      this.salvando = true;
      const ok = await this.k.salvarCard(card, corpo);
      this.salvando = false;
      if (!ok) return; // deu erro: continua editando, sem perder o que foi digitado
      this.editando = false;
      this.rascunho = this.copiaDoCard(card);
      this.carregarAtividades(card);
    },

    fecharSemSalvar() {
      this.confirmandoFechar = false;
      this.editando = false;
      this.cardAbertoId = null;
    },

    async carregarAtividades(card) {
      this.atividades = [];
      this.carregandoAtividades = true;
      try {
        const id = await this.k.idReal(card);
        const r = await api("GET", `/api/cards/${id}/atividades/`);
        if (this.cardAbertoId === card.id) this.atividades = r.atividades;
      } catch { /* histórico é só informativo */ }
      this.carregandoAtividades = false;
    },

    // X, Esc ou clique fora. Só pergunta se houver mudança não salva.
    fecharModal() {
      if (this.confirmandoExclusao) { this.confirmandoExclusao = false; return; }
      if (this.confirmandoFechar) { this.confirmandoFechar = false; return; } // volta a editar
      if (this.alterado) { this.confirmandoFechar = true; return; }
      this.fecharSemSalvar();
    },

    // As funções abaixo mexem só no rascunho, e só no modo de edição.
    definirPrioridade(valor) {
      if (this.editando) this.rascunho.prioridade = valor;
    },

    definirResponsavel(id) {
      if (this.editando) this.rascunho.responsavel_id = this.rascunho.responsavel_id === id ? null : id;
    },

    adicionarItem() {
      const texto = this.novoItem.trim();
      if (!texto || !this.editando) return;
      this.rascunho.checklist.push({ _k: ++seqTemp, id: null, texto, feito: false });
      this.novoItem = "";
    },

    removerItem(item) {
      if (this.editando) this.rascunho.checklist = this.rascunho.checklist.filter((i) => i !== item);
    },

    async excluirCardAberto() {
      const card = this.cardAberto;
      this.confirmandoExclusao = false;
      this.editando = false;
      this.cardAbertoId = null;
      await this.k.excluirCard(card);
    },

    // ---------- Formatação ----------
    prioridade(valor) {
      return this.prioridades.find((p) => p.valor === valor) || this.prioridades[1];
    },

    progresso(card) {
      const total = card.checklist.length;
      if (!total) return 0;
      return Math.round((card.checklist.filter((i) => i.feito).length / total) * 100);
    },

    feitos(card) {
      return card.checklist.filter((i) => i.feito).length;
    },

    dataLocal(iso) {
      const [a, m, d] = iso.split("-").map(Number);
      return new Date(a, m - 1, d);
    },

    formatarDataHora(iso) {
      return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
    },

    formatarData(iso) {
      if (!iso) return "";
      return this.dataLocal(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "");
    },

    // "vencido" | "hoje" | "breve" | "ok" | "concluido" | null
    statusVencimento(card) {
      if (!card.vencimento) return null;
      if (this.k.coluna(card.coluna_id)?.concluida) return "concluido";
      const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
      const dias = Math.round((this.dataLocal(card.vencimento) - hoje) / 86400000);
      if (dias < 0) return "vencido";
      if (dias === 0) return "hoje";
      if (dias <= 2) return "breve";
      return "ok";
    },

    classeVencimento(card) {
      return {
        vencido: "bg-red-500/15 text-red-400",
        hoje: "bg-amber-500/15 text-amber-400",
        breve: "bg-amber-500/10 text-amber-300",
        ok: "bg-slate-500/10 text-slate-500 dark:text-slate-400",
        concluido: "bg-emerald-500/10 text-emerald-500 line-through",
      }[this.statusVencimento(card)] || "";
    },

    cardsDoMembro(membroId) {
      return this.k.quadro ? this.k.quadro.cards.filter((c) => c.responsavel_id === membroId).length : 0;
    },
  }));
});
