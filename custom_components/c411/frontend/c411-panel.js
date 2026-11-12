/*
 * Panneau TorrentManager (C411 + qBittorrent + Plex) pour Home Assistant
 * Nouveautés · Recherche · Téléchargements qBittorrent
 * Aucune dépendance, aucun build : un simple Web Component.
 */

const ICONS = {
  "1": "mdi:gamepad-variant",
  "2": "mdi:movie-open",
  "3": "mdi:music",
  "4": "mdi:application-cog",
  "5": "mdi:television-classic",
  "6": "mdi:eye-off",
  "7": "mdi:book-open-variant",
  "8": "mdi:printer-3d",
};
const SPECIAL_ICONS = { "2060": "mdi:movie-roll", "5070": "mdi:drama-masks", "2070": "mdi:earth", "3030": "mdi:headphones" };

const STATES = {
  downloading: ["Téléchargement", "dl"],
  forcedDL: ["Téléchargement (forcé)", "dl"],
  metaDL: ["Métadonnées…", "wait"],
  forcedMetaDL: ["Métadonnées…", "wait"],
  stalledDL: ["En attente de sources", "wait"],
  queuedDL: ["En file d'attente", "wait"],
  allocating: ["Allocation", "wait"],
  checkingDL: ["Vérification", "wait"],
  checkingUP: ["Vérification", "wait"],
  checkingResumeData: ["Vérification", "wait"],
  pausedDL: ["En pause", "paused"],
  stoppedDL: ["En pause", "paused"],
  uploading: ["Partage", "up"],
  forcedUP: ["Partage (forcé)", "up"],
  stalledUP: ["Terminé · partage", "up"],
  queuedUP: ["Terminé · en file", "done"],
  pausedUP: ["Terminé", "done"],
  stoppedUP: ["Terminé", "done"],
  moving: ["Déplacement", "wait"],
  missingFiles: ["Fichiers manquants", "err"],
  error: ["Erreur", "err"],
  unknown: ["Inconnu", "wait"],
};
const AUTO = "__auto__";
const QORDER = ["2160p", "1080p", "720p", "sd"];
const QLABEL = { "2160p": "4K", "1080p": "1080p", "720p": "720p", sd: "SD" };
const LLABEL = { vf: "VF", vostfr: "VOSTFR", vo: "VO" };
const SRCLABEL = { remux: "REMUX", bluray: "BluRay", web: "WEB-DL", webrip: "WEBRip", light: "Light", hdtv: "HDTV", dvd: "DVD", cam: "CAM" };
const SRCSCORE = { remux: 40, bluray: 35, web: 30, webrip: 20, light: 10, hdtv: 5, dvd: 0, cam: -800 };

/* Note d'une version : préférences (qualité, langue) puis réputation (sources, téléchargements…). */
function versionScore(r, prefQ, prefL) {
  const i = r.info || {};
  const qi = QORDER.indexOf(i.quality || "sd"), pi = QORDER.indexOf(prefQ);
  let sc = 1000 - Math.abs(qi - (pi < 0 ? 1 : pi)) * 300;
  if (i.languages === prefL) sc += 500;
  else if (prefL === "vf" && i.languages === "vostfr") sc += 150;
  if (i.multi && prefL !== "vo") sc += 40;
  sc += Math.round(Math.log10(1 + (r.seeders || 0)) * 120);
  sc += Math.round(Math.log10(1 + (r.grabs || 0)) * 40);
  if (r.freeleech) sc += 25;
  sc += SRCSCORE[i.source] || 0;
  if (i.proper) sc += 10;
  if (!r.seeders) sc -= 400;
  return sc;
}
const PAUSED = new Set(["pausedDL", "stoppedDL", "pausedUP", "stoppedUP"]);

