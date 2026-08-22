(function () {
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };

  function ScamLearnSimulation(root, mode, options) {
    this.root = root;
    this.mode = mode;
    this.sessionId = null;
    this.presetScenarioId = options && options.scenarioId;
    this.render();
  }

  ScamLearnSimulation.prototype.render = function () {
    this.root.innerHTML = "";
    this.pickerEl = el("div", "scenario-picker");
    this.chatEl = el("div", "chat-window");
    this.chatEl.style.display = "none";
    this.root.appendChild(this.pickerEl);
    this.root.appendChild(this.chatEl);

    if (this.mode === "train" && this.presetScenarioId) {
      // Arrived here from the Analyze page with a specific (often
      // artifact-generated) scenario already chosen — skip the picker.
      this.startSession(this.presetScenarioId);
    } else if (this.mode === "train") {
      this.loadScenarioList();
    } else {
      const btn = el("button", "btn btn-primary", "Start Test");
      btn.addEventListener("click", () => this.startSession(null));
      this.pickerEl.appendChild(el("p", null, "You won't be told whether this is a scam or a legitimate situation. Investigate, then decide."));
      this.pickerEl.appendChild(btn);
    }
  };

  ScamLearnSimulation.prototype.loadScenarioList = function () {
    fetch("/api/scenarios?mode=train")
      .then((r) => r.json())
      .then((data) => {
        const list = el("div", "scenario-list");
        data.scenarios.forEach((s) => {
          const card = el("div", "scenario-card");
          card.appendChild(el("h3", null, s.title));
          card.appendChild(el("p", "meta", `${s.category} · ${s.difficulty}`));
          const goal = el("p", null, "Goal: " + s.target_learning_objectives.join("; "));
          card.appendChild(goal);
          const btn = el("button", "btn btn-primary", "Start Simulation");
          btn.addEventListener("click", () => this.startSession(s.id));
          card.appendChild(btn);
          list.appendChild(card);
        });
        this.pickerEl.appendChild(list);
      });
  };

  ScamLearnSimulation.prototype.startSession = function (scenarioId) {
    fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: this.mode, scenario_id: scenarioId }),
    })
      .then((r) => r.json().then((data) => ({ ok: r.ok, data: data })))
      .then(({ ok, data }) => {
        if (!ok) {
          this.pickerEl.appendChild(el("p", "error-text", data.error || "Couldn't start this scenario."));
          return;
        }
        this.sessionId = data.session_id;
        this.pickerEl.style.display = "none";
        this.chatEl.style.display = "block";
        this.appendBubble("scenario", data.message);
        this.renderActions();
      });
  };

  ScamLearnSimulation.prototype.appendBubble = function (speaker, text) {
    const bubble = el("div", "bubble bubble-" + speaker, text);
    this.chatEl.insertBefore(bubble, this.actionsEl || null);
  };

  ScamLearnSimulation.prototype.renderActions = function () {
    if (this.actionsEl) this.actionsEl.remove();
    this.actionsEl = el("div", "actions-panel");

    const input = el("textarea", "response-input");
    input.placeholder = "Type your response (optional for most actions)...";
    this.actionsEl.appendChild(input);

    const buttonsRow = el("div", "actions-row");
    const actions = [
      ["CONTINUE", "Continue"],
      ["ASK_QUESTION", "Ask a Question"],
      ["VERIFY", "Verify"],
      ["STOP", "Stop"],
      ["REPORT", "Report"],
    ];
    actions.forEach(([type, label]) => {
      const btn = el("button", "btn btn-secondary", label);
      btn.addEventListener("click", () => this.submitDecision(type, input.value));
      buttonsRow.appendChild(btn);
    });
    this.actionsEl.appendChild(buttonsRow);
    this.chatEl.appendChild(this.actionsEl);
  };

  ScamLearnSimulation.prototype.submitDecision = function (actionType, text) {
    this.appendBubble("user", text ? text : "[" + actionType + "]");
    fetch(`/api/sessions/${this.sessionId}/decisions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_type: actionType, text: text }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "completed") {
          this.renderOutcome(data);
        } else {
          this.appendBubble("scenario", data.message);
        }
      });
  };

  ScamLearnSimulation.prototype.renderOutcome = function (data) {
    this.actionsEl.remove();
    const box = el("div", "outcome-box");
    box.appendChild(el("h2", null, "Scenario Complete"));
    box.appendChild(el("p", "classification-tag", data.classification));
    box.appendChild(el("p", null, data.outcome_summary));
    box.appendChild(el("p", null, `Reasoning score: ${data.reasoning_score}/100`));

    if (data.newly_earned_achievements && data.newly_earned_achievements.length) {
      const ach = el("p", "achievement-earned", "New achievement unlocked! Check My Progress to see it.");
      box.appendChild(ach);
    }

    if (data.expected_red_flags.length) {
      box.appendChild(el("h3", null, "Red flags in this scenario"));
      const ul = el("ul");
      data.expected_red_flags.forEach((f) => ul.appendChild(el("li", null, f)));
      box.appendChild(ul);
    }

    if (data.safe_verification_actions.length) {
      box.appendChild(el("h3", null, "Safer alternatives"));
      const ul = el("ul");
      data.safe_verification_actions.forEach((f) => ul.appendChild(el("li", null, f)));
      box.appendChild(ul);
    }

    const replayContainer = el("div", "replay-container");
    replayContainer.appendChild(el("p", "analyze-status", "Loading Scam Replay…"));
    box.appendChild(replayContainer);

    const progressLink = el("a", "btn btn-secondary", "View My Progress");
    progressLink.href = "/profile";
    box.appendChild(progressLink);

    this.chatEl.appendChild(box);
    this.loadReplay(replayContainer);
  };

  ScamLearnSimulation.prototype.loadReplay = function (container) {
    fetch(`/api/sessions/${this.sessionId}/replay`)
      .then((r) => r.json())
      .then((data) => this.renderReplay(container, data))
      .catch(() => {
        container.innerHTML = "";
      });
  };

  ScamLearnSimulation.prototype.renderReplay = function (container, data) {
    container.innerHTML = "";
    container.appendChild(el("h3", null, "Scam Replay"));

    const timeline = el("ol", "replay-timeline");
    data.steps.forEach((step) => {
      const item = el("li", "replay-step");
      item.appendChild(el("span", "replay-stage", step.stage));
      if (step.scenario_message) {
        item.appendChild(el("p", "replay-message", step.scenario_message));
      }
      if (step.user_action) {
        item.appendChild(el("p", "replay-user-action", "You: " + step.user_action));
      }
      timeline.appendChild(item);
    });
    container.appendChild(timeline);

    if (data.intervention_point) {
      const ip = el("div", "intervention-point");
      const label = data.intervention_point.framing === "caught" ? "Where you caught it" : "Your intervention point";
      ip.appendChild(el("h4", null, label));
      ip.appendChild(el("p", null, data.intervention_point.scenario_message));
      container.appendChild(ip);
    }

    if (data.narrative) {
      container.appendChild(el("p", null, data.narrative));
    }
    if (data.lesson_to_remember) {
      container.appendChild(el("p", "lesson-to-remember", "Remember: " + data.lesson_to_remember));
    }
  };

  window.ScamLearnSimulation = ScamLearnSimulation;
})();
