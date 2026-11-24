const packets = {
  position: {
    title: "POSITION BEACON", icon: "◆", from: "N0DEMO-9",
    fields: [["LAT", "39° 55.00′N"], ["LON", "116° 30.00′E"], ["SPEED", "62 km/h"], ["COURSE", "085°"]],
    comment: "Mobile APRS demo · headed east along the park.",
    distance: "14.2 km", bearing: "315", direction: "NW",
    route: "N0DEMO-9>APRS,N0DIGI-1*,N0DIGI-2*,N0DIGI-3*,N0DIGI-4*,N0DIGI-5*,WIDE2-1:",
  },
  weather: {
    title: "WEATHER STATION", icon: "✳", from: "N0WX-1",
    fields: [["TEMP", "12°C"], ["HUM", "48%"], ["WIND", "NW 12 km/h"], ["PRESS", "1018 hPa"]],
    distance: "8.60 km", bearing: "287", direction: "WNW",
    route: "N0WX-1>APRS,WIDE1-1:",
  },
  message: {
    title: "APRS MESSAGE", icon: "✉", from: "N0MSG-2", to: "N0HOME-3", messageId: "2",
    comment: "Hello from the APRS demo. Can you copy?",
    route: "N0MSG-2>APRS,WIDE1-1:",
  },
  status: {
    title: "APRS STATUS", icon: "●", from: "N0BASE",
    comment: "Monitoring APRS. Leave a message if you need a reply.",
    route: "N0BASE>APRS,WIDE1-1:",
  },
  igate: {
    title: "APRS IGATE", icon: "◈", from: "N0GATE-10",
    fields: [["MODE", "RX ONLY"], ["LAT", "39° 58.00′N"], ["LON", "116° 18.00′E"]],
    comment: "Local gateway serving the park and surrounding neighborhoods.",
    distance: "6.30 km", bearing: "044", direction: "NE",
    route: "N0GATE-10>APRS,N0DIGI-3*,WIDE1-1,WIDE2-1:",
  },
  relayed: {
    title: "APRS BEACON RELAYED", icon: "↗", from: "N0HOME-3",
    fields: [["VIA", "N0DIGI-3"], ["LAT", "39° 54.80′N"], ["LON", "116° 29.50′E"]],
    comment: "ICOM IC-705 APRS TEST",
    route: "N0HOME-3>APRS,N0DIGI-3*,WIDE2-1:",
  },
};

