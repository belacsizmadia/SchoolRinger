const state = {
  schedules: [],
  tracks: [],
  weekdays: [],
};

const elements = {
  list: document.querySelector("#schedule-list"),
  empty: document.querySelector("#empty-state"),
  summary: document.querySelector("#schedule-summary"),
  group: document.querySelector("#group-name"),
  timezone: document.querySelector("#timezone"),
  activity: document.querySelector("#activity-list"),
  activityEmpty: document.querySelector("#activity-empty"),
  dialog: document.querySelector("#schedule-dialog"),
  form: document.querySelector("#schedule-form"),
  formError: document.querySelector("#form-error"),
  id: document.querySelector("#schedule-id"),
  time: document.querySelector("#schedule-time"),
  track: document.querySelector("#schedule-track"),
  enabled: document.querySelector("#schedule-enabled"),
  dayPicker: document.querySelector("#weekday-picker"),
  dialogTitle: document.querySelector("#dialog-title"),
  toast: document.querySelector("#toast"),
};

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ error: "Sikertelen kérés." }));
    throw new Error(data.error || "Sikertelen kérés.");
  }
  return response.status === 204 ? null : response.json();
}

function formatNextRun(value) {
  if (!value) return "Nincs ütemezve";
  const date = new Date(value);
  return new Intl.DateTimeFormat("hu-HU", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function createCell(className, text) {
  const cell = document.createElement("td");
  cell.className = className;
  if (text !== undefined) cell.textContent = text;
  return cell;
}

function renderSchedules() {
  elements.list.replaceChildren();
  elements.empty.hidden = state.schedules.length > 0;
  const activeCount = state.schedules.filter((item) => item.enabled).length;
  elements.summary.textContent = `${state.schedules.length} időzítés, ${activeCount} aktív`;

  for (const schedule of state.schedules) {
    const row = document.createElement("tr");
    if (!schedule.enabled) row.classList.add("is-disabled");

    row.append(createCell("time-cell", schedule.time));

    const daysCell = createCell("day-list");
    for (const weekday of state.weekdays) {
      const chip = document.createElement("span");
      chip.className = `day-chip${schedule.weekdays.includes(weekday.value) ? " on" : ""}`;
      chip.textContent = weekday.short;
      chip.title = weekday.label;
      daysCell.append(chip);
    }
    row.append(daysCell);

    const trackCell = createCell("track-name", schedule.track);
    trackCell.title = schedule.track;
    row.append(trackCell);
    row.append(createCell("next-run", schedule.enabled ? formatNextRun(schedule.next_run) : "Kikapcsolva"));

    const toggleCell = createCell("");
    const toggleLabel = document.createElement("label");
    toggleLabel.className = "switch";
    toggleLabel.title = schedule.enabled ? "Kikapcsolás" : "Bekapcsolás";
    const toggleInput = document.createElement("input");
    toggleInput.type = "checkbox";
    toggleInput.checked = schedule.enabled;
    toggleInput.setAttribute("aria-label", toggleLabel.title);
    toggleInput.addEventListener("change", () => toggleSchedule(schedule, toggleInput.checked));
    toggleLabel.append(toggleInput, document.createElement("span"));
    toggleCell.append(toggleLabel);
    row.append(toggleCell);

    const actions = createCell("row-actions");
    actions.append(
      actionButton("Próba", () => testSchedule(schedule.id)),
      actionButton("Szerkesztés", () => openDialog(schedule)),
      actionButton("Törlés", () => deleteSchedule(schedule), "danger"),
    );
    row.append(actions);
    elements.list.append(row);
  }
}

function actionButton(label, handler, style = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `action-button ${style}`.trim();
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

function renderActivity(items) {
  elements.activity.replaceChildren();
  elements.activityEmpty.hidden = items.length > 0;
  for (const item of items) {
    const entry = document.createElement("li");
    entry.className = item.status;
    const message = document.createElement("p");
    message.textContent = item.message;
    const time = document.createElement("time");
    time.dateTime = item.time;
    time.textContent = new Intl.DateTimeFormat("hu-HU", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(new Date(item.time));
    entry.append(message, time);
    elements.activity.append(entry);
  }
}

function renderFormOptions() {
  elements.track.replaceChildren();
  if (!state.tracks.length) {
    const option = new Option("Nincs MP3 a media mappában", "");
    option.disabled = true;
    option.selected = true;
    elements.track.add(option);
  } else {
    for (const track of state.tracks) elements.track.add(new Option(track, track));
  }

  elements.dayPicker.replaceChildren();
  for (const weekday of state.weekdays) {
    const label = document.createElement("label");
    label.className = "weekday-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "weekday";
    input.value = weekday.value;
    const caption = document.createElement("span");
    caption.textContent = weekday.short;
    caption.title = weekday.label;
    label.append(input, caption);
    elements.dayPicker.append(label);
  }
}

async function loadState() {
  try {
    const data = await api("/api/state");
    Object.assign(state, data);
    elements.group.textContent = data.group;
    elements.timezone.textContent = data.timezone;
    renderFormOptions();
    renderSchedules();
    renderActivity(data.activity);
  } catch (error) {
    showToast(error.message);
  }
}

function openDialog(schedule = null) {
  elements.form.reset();
  elements.formError.hidden = true;
  elements.id.value = schedule?.id || "";
  elements.dialogTitle.textContent = schedule ? "Időzítés szerkesztése" : "Új időzítés";
  elements.time.value = schedule?.time || "08:00";
  elements.track.value = schedule?.track || state.tracks[0] || "";
  elements.enabled.checked = schedule?.enabled ?? true;
  const selectedDays = schedule?.weekdays || [0, 1, 2, 3, 4];
  for (const input of elements.dayPicker.querySelectorAll("input")) {
    input.checked = selectedDays.includes(Number(input.value));
  }
  elements.dialog.showModal();
}

function closeDialog() {
  elements.dialog.close();
}

async function saveSchedule(event) {
  event.preventDefault();
  const id = elements.id.value;
  const payload = {
    time: elements.time.value,
    track: elements.track.value,
    enabled: elements.enabled.checked,
    weekdays: [...elements.dayPicker.querySelectorAll("input:checked")].map((item) => Number(item.value)),
  };
  try {
    await api(id ? `/api/schedules/${id}` : "/api/schedules", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    closeDialog();
    showToast(id ? "Az időzítés frissült." : "Az időzítés létrejött.");
    await loadState();
  } catch (error) {
    elements.formError.textContent = error.message;
    elements.formError.hidden = false;
  }
}

async function toggleSchedule(schedule, enabled) {
  try {
    await api(`/api/schedules/${schedule.id}`, {
      method: "PUT",
      body: JSON.stringify({ ...schedule, enabled }),
    });
    await loadState();
  } catch (error) {
    showToast(error.message);
    await loadState();
  }
}

async function deleteSchedule(schedule) {
  if (!window.confirm(`Törlöd ezt az időzítést?\n${schedule.time} · ${schedule.track}`)) return;
  try {
    await api(`/api/schedules/${schedule.id}`, { method: "DELETE" });
    showToast("Az időzítés törölve.");
    await loadState();
  } catch (error) {
    showToast(error.message);
  }
}

async function testSchedule(id) {
  try {
    const data = await api(`/api/schedules/${id}/play`, { method: "POST" });
    showToast(data.message);
    window.setTimeout(loadState, 700);
  } catch (error) {
    showToast(error.message);
  }
}

let toastTimer;
function showToast(message) {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  toastTimer = window.setTimeout(() => { elements.toast.hidden = true; }, 3500);
}

document.querySelector("#new-schedule").addEventListener("click", () => openDialog());
document.querySelector("#empty-create").addEventListener("click", () => openDialog());
document.querySelector("#close-dialog").addEventListener("click", closeDialog);
document.querySelector("#cancel-dialog").addEventListener("click", closeDialog);
document.querySelector("#refresh").addEventListener("click", loadState);
elements.form.addEventListener("submit", saveSchedule);
elements.dialog.addEventListener("click", (event) => {
  if (event.target === elements.dialog) closeDialog();
});

loadState();
window.setInterval(loadState, 15000);
