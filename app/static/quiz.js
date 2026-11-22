const slug = location.pathname.split("/").filter(Boolean).pop();
const app = document.getElementById("app");
const state = { quiz: null, person: null, answers: [] };

function brand() {
  return h("div", { class: "brand" }, h("span", { class: "bubble" }), "Questionnaire vidéo");
}

function show(...nodes) {
  app.replaceChildren(brand(), ...nodes);
  window.scrollTo({ top: 0 });
}

function field(label, name, type = "text", extra = {}) {
  return h("label", { class: "line" }, h("span", {}, label),
    h("input", { type, name, required: true, autocomplete: extra.autocomplete, maxlength: extra.maxlength || 150, ...extra }));
}

function renderForm() {
  const err = h("p", { class: "notice error hidden", role: "alert" });
  const form = h("form", { class: "stack", novalidate: false },
    h("div", { class: "grid-2" },
      field("Nom", "nom", "text", { autocomplete: "family-name" }),
      field("Prénom", "prenom", "text", { autocomplete: "given-name" })),
    h("div", { class: "grid-2" },
      field("Téléphone", "tel", "tel", { autocomplete: "tel", minlength: 6, maxlength: 30 }),
      field("E-mail", "email", "email", { autocomplete: "email", maxlength: 200 })),
    field("Entreprise", "entreprise", "text", { autocomplete: "organization" }),
    h("label", { class: "check" },
      h("input", { type: "checkbox", name: "consent", required: true }),
      h("span", {}, "J'accepte que ces informations soient transmises à l'organisateur de ce questionnaire pour suivre mes résultats. Je peux demander leur suppression à tout moment.")),
    err,
    h("div", {}, h("button", { class: "primary large", type: "submit" }, "Commencer")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!form.reportValidity()) return;
    const f = new FormData(form);
    state.person = {
      nom: f.get("nom").trim(), prenom: f.get("prenom").trim(), tel: f.get("tel").trim(),
      email: f.get("email").trim(), entreprise: f.get("entreprise").trim(), consent: true,
    };
    state.answers = state.quiz.questions.map(() => null);
    renderQuiz();
  });
  const n = state.quiz.questions.length;
  show(
    h("div", { class: "intro" },
      h("h1", {}, state.quiz.title || "Questionnaire"),
      h("p", { class: "meta" }, n + " questions · une seule réponse par question" + (state.quiz.video_id || state.quiz.video_url ? " · vidéo à regarder avant" : ""))),
    h("div", { class: "card sheet-form" }, form));
}

function videoBlock() {
  const q = state.quiz;
  if (q.video_id) {
    return h("div", { class: "video" }, h("iframe", {
      src: "https://www.youtube-nocookie.com/embed/" + encodeURIComponent(q.video_id),
      title: q.title || "Vidéo", allow: "accelerometer; encrypted-media; picture-in-picture", allowfullscreen: true,
      referrerpolicy: "strict-origin-when-cross-origin",
    }));
  }
  if (q.video_url) {
    return h("p", {}, h("a", { href: q.video_url, target: "_blank", rel: "noopener noreferrer" }, "Ouvrir la vidéo"));
  }
  return null;
}

function renderQuiz() {
  const total = state.quiz.questions.length;
  const progress = h("div", { class: "progress", "aria-hidden": "true" },
    state.quiz.questions.map(() => h("span", { class: "bubble" })));
  const count = h("span", { class: "small muted mono" });
  const send = h("button", { class: "primary", type: "button" }, "Envoyer mes réponses");
  const err = h("p", { class: "notice error hidden", role: "alert" });

  function refresh() {
    const done = state.answers.filter((a) => a !== null).length;
    [...progress.children].forEach((b, i) => b.classList.toggle("done", state.answers[i] !== null));
    count.textContent = done + " / " + total;
    send.disabled = done < total;
  }

  const sheet = h("div", { class: "sheet" }, state.quiz.questions.map((q, qi) => {
    const group = h("div", { class: "options", role: "radiogroup", "aria-labelledby": "q" + qi }, q.options.map((opt, oi) => {
      const btn = h("button", { class: "option", type: "button", role: "radio", "aria-checked": "false" },
        h("span", { class: "bubble" }, LETTERS[oi]), h("span", {}, opt));
      btn.addEventListener("click", () => {
        state.answers[qi] = oi;
        [...group.children].forEach((c, i) => c.setAttribute("aria-checked", String(i === oi)));
        refresh();
      });
      return btn;
    }));
    return h("section", { class: "question" },
      h("p", { class: "num" }, String(qi + 1).padStart(2, "0") + " / " + String(total).padStart(2, "0")),
      h("h3", { id: "q" + qi }, q.question), group);
  }));

  send.addEventListener("click", async () => {
    send.disabled = true;
    err.classList.add("hidden");
    try {
      const res = await api("/api/q/" + encodeURIComponent(slug) + "/submit", {
        method: "POST", body: { participant: state.person, answers: state.answers },
      });
      renderResult(res);
    } catch (e) {
      err.textContent = e.message;
      err.classList.remove("hidden");
      send.disabled = false;
    }
  });

  show(
    h("div", { class: "intro" }, h("h1", {}, state.quiz.title || "Questionnaire")),
    videoBlock(), sheet, err,
    h("div", { class: "sticky-bar" }, h("div", { class: "inner" }, progress, count, h("span", { class: "spacer" }), send)));
  refresh();
}

function renderResult(res) {
  if (!res.review) {
    show(h("div", { class: "card thanks" },
      h("h1", {}, "Merci " + state.person.prenom),
      h("p", {}, "Vos réponses ont bien été envoyées.")));
    return;
  }
  const ratio = res.score / res.total;
  const line = ratio === 1 ? "Aucune erreur" : ratio >= 0.7 ? "Bien compris" : ratio >= 0.5 ? "À revoir sur quelques points" : "Revoyez la vidéo";
  const misses = res.total - res.score;
  const review = state.quiz.questions.map((q, qi) => {
    const r = res.review[qi];
    const opts = q.options.map((opt, oi) => {
      const cls = oi === r.correct ? "is-correct" : oi === r.chosen ? "is-wrong" : "";
      return h("div", { class: "option " + cls }, h("span", { class: "bubble" }, LETTERS[oi]), h("span", {}, opt));
    });
    return h("section", { class: "question" },
      h("p", { class: "num" }, String(qi + 1).padStart(2, "0") + " / " + String(res.total).padStart(2, "0")),
      h("h3", {}, q.question), h("div", { class: "options" }, opts),
      r.explanation ? h("p", { class: "explain" }, r.explanation) : null);
  });
  show(
    h("div", { class: "card copy" },
      h("div", { class: "stamp", "aria-label": res.score + " sur " + res.total }, String(res.score), h("small", {}, "/" + res.total)),
      h("div", {},
        h("h2", {}, line),
        h("p", {}, misses ? misses + " erreur" + (misses > 1 ? "s" : "") + ", la correction est juste en dessous" : "Toutes vos réponses sont justes"))),
    h("div", { class: "sheet" }, review));
}

(async function init() {
  try {
    state.quiz = await api("/api/q/" + encodeURIComponent(slug));
    renderForm();
  } catch (e) {
    show(h("div", { class: "card" }, h("h2", {}, "Questionnaire indisponible"), h("p", { class: "muted" }, e.message)));
  }
})();
