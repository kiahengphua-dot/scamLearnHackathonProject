(function () {
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };

  const formatCategory = (c) => c.replace(/_/g, " ");

  function ProfileView(root) {
    this.root = root;
    this.load();
  }

  ProfileView.prototype.load = function () {
    fetch("/api/profile")
      .then((r) => r.json())
      .then((data) => this.render(data))
      .catch(() => {
        this.root.innerHTML = "";
        this.root.appendChild(el("p", "error-text", "Could not load your profile right now."));
      });
  };

  ProfileView.prototype.render = function (data) {
    this.root.innerHTML = "";

    if (data.overall_proficiency === null) {
      this.root.appendChild(
        el("p", null, "Complete a scenario in Train or Test mode to start building your profile.")
      );
      return;
    }

    const summary = el("div", "profile-summary");
    const overall = el("div", "profile-overall");
    overall.appendChild(el("span", "profile-overall-number", `${data.overall_proficiency}%`));
    overall.appendChild(el("span", "profile-overall-label", "Overall Scam Resistance"));
    summary.appendChild(overall);

    if (data.strongest_category) {
      const strengths = el("div", "profile-fact");
      strengths.appendChild(el("strong", null, "Strongest skill: "));
      strengths.appendChild(el("span", null, formatCategory(data.strongest_category)));
      summary.appendChild(strengths);
    }
    if (data.weakest_category) {
      const weakness = el("div", "profile-fact");
      weakness.appendChild(el("strong", null, "Area to improve: "));
      weakness.appendChild(el("span", null, formatCategory(data.weakest_category)));
      summary.appendChild(weakness);
    }
    this.root.appendChild(summary);

    if (Object.keys(data.skill_profile).length) {
      const skillsBox = el("div", "profile-skills");
      skillsBox.appendChild(el("h2", null, "Skill Breakdown"));
      Object.entries(data.skill_profile)
        .sort((a, b) => a[1] - b[1])
        .forEach(([category, value]) => {
          const row = el("div", "skill-row");
          row.appendChild(el("span", "skill-name", formatCategory(category)));
          const barTrack = el("div", "skill-bar-track");
          const bar = el("div", "skill-bar-fill");
          bar.style.width = `${value}%`;
          barTrack.appendChild(bar);
          row.appendChild(barTrack);
          row.appendChild(el("span", "skill-value", `${value}%`));
          skillsBox.appendChild(row);
        });
      this.root.appendChild(skillsBox);
    }

    if (data.recommended) {
      const rec = el("div", "profile-recommendation");
      rec.appendChild(el("h2", null, "Recommended Next Lesson"));
      rec.appendChild(el("h3", null, data.recommended.title));
      rec.appendChild(el("p", null, data.recommended.reason));
      const btn = el("a", "btn btn-primary", "Start This Scenario");
      btn.href = `/train?scenario=${encodeURIComponent(data.recommended.scenario_id)}`;
      rec.appendChild(btn);
      this.root.appendChild(rec);
    }

    if (data.achievements && data.achievements.length) {
      const achBox = el("div", "profile-achievements");
      achBox.appendChild(el("h2", null, "Achievements"));
      const list = el("div", "achievements-list");
      data.achievements.forEach((a) => {
        const badge = el("div", "achievement-badge");
        badge.appendChild(el("h3", null, a.title));
        badge.appendChild(el("p", null, a.description));
        list.appendChild(badge);
      });
      achBox.appendChild(list);
      this.root.appendChild(achBox);
    }
  };

  window.ProfileView = ProfileView;
})();