const nf1 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const rtf = new Intl.RelativeTimeFormat("fr", { numeric: "auto" });

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function bytes(n) {
  n = Number(n) || 0;
  const u = ["o", "Ko", "Mo", "Go", "To"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${nf1.format(n)} ${u[i]}`;
}
const speed = (n) => `${bytes(n)}/s`;
function ago(iso) {
  if (!iso) return "";
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const steps = [[60, "second"], [3600, "minute"], [86400, "hour"], [604800, "day"], [2629800, "week"], [31557600, "month"], [Infinity, "year"]];
  const div = { second: 1, minute: 60, hour: 3600, day: 86400, week: 604800, month: 2629800, year: 31557600 };
  for (const [lim, unit] of steps) if (Math.abs(diff) < lim) return rtf.format(Math.round(diff / div[unit]), unit);
  return "";
}
function eta(s) {
  s = Number(s);
  if (!isFinite(s) || s <= 0 || s >= 8640000) return "∞";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d} j ${h} h`;
  if (h) return `${h} h ${m} min`;
  if (m) return `${m} min`;
  return `${Math.floor(s)} s`;
}

class C411Panel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._s = {
      tab: "latest",
      config: null,
      latest: [], latestError: null, latestLoading: false, latestUpdate: null,
      results: null, searchError: null, searchLoading: false, lastQuery: "", offset: 0, more: false,
      cats: new Set(), latestCats: new Set(),
      sort: "date",
      qb: null, qbError: null,
      dlFilter: "c411",
      sending: new Set(), sent: new Set(),
      confirm: null,
      qbCategory: null, paused: null,
      series: null, seriesError: null, seriesLoading: false, seriesFilter: "followed", seriesQuery: "",
      seriesBusy: new Set(),
      view: { best: true, q: "all", l: "all" }, viewLoaded: false,
      expanded: new Set(), art: {}, artAsked: new Set(),
      perms: { view: true, download: true, manage: true },
      recs: null, recsLoading: false, recsError: null, byId: null,
    };
    this._built = false;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first && this.isConnected) this._init();
  }
  set narrow(v) { this._narrow = v; if (this._menu) this._menu.narrow = v; }
  set panel(v) { this._panel = v; }

  connectedCallback() {
    if (this._hass && !this._built) this._init();
    this._startPolling();
  }
  disconnectedCallback() { clearInterval(this._timer); this._timer = null; }

  _startPolling() {
    if (this._timer || !this._hass) return;
    let tick = 0;
    this._timer = setInterval(() => {
      if (document.hidden) return;
      this._loadTorrents();
      if (++tick % 15 === 0) this._loadSeries();
    }, 4000);
  }

  async _init() {
    if (this._built) return;
    this._build();
    this._built = true;
    this._startPolling();
    try {
      const cfg = await this._ws({ type: "c411/config" });
      this._s.config = cfg;
      this._s.qbCategory = AUTO;
      this._s.perms = cfg.permissions || this._s.perms;
      this._loadView(cfg);
      this._s.paused = !!cfg.start_paused;
      this._renderSendOptions();
      this._renderViewOptions();
      this._renderChips();
      this._renderLatest(); this._renderResults();
    } catch (e) { this._toast(this._msg(e), true); }
    this._loadLatest(false);
    this._loadTorrents();
    this._loadSeries();
  }

  _ws(msg) { return this._hass.callWS(msg); }
  _msg(e) { return e?.message || e?.error?.message || String(e); }

  // ---------------------------------------------------------------- données
  async _loadLatest(refresh) {
    this._s.latestLoading = true; this._renderLatest();
    try {
      const r = await this._ws({ type: "c411/latest", refresh });
      this._s.latest = r.results || [];
      this._s.latestError = r.error;
      this._s.latestUpdate = r.last_update;
    } catch (e) { this._s.latestError = this._msg(e); }
    this._s.latestLoading = false; this._renderLatest();
  }

  async _search(append = false) {
    const q = this.shadowRoot.getElementById("q").value.trim();
    const s = this._s;
    if (!append) { s.offset = 0; s.lastQuery = q; }
    s.searchLoading = true; s.searchError = null; this._renderResults();
    try {
      const msg = { type: "c411/search", query: s.lastQuery, categories: [...s.cats], limit: 50, offset: s.offset };
      if (s.byId) {
        msg.categories = [];
        msg.query = s.byId.original_title || s.byId.title;
        if (s.byId.tmdbid) msg.tmdbid = s.byId.tmdbid;
        else if (s.byId.imdbid) msg.imdbid = s.byId.imdbid;
        if (msg.tmdbid || msg.imdbid) msg.media = s.byId.media;
      }
      const r = await this._ws(msg);
      const items = r.results || [];
      s.results = append ? [...(s.results || []), ...items] : items;
      const raw = r.raw_count ?? items.length;
      s.more = raw === 50;
      s.offset += raw;
    } catch (e) { s.searchError = this._msg(e); if (!append) s.results = []; }
    s.searchLoading = false; this._renderResults();
  }

  async _loadTorrents() {
    if (!this._hass || !this._built) return;
    try {
      this._s.qb = await this._ws({ type: "c411/torrents", live: true });
      this._s.qbError = null;
    } catch (e) { this._s.qbError = this._msg(e); }
    this._renderStats();
    if (this._s.tab === "downloads") this._renderDownloads();
    else this._refreshBadges();
  }

  async _download(rel) {
    const s = this._s;
    if (!rel.download_url || s.sending.has(rel.guid)) return;
    s.sending.add(rel.guid); this._refreshBadges();
    try {
      const msg = {
        type: "c411/download", url: rel.download_url, title: rel.title, paused: !!s.paused,
        categories: rel.categories || [], content_type: rel.content_type || undefined,
      };
      if (s.qbCategory !== AUTO) msg.category = s.qbCategory;
      await this._ws(msg);
      s.sent.add(rel.guid);
      const dest = this._destination(rel);
      this._toast(`Envoyé à qBittorrent${dest ? " → " + dest : ""} : ${rel.title}`);
      setTimeout(() => this._loadTorrents(), 1500);
    } catch (e) { this._toast(this._msg(e), true); }
    s.sending.delete(rel.guid); this._refreshBadges();
  }

  async _action(action, hash) {
    try {
      this._s.qb = await this._ws({ type: "c411/torrent_action", action, hashes: [hash] });
      const labels = { pause: "Mis en pause", resume: "Relancé", delete: "Torrent retiré", delete_files: "Torrent et fichiers supprimés", recheck: "Vérification lancée" };
      this._toast(labels[action] || "OK");
    } catch (e) { this._toast(this._msg(e), true); }
    this._s.confirm = null;
    this._renderDownloads(); this._renderStats();
  }

  // ---------------------------------------------------------------- squelette
  _build() {
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>${STYLE}</style>
      <div class="toolbar">
        <span id="menu"></span>
        <div class="title"><ha-icon icon="mdi:movie-search"></ha-icon> TorrentManager</div>
        <div class="stats" id="stats"></div>
      </div>
      <nav class="tabs" id="tabs">
        <button data-tab="latest" class="active"><ha-icon icon="mdi:new-box"></ha-icon><span>Nouveautés</span></button>
        <button data-tab="search"><ha-icon icon="mdi:magnify"></ha-icon><span>Recherche</span></button>
        <button data-tab="foryou"><ha-icon icon="mdi:star-shooting-outline"></ha-icon><span>Pour vous</span></button>
        <button data-tab="series"><ha-icon icon="mdi:television-play"></ha-icon><span>Séries</span><b id="sercount"></b></button>
        <button data-tab="downloads"><ha-icon icon="mdi:download"></ha-icon><span>Téléchargements</span><b id="dlcount"></b></button>
      </nav>
      <main>
        <section id="pane-latest">
          <div class="controls">
            <div class="chips" id="chips-latest"></div>
            <div class="row">
              <label class="sort">Trier <select id="sort-latest">
                <option value="date">Plus récents</option><option value="seeders">Plus de sources</option>
                <option value="size">Plus gros</option><option value="grabs">Plus téléchargés</option></select></label>
              <span class="send-options"></span>
              <button class="ghost" data-action="refresh-latest" title="Rafraîchir"><ha-icon icon="mdi:refresh"></ha-icon></button>
            </div>
            <div class="row view-options"></div>
          </div>
          <div id="list-latest" class="list"></div>
        </section>
        <section id="pane-search" hidden>
          <form class="search" id="search-form">
            <ha-icon icon="mdi:magnify"></ha-icon>
            <input id="q" type="search" placeholder="Titre, saison, qualité… (ex. « Dune 2160p »)" autocomplete="off" />
            <button class="btn primary" type="submit">Rechercher</button>
          </form>
          <div class="controls">
            <div class="chips" id="chips-search"></div>
            <div class="row">
              <label class="sort">Trier <select id="sort-search">
                <option value="date">Plus récents</option><option value="seeders">Plus de sources</option>
                <option value="size">Plus gros</option><option value="grabs">Plus téléchargés</option></select></label>
              <span class="send-options"></span>
            </div>
            <div class="row view-options"></div>
          </div>
          <div id="list-search" class="list"></div>
        </section>
        <section id="pane-foryou" hidden>
          <div id="list-foryou"></div>
        </section>
        <section id="pane-series" hidden>
          <div class="controls">
            <div class="row">
              <div class="chips" id="chips-series">
                <button class="chip" data-sf="followed">Suivies</button>
                <button class="chip" data-sf="available">Nouveaux épisodes</button>
                <button class="chip" data-sf="all">Toutes</button>
              </div>
              <input id="series-q" type="search" class="filter" placeholder="Filtrer…" autocomplete="off" />
              <span class="grow"></span>
              <button class="btn outline sm" data-action="series-library" title="Relire la bibliothèque Plex"><ha-icon icon="mdi:plex"></ha-icon>Relire Plex</button>
              <button class="btn primary sm" data-action="series-check" title="Chercher les nouveaux épisodes sur C411"><ha-icon icon="mdi:magnify-scan"></ha-icon>Vérifier maintenant</button>
            </div>
            <div class="hint" id="series-status"></div>
          </div>
          <div id="list-series" class="grid"></div>
        </section>
        <section id="pane-downloads" hidden>
          <div class="controls"><div class="chips" id="chips-dl">
            <button class="chip" data-dl="c411">Ajoutés via C411</button>
            <button class="chip" data-dl="active">En cours</button>
            <button class="chip" data-dl="all">Tous</button>
          </div></div>
          <div id="list-downloads" class="list"></div>
        </section>
      </main>
      <div id="toast" class="toast" hidden></div>
    `;
    const menu = document.createElement("ha-menu-button");
    menu.hass = this._hass; menu.narrow = this._narrow;
    root.getElementById("menu").appendChild(menu);
    this._menu = menu;

    root.addEventListener("click", (ev) => this._onClick(ev));
    root.getElementById("search-form").addEventListener("submit", (ev) => { ev.preventDefault(); this._s.byId = null; this._search(false); });
    root.getElementById("series-q").addEventListener("input", (ev) => { this._s.seriesQuery = ev.target.value; this._renderSeries(); });
    for (const id of ["sort-latest", "sort-search"]) {
      root.getElementById(id).addEventListener("change", (ev) => {
        this._s.sort = ev.target.value;
        root.getElementById("sort-latest").value = root.getElementById("sort-search").value = this._s.sort;
        this._renderLatest(); this._renderResults();
      });
    }
    root.addEventListener("change", (ev) => {
      if (ev.target.classList.contains("qbcat")) { this._s.qbCategory = ev.target.value; this._renderSendOptions(); }
      if (ev.target.classList.contains("paused")) { this._s.paused = ev.target.checked; this._renderSendOptions(); }
      if (ev.target.classList.contains("bestonly")) { this._s.view.best = ev.target.checked; this._viewChanged(); }
      if (ev.target.dataset.pref) this._seriesPref(ev.target.dataset.key, ev.target.dataset.pref, ev.target.checked);
    });
    this._renderChips(); this._renderSendOptions(); this._renderStats();
    this._renderLatest(); this._renderResults(); this._renderDownloads();
  }

  _onClick(ev) {
    const el = ev.target.closest("[data-tab],[data-action],[data-cat],[data-dl],[data-sf],[data-vq],[data-vl]");
    if (!el) return;
    const s = this._s;
    if (el.dataset.tab) return this._setTab(el.dataset.tab);
    if (el.dataset.dl) { s.dlFilter = el.dataset.dl; this._renderDownloads(); return; }
    if (el.dataset.sf) { s.seriesFilter = el.dataset.sf; this._renderSeries(); return; }
    if (el.dataset.vq) { s.view.q = el.dataset.vq; return this._viewChanged(); }
    if (el.dataset.vl) { s.view.l = el.dataset.vl; return this._viewChanged(); }
    if (el.dataset.cat !== undefined) {
      const set = el.dataset.scope === "latest" ? s.latestCats : s.cats;
      const c = el.dataset.cat;
      if (c === "") set.clear(); else set.has(c) ? set.delete(c) : set.add(c);
      this._renderChips();
      if (el.dataset.scope === "latest") this._renderLatest();
      else if (s.results) this._search(false);
      return;
    }
    const a = el.dataset.action;
    if (a === "refresh-latest") return this._loadLatest(true);
    if (a === "more") return this._search(true);
    if (a === "download") {
      const list = el.dataset.list === "latest" ? s.latest : s.results;
      const rel = (list || []).find((r) => r.guid === el.dataset.guid);
      if (rel) this._download(rel);
      return;
    }
    if (a === "goto-downloads") return this._setTab("downloads");
    if (a === "recs-refresh") return this._loadRecs(true);
    if (a === "rec-find") {
      const rec = (s.recs?.items || [])[Number(el.dataset.idx)];
      if (!rec) return;
      s.byId = rec;
      this._setTab("search");
      this.shadowRoot.getElementById("q").value = rec.title + (rec.year ? ` (${rec.year})` : "");
      this._search(false);
      return;
    }
    if (a === "close-hint") {
      try { window.localStorage.setItem("c411-hint-art", "1"); } catch (e) { /* ignoré */ }
      this._renderLatest(); this._renderResults();
      return;
    }
    if (a === "versions") {
      const g = el.dataset.group;
      s.expanded.has(g) ? s.expanded.delete(g) : s.expanded.add(g);
      this._renderLatest(); this._renderResults();
      return;
    }
    if (a === "series-check") return this._seriesCall({ type: "c411/series_check" }, "Vérification terminée", "all");
    if (a === "series-library") return this._seriesCall({ type: "c411/series_check", library: true }, "Bibliothèque Plex relue", "all");
    if (a === "show-check") return this._seriesCall({ type: "c411/series_check", rating_key: el.dataset.key }, null, el.dataset.key);
    if (a === "ep-grab") return this._seriesCall({ type: "c411/series_grab", rating_key: el.dataset.key, key: el.dataset.ep }, `${el.dataset.ep} envoyé à qBittorrent`, el.dataset.key + el.dataset.ep);
    if (a === "ep-forget") return this._seriesCall({ type: "c411/series_forget", rating_key: el.dataset.key, code: el.dataset.ep }, `${el.dataset.ep} pourra être retéléchargé`, el.dataset.key + el.dataset.ep);
    if (a === "confirm") { s.confirm = el.dataset.hash; return this._renderDownloads(); }
    if (a === "cancel") { s.confirm = null; return this._renderDownloads(); }
    if (["pause", "resume", "delete", "delete_files", "recheck"].includes(a)) return this._action(a, el.dataset.hash);
  }

  _setTab(tab) {
    this._s.tab = tab;
    const root = this.shadowRoot;
    root.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    for (const p of ["latest", "search", "foryou", "series", "downloads"]) root.getElementById(`pane-${p}`).hidden = p !== tab;
    if (tab === "foryou") { this._renderForYou(); if (!this._s.recs) this._loadRecs(false); }
    if (tab === "series") { this._renderSeries(); this._loadSeries(); }
    if (tab === "search") setTimeout(() => root.getElementById("q").focus(), 50);
    if (tab === "downloads") { this._renderDownloads(); this._loadTorrents(); }
  }

  // ---------------------------------------------------------------- rendu
  _renderChips() {
    const root = this.shadowRoot; if (!root.getElementById("chips-latest")) return;
    const top = this._topCats();
    const chips = (scope, set) =>
      `<button class="chip ${set.size ? "" : "on"}" data-scope="${scope}" data-cat="">Tout</button>` +
      top.map(([id, label]) =>
        `<button class="chip ${set.has(id) ? "on" : ""}" data-scope="${scope}" data-cat="${id}"><ha-icon icon="${this._icon([id])}"></ha-icon>${esc(label)}</button>`).join("");
    root.getElementById("chips-latest").innerHTML = chips("latest", this._s.latestCats);
    root.getElementById("chips-search").innerHTML = chips("search", this._s.cats);
  }

  _renderSendOptions() {
    const s = this._s;
    const cats = s.config?.qb_categories || [];
    const opts = [
      `<option value="${AUTO}" ${s.qbCategory === AUTO ? "selected" : ""}>Automatique (selon le type)</option>`,
      `<option value="" ${s.qbCategory === "" ? "selected" : ""}>Sans catégorie</option>`,
    ].concat(cats.map((c) => `<option value="${esc(c)}" ${c === s.qbCategory ? "selected" : ""}>${esc(c)}</option>`));
    const html = `<label title="Destination dans qBittorrent. « Automatique » utilise le dossier et la catégorie réglés pour chaque type (Films, Séries…) dans les options."><ha-icon icon="mdi:folder-download"></ha-icon>
        <select class="qbcat">${opts.join("")}</select></label>
      <label class="check" title="Ajouter en pause"><input type="checkbox" class="paused" ${s.paused ? "checked" : ""}/> en pause</label>`;
    const ro = `<span class="hint"><ha-icon icon="mdi:eye-outline"></ha-icon> Consultation seule</span>`;
    this.shadowRoot.querySelectorAll(".send-options").forEach((el) => (el.innerHTML = s.perms.download ? html : ro));
  }

  _renderStats() {
    const root = this.shadowRoot; const el = root.getElementById("stats"); if (!el) return;
    const qb = this._s.qb;
    if (this._s.qbError) {
      el.innerHTML = `<span class="pill err" title="${esc(this._s.qbError)}"><ha-icon icon="mdi:lan-disconnect"></ha-icon> qBittorrent injoignable</span>`;
    } else if (qb) {
      el.innerHTML = `<span class="pill"><ha-icon icon="mdi:arrow-down-bold"></ha-icon>${speed(qb.dl_speed)}</span>
        <span class="pill"><ha-icon icon="mdi:arrow-up-bold"></ha-icon>${speed(qb.up_speed)}</span>`;
    }
    const n = qb ? qb.c411_downloading : 0;
    root.getElementById("dlcount").textContent = n ? String(n) : "";
    const av = this._s.series?.available_count || 0;
    root.getElementById("sercount").textContent = av ? String(av) : "";
  }

  _topCats() {
    return this._s.config?.top_categories || [["2000", "Films"], ["5000", "Séries"], ["5070", "Animation"], ["3000", "Audio"], ["7000", "Ebooks"], ["1000", "Jeux"], ["4000", "Logiciels"]];
  }

  _icon(cats) {
    const c = (cats && cats[0]) || "";
    return SPECIAL_ICONS[c] || ICONS[c[0]] || "mdi:file";
  }
  _catName(cats) {
    const all = this._s.config?.categories || {};
    const c = (cats || []).find((x) => all[x] && !x.endsWith("000")) || (cats || [])[0];
    return all[c] || c || "";
  }

  _matchesTop(rel, set) {
    if (!set.size) return true;
    const top = new Set(this._topCats().map(([id]) => id));
    return (rel.categories || []).some((c) => [...set].some((t) =>
      c === t || (t.endsWith("000") && c[0] === t[0] && !top.has(c))));
  }

  _torrentByHash() {
    const map = new Map();
    for (const t of this._s.qb?.torrents || []) map.set(t.hash, t);
    return map;
  }

  _actionHtml(rel, list, byHash, compact = false) {
    const s = this._s;
    const t = rel.infohash && byHash.get(rel.infohash);
    if (t) {
      const pct = Math.floor((t.progress || 0) * 100);
      return `<button class="btn have" data-action="goto-downloads" title="Déjà dans qBittorrent">
        <ha-icon icon="${pct >= 100 ? "mdi:check-circle" : "mdi:progress-download"}"></ha-icon>${pct >= 100 ? "Téléchargé" : pct + " %"}</button>`;
    }
    if (!s.perms.download) return "";
    if (s.sending.has(rel.guid)) return `<button class="btn primary" disabled><span class="spin"></span>Envoi…</button>`;
    if (s.sent.has(rel.guid)) return `<button class="btn have" data-action="goto-downloads"><ha-icon icon="mdi:check"></ha-icon>Envoyé</button>`;
    const dest = this._destination(rel);
    return `<button class="btn primary ${compact ? "xs" : ""}" data-action="download" data-list="${list}" data-guid="${esc(rel.guid)}" title="${esc(dest ? "Destination : " + dest : "Envoyer à qBittorrent")}">
      <ha-icon icon="mdi:download"></ha-icon>${compact ? "" : "Télécharger"}</button>`;
  }

  _refreshBadges() {
    const byHash = this._torrentByHash();
    const root = this.shadowRoot;
    for (const [list, items] of [["latest", this._s.latest], ["search", this._s.results || []]]) {
      const container = root.getElementById(`list-${list}`); if (!container) continue;
      const map = new Map(items.map((r) => [r.guid, r]));
      container.querySelectorAll(".slot[data-guid]").forEach((slot) => {
        const rel = map.get(slot.dataset.guid); if (!rel) return;
        const html = this._actionHtml(rel, list, byHash);
        if (slot.dataset.h !== html) { slot.innerHTML = html; slot.dataset.h = html; }
      });
    }
  }

  // ---------------------------------------------------------------- versions & affiches
  _loadView(cfg) {
    const v = this._s.view;
    v.best = cfg.best_only !== false;
    this._s.prefQ = cfg.pref_quality || "1080p";
    this._s.prefL = cfg.pref_language || "vf";
    try {
      const saved = JSON.parse(window.localStorage.getItem("c411-view") || "null");
      if (saved) Object.assign(v, saved);
    } catch (e) { /* stockage indisponible : réglages par défaut */ }
  }

  _viewChanged() {
    try { window.localStorage.setItem("c411-view", JSON.stringify(this._s.view)); } catch (e) { /* ignoré */ }
    this._renderViewOptions(); this._renderLatest(); this._renderResults();
  }

  _renderViewOptions() {
    const v = this._s.view;
    const seg = (attr, cur, opts) => `<span class="seg">${opts.map(([val, label]) =>
      `<button data-${attr}="${val}" class="${cur === val ? "on" : ""}">${label}</button>`).join("")}</span>`;
    const html = `<span class="vlabel">Qualité</span>${seg("vq", v.q, [["all", "Toutes"], ["2160p", "4K"], ["1080p", "1080p"], ["720p", "720p"]])}
      <span class="vlabel">Langue</span>${seg("vl", v.l, [["all", "Toutes"], ["vf", "VF / MULTi"], ["vostfr", "VOSTFR"]])}
      <label class="sw" title="Regroupe les versions d'un même film ou épisode et n'affiche que la mieux notée (qualité et langue préférées, puis réputation : sources, téléchargements)">
        <input type="checkbox" class="bestonly" ${v.best ? "checked" : ""}><span></span>Meilleure version seulement</label>`;
    this.shadowRoot.querySelectorAll(".view-options").forEach((el) => (el.innerHTML = html));
  }

  /* Filtre qualité/langue, puis regroupe par contenu. Renvoie [{group, best, versions}]. */
  _groups(list) {
    const s = this._s, v = s.view;
    const prefQ = v.q !== "all" ? v.q : s.prefQ || "1080p";
    const prefL = v.l !== "all" ? v.l : s.prefL || "vf";
    let items = list;
    if (v.q !== "all") items = items.filter((r) => (r.info?.quality || "sd") === v.q);
    if (v.l !== "all") items = items.filter((r) => (r.info?.languages || "vo") === v.l);
    const scored = items.map((r) => ({ r, sc: versionScore(r, prefQ, prefL) }));
    if (!v.best) return scored.map(({ r }) => ({ group: r.guid, best: r, versions: [r] }));
    const map = new Map();
    for (const it of scored) {
      const g = it.r.info?.group || it.r.guid;
      if (!map.has(g)) map.set(g, []);
      map.get(g).push(it);
    }
    return [...map.entries()].map(([group, arr]) => {
      arr.sort((a, b) => b.sc - a.sc);
      return { group, best: arr[0].r, versions: arr.map((x) => x.r) };
    });
  }

  _sortedGroups(groups) {
    const k = this._s.sort;
    const val = (g) => k === "date" ? Math.max(...g.versions.map((r) => Date.parse(r.published || 0) || 0)) : (g.best[k] || 0);
    return groups.sort((a, b) => val(b) - val(a));
  }

  _askArtwork(groups) {
    const s = this._s;
    const items = [];
    for (const g of groups) {
      const r = g.best, i = r.info || {};
      if (s.artAsked.has(g.group) || !["movies", "series", "anime"].includes(r.content_type)) continue;
      s.artAsked.add(g.group);
      items.push({
        key: g.group, group: i.group || null, kind: i.kind || null, name: i.name || null,
        year: i.year || null, season: i.season || null, tmdbid: r.tmdbid || null, imdbid: r.imdbid || null,
        content_type: r.content_type,
      });
    }
    for (let n = 0; n < items.length; n += 60) {
      this._ws({ type: "c411/artwork", items: items.slice(n, n + 60) }).then((res) => {
        Object.assign(s.art, res.artwork || {});
        if (res.error && !this._artErr) { this._artErr = true; this._toast(`Affiches : ${res.error}`, true); }
        this._renderLatest(); this._renderResults();
      }).catch(() => {});
    }
  }

  _versionTags(r) {
    const i = r.info || {};
    const tags = [QLABEL[i.quality] || "SD", (i.multi ? "MULTi" : LLABEL[i.languages] || "VO")];
    if (SRCLABEL[i.source]) tags.push(SRCLABEL[i.source]);
    if (i.codec === "x265") tags.push("x265");
    for (const h of i.hdr || []) tags.push(h);
    return tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("");
  }

  _groupHtml(g, list, byHash) {
    const r = g.best;
    const fallback = g.versions.find((v) => v.poster)?.poster;
    const art = this._s.art[g.group] || (fallback ? { poster: fallback } : null);
    const others = g.versions.length - 1;
    const open = this._s.expanded.has(g.group);
    const visual = art?.poster
      ? `<img class="poster-sm" loading="lazy" src="${esc(art.poster)}" alt="">`
      : `<div class="ico"><ha-icon icon="${this._icon(r.categories)}"></ha-icon></div>`;
    const heading = art?.title
      ? `<div class="t">${esc(art.title)}${art.year ? ` <span class="muted">(${art.year})</span>` : ""}${this._episodeLabel(r)}
          ${art.vote ? `<span class="vote" title="Note du public"><ha-icon icon="mdi:star"></ha-icon>${nf1.format(art.vote)}</span>` : ""}</div>
         <div class="sub" title="${esc(r.title)}">${esc(r.title)}</div>`
      : `<div class="t" title="${esc(r.title)}">${esc(r.title)}</div>`;
    const versions = open && others ? `<ul class="versions">${g.versions.map((v, idx) => `
        <li class="${idx === 0 ? "top" : ""}">
          <span class="tags">${this._versionTags(v)}</span>
          <span class="vt" title="${esc(v.title)}">${esc(v.title)}</span>
          <span class="muted nowrap">${bytes(v.size)} · <span class="seed">${v.seeders}</span> src · ${v.grabs} DL</span>
          <span class="slot" data-guid="${esc(v.guid)}">${this._actionHtml(v, list, byHash, true)}</span>
        </li>`).join("")}</ul>` : "";
    return `<article class="card rel ${art?.poster ? "has-poster" : ""}">
      ${visual}
      <div class="body">
        ${heading}
        <div class="meta">
          <span class="tags">${this._versionTags(r)}</span>
          <span><ha-icon icon="mdi:harddisk"></ha-icon>${bytes(r.size)}</span>
          <span class="seed" title="Sources"><ha-icon icon="mdi:arrow-up-bold-circle"></ha-icon>${r.seeders}</span>
          <span class="leech" title="Clients"><ha-icon icon="mdi:arrow-down-bold-circle"></ha-icon>${r.leechers}</span>
          <span title="Téléchargements complétés"><ha-icon icon="mdi:check-all"></ha-icon>${r.grabs}</span>
          <span title="${esc(r.published ? new Date(r.published).toLocaleString("fr-FR") : "")}"><ha-icon icon="mdi:clock-outline"></ha-icon>${esc(ago(r.published))}</span>
          ${r.freeleech ? `<span class="badge free">Freeleech</span>` : ""}
          ${others ? `<button class="linkbtn" data-action="versions" data-group="${esc(g.group)}">
              <ha-icon icon="${open ? "mdi:chevron-up" : "mdi:chevron-down"}"></ha-icon>${open ? "Masquer" : `+${others} version${others > 1 ? "s" : ""}`}</button>` : ""}
        </div>
        ${versions}
      </div>
      <div class="act">
        ${r.details_url ? `<a class="ghost" href="${esc(r.details_url)}" target="_blank" rel="noopener noreferrer" title="Voir la fiche sur C411"><ha-icon icon="mdi:open-in-new"></ha-icon></a>` : ""}
        <span class="slot" data-guid="${esc(r.guid)}">${this._actionHtml(r, list, byHash)}</span>
      </div>
    </article>`;
  }

  _episodeLabel(r) {
    const i = r.info || {};
    if (i.kind === "episode") return ` <span class="ep">S${String(i.season).padStart(2, "0")}E${String(i.episodes[0]).padStart(2, "0")}${i.episodes.length > 1 ? "-E" + String(i.episodes.at(-1)).padStart(2, "0") : ""}</span>`;
    if (i.kind === "pack") return ` <span class="ep">Saison ${i.season}</span>`;
    return "";
  }

  _listHtml(items, list) {
    const byHash = this._torrentByHash();
    const groups = this._sortedGroups(this._groups(items));
    this._askArtwork(groups);
    return { html: this._posterHint() + groups.map((g) => this._groupHtml(g, list, byHash)).join(""), count: groups.length };
  }

  _posterHint() {
    const s = this._s;
    if (!s.config || s.config.artwork || !s.perms.manage || this._hintClosed()) return "";
    return `<div class="notice info"><ha-icon icon="mdi:image-outline"></ha-icon>
      <span>Pour afficher les affiches des films et séries, connectez Plex :
      <b>Paramètres → Appareils et services → TorrentManager → Configurer → Connexion Plex</b>.
      Les affiches et les recommandations viennent du catalogue Plex, sans autre compte.</span>
      <button class="ghost sm" data-action="close-hint" title="Masquer"><ha-icon icon="mdi:close"></ha-icon></button></div>`;
  }

  _hintClosed() {
    try { return window.localStorage.getItem("c411-hint-art") === "1"; } catch (e) { return false; }
  }

  _renderLatest() {
    const el = this.shadowRoot.getElementById("list-latest"); if (!el) return;
    const s = this._s;
    if (s.latestLoading && !s.latest.length) { el.innerHTML = skeleton(); return; }
    const items = s.latest.filter((r) => this._matchesTop(r, s.latestCats));
    const { html: listHtml, count } = this._listHtml(items, "latest");
    let html = "";
    if (s.latestError) html += `<div class="notice err"><ha-icon icon="mdi:alert"></ha-icon>${esc(s.latestError)}</div>`;
    if (s.latestUpdate) html += `<div class="hint">Mis à jour ${esc(ago(s.latestUpdate))} · ${count} contenu${count > 1 ? "s" : ""}${count !== items.length ? ` (${items.length} releases)` : ""}${s.latestLoading ? " · actualisation…" : ""}</div>`;
    html += count ? listHtml : empty("mdi:inbox", "Aucune nouveauté pour ces filtres.");
    el.innerHTML = html;
  }

  _renderResults() {
    const el = this.shadowRoot.getElementById("list-search"); if (!el) return;
    const s = this._s;
    if (s.searchLoading && !s.results?.length) { el.innerHTML = skeleton(); return; }
    let html = s.searchError ? `<div class="notice err"><ha-icon icon="mdi:alert"></ha-icon>${esc(s.searchError)}</div>` : "";
    if (s.results === null) {
      el.innerHTML = html + empty("mdi:movie-search-outline", "Cherchez un film, une série, un album…<br><small>C411 limite l'API à 15 requêtes par minute.</small>");
      return;
    }
    const { html: listHtml, count } = this._listHtml(s.results, "search");
    html += count ? `<div class="hint">${count} contenu${count > 1 ? "s" : ""}${count !== s.results.length ? ` (${s.results.length} releases)` : ""}${s.lastQuery ? ` pour « ${esc(s.lastQuery)} »` : ""}</div>` + listHtml
      : empty("mdi:emoticon-sad-outline", s.results.length ? "Aucune version ne correspond aux filtres qualité / langue." : "Aucun résultat. Essayez moins de mots ou une autre catégorie.");
    if (s.more) html += `<button class="btn more" data-action="more" ${s.searchLoading ? "disabled" : ""}>${s.searchLoading ? '<span class="spin"></span>' : ""}Afficher plus</button>`;
    el.innerHTML = html;
  }

  _renderDownloads() {
    const root = this.shadowRoot; const el = root.getElementById("list-downloads"); if (!el) return;
    const s = this._s;
    root.querySelectorAll("#chips-dl .chip").forEach((c) => c.classList.toggle("on", c.dataset.dl === s.dlFilter));
    if (s.qbError && !s.qb) { el.innerHTML = `<div class="notice err"><ha-icon icon="mdi:lan-disconnect"></ha-icon>${esc(s.qbError)}</div>`; return; }
    if (!s.qb) { el.innerHTML = skeleton(); return; }
    let list = s.qb.torrents || [];
    if (s.dlFilter === "c411") list = list.filter((t) => t.is_c411);
    if (s.dlFilter === "active") list = list.filter((t) => (STATES[t.state] || [])[1] === "dl" || (t.progress < 1 && !PAUSED.has(t.state)));
    if (!list.length) {
      el.innerHTML = empty("mdi:download-off", s.dlFilter === "c411"
        ? "Aucun torrent envoyé depuis C411 pour l'instant.<br><small>Utilisez « Télécharger » dans Nouveautés ou Recherche.</small>"
        : "Aucun torrent.");
      return;
    }
    el.innerHTML = list.map((t) => this._torrentHtml(t)).join("");
  }

  _torrentHtml(t) {
    const [label, kind] = STATES[t.state] || [t.state, "wait"];
    const pct = Math.min(100, (t.progress || 0) * 100);
    const done = pct >= 100;
    const paused = PAUSED.has(t.state);
    const confirm = this._s.confirm === t.hash;
    const h = esc(t.hash);
    const perms = this._s.perms;
    const actions = !perms.download ? "" : confirm
      ? `<span class="confirm">Supprimer ?
          <button class="btn danger sm" data-action="delete" data-hash="${h}">Torrent seul</button>
          <button class="btn danger sm" data-action="delete_files" data-hash="${h}">+ fichiers</button>
          <button class="ghost" data-action="cancel" title="Annuler"><ha-icon icon="mdi:close"></ha-icon></button></span>`
      : `<button class="ghost" data-action="${paused ? "resume" : "pause"}" data-hash="${h}" title="${paused ? "Reprendre" : "Pause"}">
            <ha-icon icon="${paused ? "mdi:play" : "mdi:pause"}"></ha-icon></button>
         ${perms.manage ? `<button class="ghost" data-action="recheck" data-hash="${h}" title="Revérifier"><ha-icon icon="mdi:file-check-outline"></ha-icon></button>
         <button class="ghost" data-action="confirm" data-hash="${h}" title="Supprimer"><ha-icon icon="mdi:delete-outline"></ha-icon></button>` : ""}`;
    const left = done ? bytes(t.size) : `${bytes(t.size - (t.amount_left || 0))} / ${bytes(t.size)}`;
    return `<article class="card tor ${kind}">
      <div class="top">
        <div class="t" title="${esc(t.name)}">${esc(t.name)}</div>
        <div class="act">${actions}</div>
      </div>
      <div class="bar"><div style="width:${pct.toFixed(1)}%"></div></div>
      <div class="meta">
        <span class="state ${kind}">${esc(label)}</span>
        <span><b>${nf1.format(pct)} %</b> · ${left}</span>
        ${!done && !paused ? `<span><ha-icon icon="mdi:arrow-down-bold"></ha-icon>${speed(t.dlspeed)}</span><span><ha-icon icon="mdi:timer-sand"></ha-icon>${eta(t.eta)}</span>` : ""}
        ${t.upspeed ? `<span><ha-icon icon="mdi:arrow-up-bold"></ha-icon>${speed(t.upspeed)}</span>` : ""}
        <span title="Sources / clients"><ha-icon icon="mdi:account-multiple"></ha-icon>${t.num_seeds} / ${t.num_leechs}</span>
        <span title="Ratio"><ha-icon icon="mdi:scale-balance"></ha-icon>${nf1.format(t.ratio || 0)}</span>
        ${t.category ? `<span class="badge">${esc(t.category)}</span>` : ""}
      </div>
    </article>`;
  }

  _destination(rel) {
    const s = this._s;
    const f = (s.config?.folders || []).find((x) => x.type === rel.content_type);
    const cat = s.qbCategory === AUTO ? (f?.category || "") : s.qbCategory;
    const parts = [];
    if (f) parts.push(f.label);
    parts.push(f?.path || "dossier par défaut");
    if (cat) parts.push(`catégorie ${cat}`);
    return parts.join(" · ");
  }

  // ---------------------------------------------------------------- séries
  async _loadSeries() {
    if (!this._hass || !this._built) return;
    const s = this._s;
    s.seriesLoading = !s.series;
    try { s.series = await this._ws({ type: "c411/series" }); s.seriesError = null; }
    catch (e) { s.seriesError = this._msg(e); }
    s.seriesLoading = false;
    this._renderStats();
    if (s.tab === "series") this._renderSeries();
  }

  async _seriesCall(msg, okText, busyKey) {
    const s = this._s;
    if (s.seriesBusy.has(busyKey)) return;
    s.seriesBusy.add(busyKey); this._renderSeries();
    try {
      s.series = await this._ws(msg);
      if (okText) this._toast(okText);
      else if (msg.rating_key) {
        const show = s.series.shows.find((x) => x.rating_key === msg.rating_key);
        this._toast(show?.available.length ? `${show.available.length} épisode(s) trouvé(s) pour ${show.title}` : `Rien de nouveau pour ${show?.title || "cette série"}`);
      }
      if (msg.type === "c411/series_grab") setTimeout(() => this._loadTorrents(), 1500);
    } catch (e) { this._toast(this._msg(e), true); }
    s.seriesBusy.delete(busyKey);
    this._renderSeries(); this._renderStats();
  }

  async _seriesPref(key, pref, value) {
    try {
      this._s.series = await this._ws({ type: "c411/series_update", rating_key: key, [pref]: value });
    } catch (e) { this._toast(this._msg(e), true); }
    this._renderSeries(); this._renderStats();
  }

  _renderSeries() {
    const root = this.shadowRoot; const el = root.getElementById("list-series"); if (!el) return;
    const s = this._s;
    root.querySelectorAll("#chips-series .chip").forEach((c) => c.classList.toggle("on", c.dataset.sf === s.seriesFilter));
    const busyAll = s.seriesBusy.has("all");
    root.querySelectorAll('[data-action="series-check"],[data-action="series-library"]').forEach((b) => (b.disabled = busyAll || !s.perms.download));
    const status = root.getElementById("series-status");
    if (s.seriesError) { el.innerHTML = `<div class="notice err"><ha-icon icon="mdi:alert"></ha-icon>${esc(s.seriesError)}</div>`; return; }
    if (!s.series) { el.innerHTML = skeleton(); status.textContent = ""; return; }
    if (!s.series.configured) {
      status.textContent = "";
      el.innerHTML = empty("mdi:plex", `Plex n'est pas encore connecté.<br><small>Paramètres → Appareils et services → C411 → Configurer → <b>Connexion Plex</b>,
        puis <b>Suivi des séries</b> pour régler qualité, langues et téléchargement automatique.</small>`);
      return;
    }
    const d = s.series;
    const bits = [];
    if (d.server_name) bits.push(`<ha-icon icon="mdi:plex"></ha-icon> ${esc(d.server_name)}`);
    bits.push(`${d.followed} série${d.followed > 1 ? "s" : ""} suivie${d.followed > 1 ? "s" : ""} sur ${d.shows.length}`);
    bits.push(d.auto ? `<span class="ok">téléchargement automatique activé</span>` : `<span class="warn">téléchargement automatique désactivé</span>`);
    if (d.last_check) bits.push(`dernière vérification ${esc(ago(d.last_check))}`);
    if (busyAll) bits.push(`<span class="spin"></span> en cours…`);
    status.innerHTML = bits.join(" · ") +
      (d.last_check_error ? `<div class="notice err"><ha-icon icon="mdi:alert"></ha-icon>C411 : ${esc(d.last_check_error)}</div>` : "") +
      (d.library_error ? `<div class="notice err"><ha-icon icon="mdi:alert"></ha-icon>Plex : ${esc(d.library_error)}</div>` : "");

    const q = s.seriesQuery.trim().toLowerCase();
    let shows = d.shows;
    if (s.seriesFilter === "followed") shows = shows.filter((x) => x.follow);
    if (s.seriesFilter === "available") shows = shows.filter((x) => x.available.length);
    if (q) shows = shows.filter((x) => x.title.toLowerCase().includes(q));
    if (!shows.length) {
      el.innerHTML = empty("mdi:television-off", s.seriesFilter === "available" ? "Aucun nouvel épisode trouvé pour l'instant." : "Aucune série.");
      return;
    }
    el.innerHTML = shows.map((x) => this._showHtml(x, d.poster_secret)).join("");
  }

  _showHtml(x, secret) {
    const s = this._s;
    const k = esc(x.rating_key);
    const statusPill = {
      available: `<span class="pill2 new"><ha-icon icon="mdi:new-box"></ha-icon>${x.available.length} disponible${x.available.length > 1 ? "s" : ""}</span>`,
      grabbed: `<span class="pill2 dl"><ha-icon icon="mdi:progress-download"></ha-icon>En téléchargement</span>`,
      up_to_date: `<span class="pill2 ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon>À jour</span>`,
    }[x.status];
    const poster = x.has_poster
      ? `<img loading="lazy" src="/api/c411/plex/poster/${encodeURIComponent(x.rating_key)}?s=${encodeURIComponent(secret)}" alt="">`
      : `<div class="noposter"><ha-icon icon="mdi:television-classic"></ha-icon></div>`;
    const avail = x.available.map((a) => {
      const busy = s.seriesBusy.has(x.rating_key + a.key);
      return `<li><b>${esc(a.key)}</b>
        <span class="tags"><span class="tag">${esc(a.quality)}</span><span class="tag">${esc({ vf: "VF", vostfr: "VOSTFR", vo: "VO" }[a.languages] || a.languages)}</span></span>
        <span class="muted" title="${esc(a.title)}">${bytes(a.size)} · ${a.seeders} src</span>
        ${s.perms.download ? `<button class="btn primary xs" data-action="ep-grab" data-key="${k}" data-ep="${esc(a.key)}" title="${esc(a.title)}" ${busy ? "disabled" : ""}>
          ${busy ? '<span class="spin"></span>' : '<ha-icon icon="mdi:download"></ha-icon>'}</button>` : ""}</li>`;
    }).join("");
    const grabbed = x.grabbed.map((g) => `<li><b>${esc(g.code)}</b>
        <span class="muted" title="${esc(g.title)}">envoyé ${esc(ago(g.at))}${g.auto ? " · auto" : ""}</span>
        ${s.perms.manage ? `<button class="ghost sm" data-action="ep-forget" data-key="${k}" data-ep="${esc(g.code)}" title="Oublier (permet de le retélécharger)"><ha-icon icon="mdi:backup-restore"></ha-icon></button>` : ""}</li>`).join("");
    const checking = s.seriesBusy.has(x.rating_key);
    return `<article class="card show ${x.follow ? "" : "off"}">
      <div class="poster">${poster}</div>
      <div class="sbody">
        <div class="t">${esc(x.title)}${x.year ? ` <span class="muted">(${x.year})</span>` : ""}</div>
        <div class="meta"><span>${x.last ? `Dernier : <b>${esc(x.last)}</b>` : "Aucun épisode"}</span>
          <span>${x.episode_count} ép. · ${x.season_count} saison${x.season_count > 1 ? "s" : ""}</span></div>
        <div class="row tight">${x.follow ? statusPill : `<span class="pill2">Non suivie</span>`}
          ${(x.new_seasons || []).map((n) => `<span class="pill2 season"><ha-icon icon="mdi:party-popper"></ha-icon>Saison ${n}</span>`).join("")}</div>
        <div class="switches">
          <label class="sw ${s.perms.manage ? "" : "dis"}"><input type="checkbox" data-pref="follow" data-key="${k}" ${x.follow ? "checked" : ""} ${s.perms.manage ? "" : "disabled"}><span></span>Suivre</label>
          <label class="sw ${x.follow && s.perms.manage ? "" : "dis"}" title="Télécharger automatiquement les nouveaux épisodes"><input type="checkbox" data-pref="auto" data-key="${k}" ${x.auto ? "checked" : ""} ${x.follow && s.perms.manage ? "" : "disabled"}><span></span>Auto</label>
          <button class="ghost sm" data-action="show-check" data-key="${k}" title="Chercher sur C411 maintenant" ${checking || !s.perms.download ? "disabled" : ""}>
            ${checking ? '<span class="spin"></span>' : '<ha-icon icon="mdi:magnify"></ha-icon>'}</button>
        </div>
        ${avail ? `<ul class="eps">${avail}</ul>` : ""}
        ${grabbed ? `<ul class="eps grabbed">${grabbed}</ul>` : ""}
      </div>
    </article>`;
  }

  // ---------------------------------------------------------------- pour vous
  async _loadRecs(refresh) {
    const s = this._s;
    s.recsLoading = true; this._renderForYou();
    try { s.recs = await this._ws({ type: "c411/recommendations", refresh }); s.recsError = null; }
    catch (e) { s.recsError = this._msg(e); }
    s.recsLoading = false; this._renderForYou();
  }

  _renderForYou() {
    const el = this.shadowRoot.getElementById("list-foryou"); if (!el) return;
    const s = this._s;
    let html = `<div class="row section-head"><h2>Recommandé pour vous</h2><span class="grow"></span>
      <button class="btn outline sm" data-action="recs-refresh" ${s.recsLoading ? "disabled" : ""}>
        ${s.recsLoading ? '<span class="spin"></span>' : '<ha-icon icon="mdi:refresh"></ha-icon>'}Actualiser</button></div>`;
    if (s.recsError) html += `<div class="notice err"><ha-icon icon="mdi:alert"></ha-icon>${esc(s.recsError)}</div>`;
    else if (!s.recs) html += `<div class="recgrid">${Array.from({ length: 8 }, () => '<div class="card skel rec-skel"></div>').join("")}</div>`;
    else if (!s.recs.configured) {
      html += `<div class="notice info"><ha-icon icon="mdi:star-shooting-outline"></ha-icon><span>${s.perms.manage
        ? `Les recommandations utilisent le catalogue Plex. Connectez Plex dans <b>Paramètres → Appareils et services → TorrentManager → Configurer → Connexion Plex</b>.`
        : "Les recommandations ne sont pas encore activées par l'administrateur."}</span></div>`;
    } else if (!s.recs.items.length) {
      html += empty("mdi:movie-open-star-outline", s.recs.seeds.length
        ? "Pas de recommandation pour l'instant."
        : "Téléchargez quelques films ou séries depuis TorrentManager (ou suivez des séries Plex) : les recommandations apparaîtront ici.");
    } else {
      const seeds = s.recs.seeds.map((x) => x.title);
      html += `<div class="hint">D'après ${seeds.slice(0, 6).map(esc).join(", ")}${seeds.length > 6 ? ` et ${seeds.length - 6} autre${seeds.length - 6 > 1 ? "s" : ""}` : ""}.</div>`;
      html += `<div class="recgrid">${s.recs.items.map((r, i) => this._recHtml(r, i)).join("")}</div>`;
    }
    // Populaire en ce moment (toujours disponible)
    const pop = this._groups(s.latest.filter((r) => ["movies", "series", "anime"].includes(r.content_type)))
      .sort((a, b) => (b.best.grabs || 0) - (a.best.grabs || 0)).slice(0, 8);
    if (pop.length) {
      this._askArtwork(pop);
      const byHash = this._torrentByHash();
      html += `<div class="row section-head"><h2>Populaire en ce moment sur C411</h2></div>
        <div class="list">${pop.map((g) => this._groupHtml(g, "latest", byHash)).join("")}</div>`;
    }
    el.innerHTML = html;
  }

  _recHtml(r, i) {
    const kind = r.media === "tv" ? "Série" : "Film";
    return `<article class="card rec">
      <div class="rposter">${r.poster ? `<img loading="lazy" src="${esc(r.poster)}" alt="">` : `<div class="noposter"><ha-icon icon="${r.media === "tv" ? "mdi:television-classic" : "mdi:movie-open"}"></ha-icon></div>`}
        <span class="kind">${kind}</span></div>
      <div class="rbody">
        <div class="t">${esc(r.title)}</div>
        <div class="meta">${r.year ? `<span>${r.year}</span>` : ""}${r.vote ? `<span class="vote"><ha-icon icon="mdi:star"></ha-icon>${nf1.format(r.vote)}</span>` : ""}</div>
        ${r.overview ? `<p class="ov">${esc(r.overview)}</p>` : ""}
        <div class="because">Parce que vous avez : ${r.because.map(esc).join(", ")}</div>
        <button class="btn primary sm" data-action="rec-find" data-idx="${i}"><ha-icon icon="mdi:magnify"></ha-icon>Trouver sur C411</button>
      </div>
    </article>`;
  }

  _toast(text, error = false) {
    const el = this.shadowRoot.getElementById("toast"); if (!el) return;
    el.textContent = text;
    el.className = `toast ${error ? "err" : ""}`;
    el.hidden = false;
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => (el.hidden = true), error ? 6000 : 3500);
  }
}