const screen = document.querySelector("#screen");
const source = document.querySelector("#position-source");
const announcement = document.querySelector("#announcement");
const receiveButtons = document.querySelectorAll(".sample-buttons button");
const pageSize = 4;
const liveLimit = 64;
const views = [{ name: "home" }];
const records = [];
const today = "2026-11-25";
let packetNumber = 0;
let seconds = 8 * 3600 + 24 * 60;
let english = false;
try {
  english = localStorage.getItem("ic705-language") === "en";
} catch {
  // The standalone page also works when browser storage is unavailable.
}
if (english) {
  document.documentElement.lang = "en";
  document.title = "APRS simulator · IC-705";
  document.querySelectorAll("[data-en]").forEach(element => {
    element.textContent = element.dataset.en;
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function makeRecord(kind, date, time, localSource) {
  const packet = packets[kind];
  return {
    ...packet, kind, date, time, localSource, number: ++packetNumber,
    distance: localSource === "NO FIX" ? null : packet.distance,
  };
}

[
  ["position", today, "08:23:50", "MANUAL"],
  ["status", today, "08:21:30", "GPS"],
  ["message", today, "08:18:10", "GPS"],
  ["weather", today, "08:15:00", "GPS"],
  ["igate", today, "08:10:23", "NO FIX"],
  ["position", "2026-11-24", "21:34:50", "GPS"],
  ["weather", "2026-11-24", "20:01:02", "GPS"],
  ["weather", "2026-11-23", "18:12:10", "GPS"],
].forEach(args => records.push(makeRecord(...args)));

function control(action, label, className = "", disabled = false) {
  return `<button type="button" data-action="${action}" class="${className}"${disabled ? " disabled" : ""}>${label}</button>`;
}

function heading(title, end = "") {
  return `<div class="view-heading"><h2>${title}</h2>${end}</div>`;
}

function list(title, rows, page, count) {
  return `<div class="view">
    ${heading(title, `<span>${page + 1}/${count}</span>`)}
    <div class="rows">${rows.join("")}</div>
    <div class="list-controls">
      <div class="action-group">
        ${control("page:newer", "Newer", "", page === 0)}
        ${control("page:older", "Older", "", page + 1 === count)}
      </div>
      ${control("exit", "Back")}
    </div>
  </div>`;
}

function paged(view, items, title, row) {
  const count = Math.max(1, Math.ceil(items.length / pageSize));
  const page = Math.max(0, Math.min(view.page, count - 1));
  view.page = page;
  return list(title, items.slice(page * pageSize, (page + 1) * pageSize).map(row), page, count);
}

function bearing(record) {
  return `<i class="bearing" data-bearing="${record.bearing}" aria-hidden="true"></i>`;
}

function stationIcon(record) {
  return `<span class="station-icon" aria-hidden="true">${record.icon}</span>`;
}

function recordRow(record) {
  const distance = record.distance
    ? `<span class="row-distance">${bearing(record)}${record.distance}</span>`
    : "";
  return control(`detail:${record.number}`, `
    <span class="row-identity">${stationIcon(record)}<span><strong>${record.from}</strong>${distance}</span></span>
    <span class="row-time"><strong>${record.time}</strong><span class="row-date">${record.date}</span></span>`, "row");
}

function compass(record) {
  const pointer = record.distance ? bearing(record) : "";
  const direction = record.distance ? `${record.bearing}° ${record.direction}` : "—";
  return `<div class="compass">
    <div class="dial" aria-hidden="true">
      <span class="cardinal north">N</span><span class="cardinal east">E</span>
      <span class="cardinal south">S</span><span class="cardinal west">W</span>${pointer}
    </div>
    <strong>${record.distance || "— km"}</strong><span>${direction}</span>
  </div>`;
}

function detail(record) {
  const gps = record.bearing
    ? `<span class="gps-state" data-source="${record.localSource}">${record.localSource}</span>`
    : "";
  const fields = (record.fields || []).map(([name, value]) =>
    `<div class="field"><span>${name}</span><strong>${value}</strong></div>`).join("");
  const address = record.to
    ? `<div class="field"><span>TO</span>${record.to}<strong class="message-id">ID ${record.messageId}</strong></div>`
    : "";
  const comment = record.comment
    ? `<p class="comment">${record.fields ? "<span>COMMENT</span>" : ""}${escapeHtml(record.comment)}</p>`
    : "";
  return `<div class="view popup" data-kind="${record.kind}">
    ${heading(record.title, gps)}
    <div class="popup-main${gps ? " has-compass" : ""}">
      ${gps ? compass(record) : ""}
      <div>
        <div class="from">${stationIcon(record)}<strong>${record.from}</strong></div>
        ${fields}${address}${comment}
      </div>
    </div>
    <div class="packet-footer">
      <div class="packet-path">${escapeHtml(record.route)}</div>
      <div class="action-group">
        ${record.to ? control("reply", "Reply", "primary") : ""}
        ${control("exit", "Back")}
      </div>
    </div>
  </div>`;
}

function draw() {
  const view = views.at(-1);
  switch (view.name) {
    case "home":
      return '<div class="standby"><strong>APRS FM STANDBY</strong><span>Waiting for packets</span></div>';
    case "quick":
      return `<div class="view">${heading("QUICK")}
        <div class="rows">
          ${control("open:live", "APRS RX List", "row")}
          ${control("open:archive", "APRS Archive", "row")}
          ${control("open:beacon", "Send APRS Beacon", "row")}
        </div>
        <div class="list-controls">${control("exit", "Back")}</div>
      </div>`;
    case "live":
      return paged(view, view.snapshot || records.slice(0, liveLimit), "APRS RX List", recordRow);
    case "archive": {
      const dates = [...new Set(records.map(record => record.date))];
      return paged(view, dates, "APRS Archive", date => control(`date:${date}`, date, "row"));
    }
    case "day":
      return paged(view, records.filter(record => record.date === view.date), view.date, recordRow);
    case "detail":
      return detail(view.record);
    case "reply":
      return `<div class="view">${heading("APRS Reply", `<span>${view.record.from}</span>`)}
        <div class="reply-body">
          <label for="reply-text" class="reply-label">Message · up to 67 ASCII characters</label>
          <textarea id="reply-text" maxlength="67" rows="2" spellcheck="false" data-action="edit">${escapeHtml(view.text)}</textarea>
        </div>
        <div class="list-controls">${control("exit", "Back")}${control("confirm", "ENT", "primary", !view.text.trim())}</div>
      </div>`;
    case "confirm":
      return `<div class="view">${heading("Send APRS Message")}
        <div class="reply-body"><p>TO ${view.record.from}</p><p>${escapeHtml(view.text)}</p></div>
        <div class="list-controls">${control("exit", "Back")}${control("send", "Send", "primary")}</div>
      </div>`;
    case "beacon":
      return `<div class="view">${heading("APRS Beacon")}
        <div class="reply-body"><p>${source.value === "NO FIX" ? "No local position" : "Beacon sent (simulation)"}</p></div>
        <div class="list-controls">${control("exit", "Back")}</div>
      </div>`;
    case "sent":
      return `<div class="view">${heading("APRS Message")}
        <div class="reply-body"><p>Message sent (simulation)</p></div>
        <div class="list-controls">${control("exit", "Back")}</div>
      </div>`;
  }
}

function render({ focus = false, action } = {}) {
  screen.innerHTML = draw();
  const view = views.at(-1);
  for (const button of receiveButtons) {
    const active = view.name === "detail" && button.dataset.action === `receive:${view.record.kind}`;
    button.setAttribute("aria-pressed", String(active));
  }
  if (focus) {
    const target = screen.querySelector(`[data-action="${action ?? ""}"]:not(:disabled)`);
    (target || screen).focus({ preventScroll: true });
  }
}

function open(view, via) {
  views.push({ ...view, via });
  render({ focus: true, action: view.name === "reply" ? "edit" : undefined });
}

function exit() {
  const closed = views.length > 1 ? views.pop() : null;
  if (!closed) return;
  render({ focus: true, action: closed.via });
  if (views.length === 1) {
    const target = [...document.querySelectorAll("[data-action]")].find(el => el.dataset.action === closed.via);
    (target || document.querySelector('.panel-keys [data-action="quick"]')).focus({ preventScroll: true });
  }
}

function receive(kind) {
  seconds += 7;
  const time = new Date(seconds * 1000).toISOString().slice(11, 19);
  const record = makeRecord(kind, today, time, source.value);
  records.unshift(record);
  announcement.textContent = english
    ? `Received ${record.title} from ${record.from} at ${time}`
    : `${time} 收到 ${record.from} 的 ${record.title}`;
  const view = views.at(-1);
  if (view.name === "home") {
    open({ name: "detail", record, incoming: true }, `receive:${kind}`);
  } else if (view.incoming) {
    views.pop();
    open({ name: "detail", record, incoming: true }, `receive:${kind}`);
  } else if (view.name === "live" && view.page === 0) {
    render();
  }
}

document.addEventListener("click", event => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  const [name, argument] = action.split(":");
  const view = views.at(-1);
  switch (name) {
    case "receive":
      receive(argument);
      break;
    case "quick":
      if (view.name === "quick") exit();
      else if (view.name === "home") open({ name: "quick" }, action);
      break;
    case "exit":
      exit();
      break;
    case "open":
      // The radio closes QUICK when its selected list opens.
      views.pop();
      open({ name: argument, page: 0 }, "quick");
      break;
    case "date":
      open({ name: "day", date: argument, page: 0 }, action);
      break;
    case "detail":
      open({ name: "detail", record: records.find(record => record.number === Number(argument)) }, action);
      break;
    case "page":
      view.page += argument === "older" ? 1 : -1;
      if (view.name === "live") {
        if (view.page === 0) view.snapshot = null;
        else view.snapshot ||= records.slice(0, liveLimit);
      }
      render({ focus: true, action });
      break;
    case "reply":
      open({ name: "reply", record: view.record, text: "" }, action);
      break;
    case "confirm":
      if (view.text.trim()) open({ name: "confirm", record: view.record, text: view.text.trim() }, "confirm");
      break;
    case "send":
      views.splice(-2, 2);
      open({ name: "sent" }, "reply");
      break;
  }
});

screen.addEventListener("input", event => {
  if (event.target.id !== "reply-text") return;
  const view = views.at(-1);
  view.text = event.target.value.replace(/[^\x20-\x7e]/g, "");
  if (event.target.value !== view.text) event.target.value = view.text;
  screen.querySelector('[data-action="confirm"]').disabled = !view.text.trim();
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape" && views.length > 1) {
    event.preventDefault();
    exit();
  }
});

render();
