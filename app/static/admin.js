const listEl = document.getElementById("list");
const mainEl = document.getElementById("main");
const S = { quizzes: [], current: null, tab: "questions", pollTimer: null };

const fmtDate = (s) => new Date(s.replace(" ", "T") + "Z").toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
const notice = (msg, kind = "error") => h("p", { class: "notice " + kind, role: "alert" }, msg);
function toast(msg) {
  const t = h("div", { class: "toast", role: "status" }, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), 2400);
}

async function loadList() {
  S.quizzes = await api("/api/admin/quizzes");
  listEl.replaceChildren(...(S.quizzes.length ? S.quizzes.map((q) =>
    h("button", { class: "qitem", type: "button", "aria-current": String(S.current && S.current.id === q.id), onclick: () => openQuiz(q.id) },
      h("span", { class: "t" }, q.title),
      h("span", { class: "m" }, (q.published ? "Publié" : "Brouillon") + " · " + q.questions + " q. · " + q.responses + " rép."))) :
    [h("p", { class: "small muted", style: "padding:8px 12px" }, "Aucun questionnaire")]));
}

/* ------------------------------------------------------------ new */
async function renderNew() {
  S.current = null;
  loadList();
  if (!S.config) {
    try { S.config = await api("/api/admin/config"); } catch (_) { S.config = { transcribe: false }; }
  }
  const local = S.config.transcribe;
  const url = h("input", { type: "url", placeholder: "https://www.youtube.com/watch?v=…", autocomplete: "off" });
  const transcript = h("textarea", { rows: local ? "6" : "10", placeholder: local
    ? "Collez ici le texte de la vidéo si le téléchargement échoue"
    : "Collez ici tout le texte prononcé dans la vidéo" });
  const count = h("select", {}, [5, 8, 10, 15].map((n) => h("option", { value: n, selected: n === 10 }, n + " questions")));
  const status = h("div");
  const go = h("button", { class: "primary", type: "button" }, "Générer les questions");
  const manual = h("button", { type: "button" }, "Créer à la main");

  go.addEventListener("click", async () => {
    status.replaceChildren();
    go.disabled = manual.disabled = true;
    try {
      const r = await api("/api/admin/quizzes", { method: "POST", body: { video_url: url.value, transcript: transcript.value, count: +count.value } });
      pollJob(r.id, r.job, status, () => { go.disabled = manual.disabled = false; });
    } catch (e) {
      status.replaceChildren(notice(e.message));
      go.disabled = manual.disabled = false;
    }
  });
  manual.addEventListener("click", async () => {
    const r = await api("/api/admin/quizzes", { method: "POST", body: { video_url: url.value, generate: false } });
    openQuiz(r.id);
  });

  mainEl.replaceChildren(
    h("h2", {}, "Nouveau questionnaire"),
    h("p", { class: "muted", style: "margin-top:8px" }, local
      ? "Collez le lien d'une vidéo. Le site la transcrit puis écrit les questions. Vous les relisez avant de publier."
      : "Collez le texte de la vidéo, l'IA écrit les questions, vous les relisez avant de publier. Sur YouTube, le texte se trouve sous la vidéo, dans « Afficher la transcription »."),
    h("div", { class: "card stack", style: "margin-top:24px" },
      h("label", { class: "field" }, h("span", {}, local ? "Lien de la vidéo" : "Lien de la vidéo (affichée aux participants)"), url),
      h("label", { class: "field" }, h("span", {}, local ? "Transcription (facultatif)" : "Transcription"), transcript),
      h("label", { class: "field", style: "max-width:240px" }, h("span", {}, "Nombre de questions"), count),
      h("div", { class: "row wrap" }, go, manual), status));
}

function pollJob(quizId, jobId, status, finish) {
  clearInterval(S.pollTimer);
  const tick = async () => {
    try {
      const j = await api("/api/admin/jobs/" + jobId);
      if (j.state === "running") {
        status.replaceChildren(h("p", { class: "notice" }, j.step + "… cela peut prendre quelques minutes"));
      } else if (j.state === "done") {
        clearInterval(S.pollTimer); finish(); openQuiz(quizId);
      } else {
        clearInterval(S.pollTimer); finish();
        status.replaceChildren(notice(j.error || "La génération a échoué"),
          h("button", { type: "button", style: "margin-top:12px", onclick: () => openQuiz(quizId) }, "Ouvrir le brouillon et écrire les questions à la main"));
      }
    } catch (e) { clearInterval(S.pollTimer); finish(); status.replaceChildren(notice(e.message)); }
  };
  S.pollTimer = setInterval(tick, 2000); tick();
}

