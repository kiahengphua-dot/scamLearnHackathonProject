(function () {
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };

  function ArtifactAnalyzer(root) {
    this.root = root;
    this.mode = "text";
    this.analysisId = null;
    this.render();
  }

  ArtifactAnalyzer.prototype.render = function () {
    this.root.innerHTML = "";

    const tabs = el("div", "analyze-tabs");
    const tabDefs = [
      ["text", "Paste Text"],
      ["screenshot", "Upload Screenshot"],
      ["url", "Check a URL"],
    ];
    tabDefs.forEach(([mode, label]) => {
      const btn = el("button", "btn btn-secondary" + (this.mode === mode ? " analyze-tab-active" : ""), label);
      btn.addEventListener("click", () => {
        this.mode = mode;
        this.render();
      });
      tabs.appendChild(btn);
    });
    this.root.appendChild(tabs);

    this.formEl = el("div", "analyze-form");
    this.root.appendChild(this.formEl);

    this.resultEl = el("div", "analyze-result");
    this.root.appendChild(this.resultEl);

    if (this.mode === "text") {
      this.renderTextForm();
    } else if (this.mode === "screenshot") {
      this.renderScreenshotForm();
    } else {
      this.renderUrlForm();
    }
  };

  ArtifactAnalyzer.prototype.renderTextForm = function () {
    const textarea = el("textarea", "response-input analyze-textarea");
    textarea.placeholder = "Paste the suspicious message here (SMS, email, chat, etc.)...";
    textarea.maxLength = 4000;
    this.formEl.appendChild(textarea);

    const btn = el("button", "btn btn-primary", "Analyze");
    btn.addEventListener("click", () => {
      const text = textarea.value.trim();
      if (!text) {
        this.showError("Please paste a message to analyze.");
        return;
      }
      this.submitAnalysis({ type: "text", text: text });
    });
    this.formEl.appendChild(btn);
  };

  ArtifactAnalyzer.prototype.renderScreenshotForm = function () {
    const fileInput = el("input", "analyze-file-input");
    fileInput.type = "file";
    fileInput.accept = "image/png,image/jpeg,image/webp";
    this.formEl.appendChild(fileInput);

    const btn = el("button", "btn btn-primary", "Analyze");
    btn.addEventListener("click", () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        this.showError("Please choose an image file to analyze.");
        return;
      }
      const formData = new FormData();
      formData.append("type", "screenshot");
      formData.append("image", file);
      this.submitAnalysis(formData);
    });
    this.formEl.appendChild(btn);
  };

  ArtifactAnalyzer.prototype.renderUrlForm = function () {
    this.formEl.appendChild(el("p", "meta", "ScamLearn fetches the page safely on the server (no scripts run, no forms are submitted) and analyzes its content."));

    const input = el("input", "response-input");
    input.type = "text";
    input.placeholder = "https://example.com/suspicious-page";
    this.formEl.appendChild(input);

    const btn = el("button", "btn btn-primary", "Analyze");
    btn.addEventListener("click", () => {
      const url = input.value.trim();
      if (!url) {
        this.showError("Please enter a URL to analyze.");
        return;
      }
      this.submitAnalysis({ type: "url", url: url });
    });
    this.formEl.appendChild(btn);
  };

  ArtifactAnalyzer.prototype.showError = function (message) {
    this.resultEl.innerHTML = "";
    this.resultEl.appendChild(el("p", "error-text", message));
  };

  ArtifactAnalyzer.prototype.submitAnalysis = function (payload) {
    this.resultEl.innerHTML = "";
    this.resultEl.appendChild(el("p", "analyze-status", "Analyzing…"));

    const isFormData = payload instanceof FormData;
    fetch("/api/artifacts/analyze", {
      method: "POST",
      headers: isFormData ? undefined : { "Content-Type": "application/json" },
      body: isFormData ? payload : JSON.stringify(payload),
    })
      .then((r) => r.json().then((data) => ({ ok: r.ok, data: data })))
      .then(({ ok, data }) => {
        if (!ok) {
          this.showError(data.error || "Analysis failed. Please try again.");
          return;
        }
        this.analysisId = data.analysis_id;
        this.renderAnalysis(data);
      })
      .catch(() => this.showError("Could not reach the server. Please try again."));
  };

  ArtifactAnalyzer.prototype.renderAnalysis = function (data) {
    this.resultEl.innerHTML = "";

    const box = el("div", "outcome-box");
    const riskRow = el("div", "analyze-risk-row");
    riskRow.appendChild(el("span", "classification-tag risk-" + data.risk_assessment, data.risk_assessment.toUpperCase() + " RISK"));
    riskRow.appendChild(el("span", "meta", `Confidence: ${Math.round(data.confidence * 100)}%`));
    box.appendChild(riskRow);

    box.appendChild(el("p", null, data.summary));

    if (data.indicators.length) {
      box.appendChild(el("h3", null, "What we found"));
      const ul = el("ul");
      data.indicators.forEach((ind) => {
        ul.appendChild(el("li", null, `[${ind.severity}] ${ind.type.replace(/_/g, " ")} — ${ind.evidence}`));
      });
      box.appendChild(ul);
    }

    if (data.recommended_verification.length) {
      box.appendChild(el("h3", null, "Recommended verification"));
      const ul = el("ul");
      data.recommended_verification.forEach((v) => ul.appendChild(el("li", null, v)));
      box.appendChild(ul);
    }

    const actions = el("div", "actions-row");
    const trainBtn = el("button", "btn btn-primary", "Train Against This");
    trainBtn.addEventListener("click", () => this.generateScenario());
    actions.appendChild(trainBtn);
    box.appendChild(actions);

    this.resultEl.appendChild(box);
  };

  ArtifactAnalyzer.prototype.generateScenario = function () {
    this.resultEl.appendChild(el("p", "analyze-status", "Generating a training scenario from this…"));
    fetch(`/api/artifacts/${this.analysisId}/generate-scenario`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then((r) => r.json().then((data) => ({ ok: r.ok, data: data })))
      .then(({ ok, data }) => {
        if (!ok) {
          this.showError(data.error || "Couldn't generate a training scenario from this. Please try again.");
          return;
        }
        window.location.href = `/train?scenario=${encodeURIComponent(data.scenario_id)}`;
      })
      .catch(() => this.showError("Could not reach the server. Please try again."));
  };

  window.ArtifactAnalyzer = ArtifactAnalyzer;
})();