function empty(icon, text) {
  return `<div class="empty"><ha-icon icon="${icon}"></ha-icon><p>${text}</p></div>`;
}
function skeleton() {
  return Array.from({ length: 6 }, () => `<div class="card skel"><div></div><div></div></div>`).join("");
}

const STYLE = `
:host {
  display: block; min-height: 100vh;
  background: var(--primary-background-color);
  color: var(--primary-text-color);
  font-family: var(--ha-font-family-body, Roboto, sans-serif);
  --c-accent: var(--primary-color, #03a9f4);
  --c-card: var(--card-background-color, #fff);
  --c-div: var(--divider-color, rgba(0,0,0,.12));
  --c-sub: var(--secondary-text-color, #727272);
  --c-ok: var(--success-color, #43a047);
  --c-warn: var(--warning-color, #ffa600);
  --c-err: var(--error-color, #db4437);
  --radius: var(--ha-card-border-radius, 12px);
}
* { box-sizing: border-box; }
ha-icon { --mdc-icon-size: 18px; }
.toolbar {
  position: sticky; top: 0; z-index: 3;
  display: flex; align-items: center; gap: 8px; height: 56px; padding: 0 12px 0 4px;
  background: var(--app-header-background-color, var(--c-accent));
  color: var(--app-header-text-color, #fff);
  border-bottom: var(--app-header-border-bottom, none);
}
.toolbar .title { font-size: 20px; font-weight: 500; display: flex; align-items: center; gap: 8px; flex: 1; }
.toolbar .title ha-icon { --mdc-icon-size: 24px; }
.stats { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.pill { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 999px;
  background: rgba(255,255,255,.18); font-size: 13px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.pill.err { background: var(--c-err); }
.tabs { position: sticky; top: 56px; z-index: 2; display: flex; gap: 4px; padding: 0 12px;
  background: var(--c-card); border-bottom: 1px solid var(--c-div); overflow-x: auto; }
.tabs button { all: unset; cursor: pointer; display: flex; align-items: center; gap: 6px; padding: 14px 14px 12px;
  color: var(--c-sub); font-weight: 500; border-bottom: 2px solid transparent; white-space: nowrap; }
.tabs button.active { color: var(--c-accent); border-bottom-color: var(--c-accent); }
.tabs button b { background: var(--c-accent); color: #fff; border-radius: 999px; font-size: 11px; padding: 1px 7px; }
.tabs button b:empty { display: none; }
main { max-width: 1100px; margin: 0 auto; padding: 16px 12px 80px; }
.controls { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
.row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 5px; padding: 6px 12px; border-radius: 999px;
  border: 1px solid var(--c-div); background: var(--c-card); font-size: 13px; color: var(--primary-text-color); transition: .15s; }
.chip ha-icon { --mdc-icon-size: 16px; color: var(--c-sub); }
.chip:hover { border-color: var(--c-accent); }
.chip.on { background: var(--c-accent); border-color: var(--c-accent); color: #fff; }
.chip.on ha-icon { color: #fff; }
select, input[type=search] { font: inherit; color: var(--primary-text-color); background: var(--c-card);
  border: 1px solid var(--c-div); border-radius: 8px; padding: 6px 8px; }
.sort, .send-options label { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--c-sub); }
.send-options { display: inline-flex; gap: 12px; align-items: center; margin-left: auto; }
.check input { accent-color: var(--c-accent); }
.search { display: flex; align-items: center; gap: 8px; background: var(--c-card); border: 1px solid var(--c-div);
  border-radius: 999px; padding: 6px 6px 6px 16px; margin-bottom: 12px; box-shadow: var(--ha-card-box-shadow, none); }
.search:focus-within { border-color: var(--c-accent); }
.search input { flex: 1; border: 0; background: transparent; font-size: 16px; padding: 8px 0; outline: none; min-width: 0; }
.search ha-icon { color: var(--c-sub); --mdc-icon-size: 22px; }
.list { display: flex; flex-direction: column; gap: 8px; }
.hint { font-size: 12px; color: var(--c-sub); margin: 0 4px 2px; }
.card { background: var(--c-card); border-radius: var(--radius); border: 1px solid var(--c-div);
  box-shadow: var(--ha-card-box-shadow, none); }
.rel { display: flex; align-items: center; gap: 12px; padding: 10px 12px; transition: border-color .15s; }
.rel:hover { border-color: var(--c-accent); }
.rel .ico { flex: none; width: 40px; height: 40px; border-radius: 10px; display: grid; place-items: center;
  background: color-mix(in srgb, var(--c-accent) 14%, transparent); color: var(--c-accent); }
.rel .ico ha-icon { --mdc-icon-size: 22px; }
.rel .body { flex: 1; min-width: 0; }
.t { font-weight: 500; line-height: 1.3; word-break: break-word; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 4px; font-size: 12.5px; color: var(--c-sub);
  font-variant-numeric: tabular-nums; align-items: center; }
.meta span { display: inline-flex; align-items: center; gap: 3px; }
.meta ha-icon { --mdc-icon-size: 14px; }
.seed { color: var(--c-ok); } .leech { color: var(--c-warn); }
.badge { padding: 1px 8px; border-radius: 999px; background: var(--secondary-background-color, rgba(0,0,0,.06)); color: var(--primary-text-color); }
.badge.free { background: var(--c-ok); color: #fff; }
.act { display: flex; align-items: center; gap: 4px; flex: none; }
.btn { all: unset; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 8px 14px; border-radius: 999px; font-weight: 500; font-size: 14px; white-space: nowrap; min-width: 120px; }
.btn.primary { background: var(--c-accent); color: var(--text-primary-color, #fff); }
.btn.primary:hover { filter: brightness(1.08); }
.btn[disabled] { opacity: .7; cursor: default; }
.btn.have { background: color-mix(in srgb, var(--c-ok) 15%, transparent); color: var(--c-ok); }
.btn.danger { background: var(--c-err); color: #fff; }
.btn.sm { padding: 5px 10px; font-size: 12.5px; min-width: 0; }
.btn.more { align-self: center; margin-top: 8px; border: 1px solid var(--c-div); color: var(--c-accent); }
.ghost { all: unset; cursor: pointer; display: inline-grid; place-items: center; width: 36px; height: 36px; border-radius: 50%; color: var(--c-sub); }
.ghost:hover { background: var(--secondary-background-color, rgba(0,0,0,.06)); color: var(--primary-text-color); }
.ghost ha-icon { --mdc-icon-size: 20px; }
.tor { padding: 12px 14px; }
.tor .top { display: flex; align-items: flex-start; gap: 8px; }
.tor .top .t { flex: 1; min-width: 0; }
.bar { height: 6px; border-radius: 3px; background: var(--c-div); overflow: hidden; margin: 8px 0 6px; }
.bar div { height: 100%; background: var(--c-accent); border-radius: 3px; transition: width .6s ease; }
.tor.up .bar div, .tor.done .bar div { background: var(--c-ok); }
.tor.paused .bar div { background: var(--c-sub); }
.tor.err .bar div { background: var(--c-err); }
.tor.wait .bar div { background: var(--c-warn); }
.state { font-weight: 600; }
.state.dl { color: var(--c-accent); } .state.up, .state.done { color: var(--c-ok); }
.state.err { color: var(--c-err); } .state.wait { color: var(--c-warn); }
.confirm { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; flex-wrap: wrap; justify-content: flex-end; }
.notice { display: flex; gap: 8px; align-items: center; padding: 10px 14px; border-radius: var(--radius); font-size: 14px; }
.notice.info { background: color-mix(in srgb, var(--c-accent) 10%, transparent); color: var(--primary-text-color); font-size: 13px; }
.notice.info > span { flex: 1; }
.notice.info > ha-icon { color: var(--c-accent); }
.notice.err { background: color-mix(in srgb, var(--c-err) 12%, transparent); color: var(--c-err); }
.empty { text-align: center; color: var(--c-sub); padding: 56px 16px; }
.empty ha-icon { --mdc-icon-size: 56px; opacity: .5; }
.empty small { opacity: .8; }
.skel { height: 64px; padding: 14px; display: flex; flex-direction: column; gap: 8px; }
.skel div { height: 12px; border-radius: 6px; background: var(--c-div); animation: pulse 1.2s infinite ease-in-out; }
.skel div:last-child { width: 45%; }
@keyframes pulse { 50% { opacity: .4; } }
.spin { width: 14px; height: 14px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%;
  animation: rot .7s linear infinite; }
@keyframes rot { to { transform: rotate(360deg); } }
.toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); z-index: 10; max-width: min(92vw, 560px);
  background: var(--primary-text-color, #222); color: var(--primary-background-color, #fff); padding: 12px 18px;
  border-radius: 10px; box-shadow: 0 6px 24px rgba(0,0,0,.25); font-size: 14px; }
.toast.err { background: var(--c-err); color: #fff; }
[hidden] { display: none !important; }
.section-head { margin: 4px 0 10px; }
.section-head h2 { font-size: 18px; font-weight: 500; margin: 0; }
#list-foryou .list { margin-bottom: 16px; }
.recgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(200px, 100%), 1fr)); gap: 12px; margin: 8px 0 24px; }
.rec { display: flex; flex-direction: column; overflow: hidden; }
.rposter { position: relative; aspect-ratio: 2/3; background: var(--secondary-background-color, rgba(0,0,0,.06)); }
.rposter img { width: 100%; height: 100%; object-fit: cover; display: block; }
.rposter .noposter ha-icon { --mdc-icon-size: 48px; }
.rposter .kind { position: absolute; top: 8px; left: 8px; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px;
  background: rgba(0,0,0,.65); color: #fff; }
.rbody { padding: 10px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
.rbody .meta { margin-top: 0; }
.rbody .vote { margin-left: 0; }
.ov { margin: 0; font-size: 12.5px; color: var(--c-sub); display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.because { font-size: 11.5px; color: var(--c-sub); font-style: italic; margin-top: auto; }
.rbody .btn { align-self: stretch; }
.rec-skel { aspect-ratio: 2/3.6; }
.view-options { gap: 8px; font-size: 13px; }
.vlabel { color: var(--c-sub); }
.seg { display: inline-flex; border: 1px solid var(--c-div); border-radius: 999px; overflow: hidden; background: var(--c-card); }
.seg button { all: unset; cursor: pointer; padding: 4px 10px; font-size: 12.5px; color: var(--primary-text-color); }
.seg button + button { border-left: 1px solid var(--c-div); }
.seg button.on { background: var(--c-accent); color: #fff; }
.view-options .sw { margin-left: 6px; }
.poster-sm { flex: none; width: 54px; aspect-ratio: 2/3; object-fit: cover; border-radius: 6px; background: var(--c-div); align-self: flex-start; }
.rel.has-poster { align-items: flex-start; }
.rel .sub { font-size: 12px; color: var(--c-sub); margin-top: 1px; word-break: break-all; }
.ep { font-size: 12px; font-weight: 600; padding: 1px 6px; border-radius: 4px; background: color-mix(in srgb, var(--c-accent) 14%, transparent); color: var(--c-accent); }
.vote { display: inline-flex; align-items: center; gap: 2px; font-size: 12px; color: var(--c-warn); font-weight: 600; margin-left: 4px; }
.vote ha-icon { --mdc-icon-size: 14px; }
.linkbtn { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 2px; color: var(--c-accent); font-weight: 500; }
.linkbtn:hover { text-decoration: underline; }
.versions { list-style: none; padding: 0; margin: 8px 0 0; display: flex; flex-direction: column; gap: 4px; }
.versions li { display: flex; align-items: center; gap: 8px; font-size: 12.5px; padding: 4px 6px 4px 8px; border-radius: 8px; background: var(--secondary-background-color, rgba(0,0,0,.04)); }
.versions li.top { background: color-mix(in srgb, var(--c-ok) 10%, transparent); }
.versions .vt { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--c-sub); }
.nowrap { white-space: nowrap; }
.versions .btn.have { min-width: 0; padding: 4px 10px; font-size: 12px; }
.grow { flex: 1; }
.filter { min-width: 140px; border-radius: 999px; padding: 6px 12px; }
.btn.outline { border: 1px solid var(--c-div); color: var(--primary-text-color); }
.btn.outline:hover { border-color: var(--c-accent); }
.btn.xs { padding: 4px 10px; min-width: 0; font-size: 12px; }
.btn.xs ha-icon { --mdc-icon-size: 16px; }
.hint .ok { color: var(--c-ok); } .hint .warn { color: var(--c-warn); }
.hint ha-icon { --mdc-icon-size: 14px; vertical-align: -2px; }
.hint .notice { margin-top: 6px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(360px, 100%), 1fr)); gap: 10px; }
.show { display: flex; gap: 12px; padding: 10px; align-items: flex-start; }
.show.off { opacity: .6; }
.show .poster { flex: none; width: 92px; aspect-ratio: 2/3; border-radius: 8px; overflow: hidden; background: var(--secondary-background-color, rgba(0,0,0,.06)); }
.show .poster img { width: 100%; height: 100%; object-fit: cover; display: block; }
.noposter { width: 100%; height: 100%; display: grid; place-items: center; color: var(--c-sub); }
.noposter ha-icon { --mdc-icon-size: 32px; }
.sbody { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.sbody .meta { margin-top: 0; }
.muted { color: var(--c-sub); font-weight: 400; }
.row.tight { gap: 6px; }
.pill2 { display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px; border-radius: 999px; font-size: 12px; font-weight: 500;
  background: var(--secondary-background-color, rgba(0,0,0,.06)); color: var(--c-sub); }
.pill2 ha-icon { --mdc-icon-size: 14px; }
.pill2.new { background: color-mix(in srgb, var(--c-accent) 16%, transparent); color: var(--c-accent); }
.pill2.dl { background: color-mix(in srgb, var(--c-warn) 18%, transparent); color: var(--c-warn); }
.pill2.season { background: color-mix(in srgb, #9c27b0 16%, transparent); color: #9c27b0; }
.pill2.ok { background: color-mix(in srgb, var(--c-ok) 15%, transparent); color: var(--c-ok); }
.switches { display: flex; align-items: center; gap: 14px; font-size: 13px; }
.sw { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; }
.sw.dis { opacity: .5; cursor: default; }
.sw input { display: none; }
.sw span { width: 30px; height: 16px; border-radius: 999px; background: var(--c-div); position: relative; transition: .2s; }
.sw span::after { content: ""; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; border-radius: 50%; background: #fff; transition: .2s; box-shadow: 0 1px 2px rgba(0,0,0,.3); }
.sw input:checked + span { background: var(--c-accent); }
.sw input:checked + span::after { left: 16px; }
.switches .ghost { margin-left: auto; width: 30px; height: 30px; }
.ghost.sm { width: 28px; height: 28px; } .ghost.sm ha-icon { --mdc-icon-size: 17px; }
.eps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.eps li { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 4px 6px 4px 8px; border-radius: 8px;
  background: color-mix(in srgb, var(--c-accent) 7%, transparent); }
.eps.grabbed li { background: var(--secondary-background-color, rgba(0,0,0,.05)); }
.eps li .muted { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tags { display: inline-flex; gap: 4px; }
.tag { font-size: 11px; padding: 0 6px; border-radius: 4px; border: 1px solid var(--c-div); color: var(--c-sub); }
button[disabled] { opacity: .6; cursor: default; }
@media (max-width: 640px) {
  .rel { flex-wrap: wrap; }
  .rel .act { width: 100%; justify-content: flex-end; }
  .rel .ico { display: none; }
  .tabs button span { display: none; }
  .tabs button { flex: 1; justify-content: center; }
  .send-options { margin-left: 0; }
  .stats .pill:nth-child(2) { display: none; }
  .grid { grid-template-columns: minmax(0, 1fr); }
  .grow { display: none; }
  .show .poster { width: 64px; }
  .eps li .tags { display: none; }
  .filter { flex: 1; min-width: 0; }
  .versions .vt { display: none; }
  .recgrid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .ov { -webkit-line-clamp: 2; }
  .vlabel { display: none; }
}
`;

if (!customElements.get("c411-panel")) customElements.define("c411-panel", C411Panel);