/* ------------------------------------------------------------ quiz */
async function openQuiz(id, tab) {
  clearInterval(S.pollTimer);
  S.current = await api("/api/admin/quizzes/" + id);
  S.tab = tab || "questions";
  await loadList();
  renderQuiz();
}

function renderQuiz() {
  const q = S.current;
  const msg = h("div");
  const title = h("input", { type: "text", class: "title-input", value: q.title, placeholder: "Titre du questionnaire", "aria-label": "Titre" });
  title.addEventListener("input", () => (q.title = title.value));
  const video = h("input", { type: "url", value: q.video_url, placeholder: "https://www.youtube.com/watch?v=…" });
  video.addEventListener("input", () => (q.video_url = video.value));
  const pub = h("input", { type: "checkbox", checked: q.published });
  pub.addEventListener("change", () => (q.published = pub.checked));
  const sc = h("input", { type: "checkbox", checked: q.show_score });
  sc.addEventListener("change", () => (q.show_score = sc.checked));

  const save = h("button", { class: "primary", type: "button" }, "Enregistrer");
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      S.current = await api("/api/admin/quizzes/" + q.id, { method: "PUT", body: {
        title: q.title, video_url: q.video_url, questions: q.questions, published: q.published, show_score: q.show_score } });
      await loadList(); renderQuiz();
      toast("Enregistré");
    } catch (e) { msg.replaceChildren(notice(e.message)); save.disabled = false; }
  });

  const link = location.origin + "/q/" + q.slug;
  const share = q.published ? h("div", { class: "link-box" },
    h("input", { type: "text", readonly: true, value: link, "aria-label": "Lien à partager" }),
    h("button", { type: "button", onclick: (e) => { navigator.clipboard.writeText(link); e.target.textContent = "Copié"; } }, "Copier"),
    h("a", { class: "btn", href: link, target: "_blank", rel: "noopener" }, "Ouvrir")) : null;

  const tabBtn = (id, label) => h("button", { class: "tab", type: "button", role: "tab", "aria-selected": String(S.tab === id), onclick: () => { S.tab = id; renderQuiz(); } }, label);

  mainEl.replaceChildren(
    h("div", { class: "row" }, title, save),
    h("div", { class: "card stack", style: "margin-top:16px" },
      h("label", { class: "field" }, h("span", {}, "Lien de la vidéo"), video),
      h("label", { class: "check" }, pub, h("span", {}, "Questionnaire ouvert aux participants")),
      h("label", { class: "check" }, sc, h("span", {}, "Montrer le score et la correction au participant à la fin")),
      share),
    msg,
    h("div", { class: "tabs", role: "tablist" }, tabBtn("questions", "Questions (" + q.questions.length + ")"), tabBtn("results", "Résultats")),
    h("div", { id: "tab-body" }));
  if (S.tab === "questions") renderQuestions(); else renderResults();
}

function renderQuestions() {
  const q = S.current, body = document.getElementById("tab-body");
  const cards = q.questions.map((it, qi) => {
    const text = h("textarea", { rows: "2", "aria-label": "Question " + (qi + 1) }, it.question);
    text.addEventListener("input", () => (it.question = text.value));
    const opts = it.options.map((o, oi) => {
      const pick = h("button", { class: "bubble pick", type: "button", role: "radio", "aria-checked": String(it.correct === oi), title: "Bonne réponse",
        onclick: () => { it.correct = oi; renderQuestions(); } }, LETTERS[oi]);
      const inp = h("input", { type: "text", value: o, "aria-label": "Réponse " + LETTERS[oi] });
      inp.addEventListener("input", () => (it.options[oi] = inp.value));
      const del = h("button", { class: "quiet small", type: "button", "aria-label": "Supprimer la réponse", disabled: it.options.length <= 2,
        onclick: () => { it.options.splice(oi, 1); if (it.correct === oi) it.correct = 0; else if (it.correct > oi) it.correct--; renderQuestions(); } }, "Retirer");
      return h("div", { class: "opt-row" }, pick, inp, del);
    });
    const expl = h("input", { type: "text", value: it.explanation || "", placeholder: "Explication affichée à la correction (facultatif)" });
    expl.addEventListener("input", () => (it.explanation = expl.value));
    return h("section", { class: "qedit" },
      h("div", { class: "row" }, h("span", { class: "mono muted small" }, String(qi + 1).padStart(2, "0")), h("span", { class: "spacer" }),
        h("button", { class: "quiet small del", type: "button", onclick: () => { q.questions.splice(qi, 1); renderQuiz(); } }, "Supprimer la question")),
      text, ...opts,
      h("div", {}, it.options.length < 6 ? h("button", { class: "quiet small", type: "button", onclick: () => { it.options.push(""); renderQuestions(); } }, "Ajouter une réponse") : null),
      expl);
  });
  body.replaceChildren(
    ...(cards.length ? [h("p", { class: "small muted" }, "Cliquez sur la bulle d'une réponse pour la marquer comme bonne. Relisez chaque question avant de publier.")] : []),
    h("div", { class: "stack" }, cards),
    h("div", { class: "row", style: "margin-top:16px" },
      h("button", { type: "button", onclick: () => { q.questions.push({ question: "", options: ["", "", "", ""], correct: 0, explanation: "" }); renderQuestions(); } }, "Ajouter une question"),
      h("span", { class: "spacer" }),
      h("button", { class: "quiet del", type: "button", onclick: async () => {
        if (!confirm("Supprimer ce questionnaire et toutes ses réponses ? Cette action est définitive.")) return;
        await api("/api/admin/quizzes/" + q.id, { method: "DELETE" }); renderNew(); } }, "Supprimer le questionnaire")));
}

async function renderResults() {
  const q = S.current, body = document.getElementById("tab-body");
  const rows = await api("/api/admin/quizzes/" + q.id + "/submissions");
  if (!rows.length) { body.replaceChildren(h("p", { class: "empty" }, "Aucune réponse pour le moment")); return; }
  const avg = rows.reduce((a, r) => a + r.score / r.total, 0) / rows.length;
  const total = rows[0].total;
  const counts = Array.from({ length: total + 1 }, (_, s) => rows.filter((r) => r.total === total && r.score === s).length);
  const peak = Math.max(...counts);
  const top = counts.indexOf(peak);
  body.replaceChildren(
    h("div", { class: "summary" },
      h("div", {},
        h("div", { class: "big" }, (avg * total).toFixed(1).replace(".", ","), h("small", {}, " / " + total)),
        h("p", { class: "cap" }, "Score moyen sur " + rows.length + " réponse" + (rows.length > 1 ? "s" : ""))),
      h("div", { class: "hist", role: "img", "aria-label": "Répartition des scores" }, counts.map((c, s) =>
        h("div", { class: "col" + (s === top && peak ? " top" : ""), title: c + " personne" + (c > 1 ? "s" : "") + " à " + s + "/" + total },
          h("div", { class: "bar", style: "height:" + (peak ? Math.round((c / peak) * 88) : 0) + "px" }),
          h("span", { class: "lbl" }, String(s)))))),
    h("div", { class: "row", style: "margin-bottom:16px" },
      h("p", { class: "muted small" }, "Chaque colonne compte les personnes ayant obtenu ce score"),
      h("span", { class: "spacer" }),
      h("a", { class: "btn", href: "/api/admin/quizzes/" + q.id + "/export.csv" }, "Exporter en CSV")),
    h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Date", "Nom", "Prénom", "Téléphone", "E-mail", "Entreprise"].map((t) => h("th", {}, t)), h("th", { class: "num" }, "Score"), h("th", {}))),
      h("tbody", {}, rows.map((r) => h("tr", {},
        h("td", { class: "nowrap" }, fmtDate(r.created_at)), h("td", {}, r.nom), h("td", {}, r.prenom), h("td", { class: "nowrap" }, r.tel), h("td", {}, r.email), h("td", {}, r.entreprise),
        h("td", { class: "num nowrap" }, r.score + " / " + r.total),
        h("td", {}, h("button", { class: "quiet small del", type: "button", "aria-label": "Supprimer la réponse de " + r.prenom + " " + r.nom, onclick: async () => {
          if (!confirm("Supprimer cette réponse ?")) return;
          await api("/api/admin/submissions/" + r.id, { method: "DELETE" }); renderQuiz(); } }, "Supprimer"))))))));
}

document.getElementById("new-btn").addEventListener("click", renderNew);
loadList().then(() => (S.quizzes.length ? openQuiz(S.quizzes[0].id) : renderNew()));
