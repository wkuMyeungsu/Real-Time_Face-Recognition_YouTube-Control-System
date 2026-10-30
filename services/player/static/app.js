// player: 유튜브 플레이어 + MQTT.
// - 기기는 주소 뒤 ?device=esp32-b로 바꾼다 (기본 esp32-a). 영상은 ?v=<영상 ID 또는 URL>로도 고를 수 있다.
// - zt/<기기>/playback의 action으로 playVideo()·pauseVideo()를 부른다.
// - 로그는 화면 목록과 zt/<기기>/log/player(QoS 0, 로거 zt.player.*)에 같이 남긴다 (docs/logging-design.txt 7-4).

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);

// ── 기기 ─────────────────────────────────────────
// 토픽에 그대로 들어가므로 + # / 같은 문자는 받지 않는다 (와일드카드 구독이 되어 버림).
const DEVICE_RE = /^[a-z0-9-]+$/;
const askedDevice = params.get("device");
const device = askedDevice && DEVICE_RE.test(askedDevice) ? askedDevice : "esp32-a";
const base = `zt/${device}`;
$("device").textContent = device;

// ── MQTT ─────────────────────────────────────────
const scheme = location.protocol === "https:" ? "wss" : "ws";
const client = mqtt.connect(`${scheme}://${location.host}/mqtt`, { reconnectPeriod: 2000 });

// ── 로그 ─────────────────────────────────────────
const clock = () => {
  const d = new Date();
  const p = (n, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
};

function show(line, level) {
  const li = document.createElement("li");
  li.textContent = `${clock()}  ${line}`;
  if (level && level !== "INFO") li.className = level.toLowerCase();
  $("log").prepend(li);
  while ($("log").children.length > 50) $("log").lastChild.remove();
}

// level: INFO | WARNING | ERROR, module: mqtt | youtube, fn: 로그를 찍은 함수 이름
function report(level, module, fn, msg, fields) {
  const kv = fields ? Object.entries(fields).map(([k, v]) => ` ${k}=${v}`).join("") : "";
  show(`[${module}] ${msg}${kv}`, level);
  if (!client.connected) return; // 끊긴 동안의 로그는 화면에만 (쌓아 두었다 늦게 보내지 않는다)
  const body = { level, logger: `zt.player.${module}`, where: `app.js:${fn}`, msg, ts_ms: Date.now() };
  if (fields && Object.keys(fields).length) body.fields = fields;
  client.publish(`${base}/log/player`, JSON.stringify(body), { qos: 0 });
}

// ── broker 연결 표시 ──────────────────────────────
let everConnected = false;
let online = false;
let downSince = 0;

function setBroker(text) {
  $("broker").textContent = text;
  // 끊긴 동안 누른 버튼이 쌓였다가 재연결 때 늦게 나가지 않게 막는다.
  $("start").disabled = $("stop").disabled = !online;
}

client.on("connect", () => {
  online = true;
  setBroker("연결됨");
  client.subscribe(`${base}/#`);
  if (everConnected) report("WARNING", "mqtt", "onConnect", "재연결", { down_ms: Date.now() - downSince });
  everConnected = true;
});
client.on("reconnect", () => setBroker("재연결 중"));
client.on("close", () => {
  if (online) {
    downSince = Date.now();
    show("[mqtt] broker 연결 끊김", "WARNING");
  }
  online = false;
  setBroker(everConnected ? "끊김" : "연결 중");
});
setBroker("연결 중");
if (askedDevice && askedDevice !== device) show(`[mqtt] 기기 이름이 올바르지 않아 ${device}로 엽니다: ${askedDevice}`, "WARNING");

function send(cmd, by) {
  if (!client.connected) return false;
  client.publish(`${base}/control`, JSON.stringify({ cmd }), { qos: 1 });
  report("INFO", "mqtt", "send", "control 보냄", { cmd, by });
  return true;
}

// ── 시작 상태와 ESP32 재부팅 처리 ─────────────────
// 시작을 누른 뒤 중지를 누르기 전까지 started=true. status idle은 세 경우에 온다:
//  - 페이지를 처음 열 때(retain)       → started=false라 무시
//  - 중지를 눌렀을 때(stop에 대한 응답) → 중지 버튼에서 먼저 false로 바꾸므로 무시
//  - 감지 중 ESP32가 재부팅됐을 때      → started=true라 start를 다시 보낸다
// 페이지를 열 때(또는 broker 재연결 때) broker가 건네준 retain status가 running이면
// 이미 감지 중인 것으로 보고 started=true로 이어받는다. 감지 중에 새로고침해도 재부팅 재시작이 계속 동작한다.
// 실시간으로 온 running은 이어받지 않는다: 시작 → 바로 중지 때 늦게 도착한 running 응답으로 다시 켜지면 안 되므로.
let started = false;
let esp32 = null;                 // 마지막으로 받은 status.state
const RESTART_COOLDOWN_MS = 2000; // start를 다시 보내는 최소 간격
const RESTART_MAX = 5;            // running을 못 보고 연달아 보낸 횟수가 이만큼이면 멈춘다
let lastAutoStart = -Infinity;
let autoStarts = 0;
let retryTimer = null;

function refreshEsp32() {
  $("esp32").textContent = esp32 || "-";
  // 감지 중인데 보드가 꺼져 있으면 눈에 띄게.
  $("esp32").classList.toggle("warn", started && esp32 === "offline");
}

function setStarted(on) {
  started = on;
  autoStarts = 0;
  clearTimeout(retryTimer);
  retryTimer = null;
  $("mode").textContent = on ? "감지 중" : "중지됨";
  refreshEsp32();
}

function maybeRestart() {
  if (!started || esp32 !== "idle" || autoStarts >= RESTART_MAX) return;
  const wait = lastAutoStart + RESTART_COOLDOWN_MS - Date.now();
  if (wait > 0) {
    // 쿨다운 중에 온 idle도 버리지 않는다. 끝날 때 아직 idle이면 그때 보낸다.
    if (!retryTimer) retryTimer = setTimeout(() => { retryTimer = null; maybeRestart(); }, wait);
    return;
  }
  if (!client.connected) return; // 재연결되면 retain status가 다시 와서 여기로 온다
  lastAutoStart = Date.now();
  autoStarts += 1;
  report("INFO", "mqtt", "maybeRestart", "ESP32가 idle로 돌아옴(재부팅) → start 다시 보냄", { try: autoStarts });
  send("start", "auto");
  if (autoStarts >= RESTART_MAX) {
    report("ERROR", "mqtt", "maybeRestart", "start를 다시 보내도 running이 되지 않아 자동 재시작을 멈춤. 보드를 확인하고 시작을 다시 누르세요", { tries: autoStarts });
  }
}

function onStatus(text, retained) {
  let state;
  try { state = JSON.parse(text).state; } catch {} // retain을 지우는 빈 메시지 등은 버린다
  if (!["running", "idle", "offline"].includes(state)) return;
  esp32 = state;
  if (state === "running") autoStarts = 0;
  if (retained && state === "running" && !started) {
    setStarted(true);
    report("INFO", "mqtt", "onStatus", "ESP32가 이미 감지 중 → 시작 상태로 이어받음");
  }
  refreshEsp32();
  maybeRestart();
}

$("start").onclick = () => { setStarted(true); send("start", "button"); };
$("stop").onclick = () => { setStarted(false); send("stop", "button"); };

// ── 유튜브 ───────────────────────────────────────
const STATE_NAMES = { "-1": "UNSTARTED", 0: "ENDED", 1: "PLAYING", 2: "PAUSED", 3: "BUFFERING", 5: "CUED" };
let yt = null;
let ytReady = false;
let pendingAction = null; // 플레이어가 준비되기 전에 온 playback
let lastPlaybackAt = 0;   // 판정 → 재생 지연(since_playback_ms)을 재려고

// 영상 ID 또는 유튜브 주소(watch?v=, youtu.be/, shorts/, embed/, live/)에서 ID를 꺼낸다.
function videoIdOf(input) {
  const s = (input || "").trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(s)) return s;
  const m = s.match(/(?:[?&]v=|youtu\.be\/|\/(?:shorts|embed|live)\/)([A-Za-z0-9_-]{11})/);
  return m ? m[1] : null;
}

function loadVideo(input) {
  const id = videoIdOf(input);
  if (!id) {
    show(`[youtube] 영상 주소를 알아볼 수 없음: ${input}`, "WARNING");
    return;
  }
  $("video").value = id;
  try { localStorage.setItem("zt.player.video", id); } catch {}
  report("INFO", "youtube", "loadVideo", "영상 선택", { video_id: id });
  if (ytReady) yt.cueVideoById(id); // 재생은 판정(playback)이 정한다
}

function applyPlayback(action) {
  if (!ytReady) { pendingAction = action; return; }
  if (action === "play") yt.playVideo(); else yt.pauseVideo();
  report("INFO", "youtube", "applyPlayback", action === "play" ? "playVideo 호출" : "pauseVideo 호출");
}

function onPlayback(text) {
  let msg;
  try { msg = JSON.parse(text); } catch {}
  const action = msg && msg.action;
  if (action !== "play" && action !== "pause") {
    report("WARNING", "mqtt", "onPlayback", "형식이 틀린 playback 버림", { body: text.slice(0, 80) });
    return;
  }
  lastPlaybackAt = Date.now();
  const fields = { action };
  if (Number.isInteger(msg.seq)) fields.seq = msg.seq; // 계약에 seq가 생기면 같이 남긴다
  report("INFO", "mqtt", "onPlayback", "playback 받음", fields);
  applyPlayback(action);
}

window.onYouTubeIframeAPIReady = () => {
  let first = videoIdOf(params.get("v") || "");
  if (!first) { try { first = localStorage.getItem("zt.player.video"); } catch {} }
  if (first) $("video").value = first;
  yt = new YT.Player("player", {
    videoId: first || undefined,
    playerVars: { playsinline: 1, rel: 0 },
    events: {
      onReady: () => {
        ytReady = true;
        report("INFO", "youtube", "onReady", "플레이어 준비", first ? { video_id: first } : undefined);
        if (pendingAction) { const a = pendingAction; pendingAction = null; applyPlayback(a); }
      },
      onStateChange: (e) => {
        const fields = { state: STATE_NAMES[e.data] || String(e.data) };
        if (lastPlaybackAt && (e.data === 1 || e.data === 2)) {
          fields.since_playback_ms = Date.now() - lastPlaybackAt;
          lastPlaybackAt = 0;
        }
        report("INFO", "youtube", "onStateChange", "유튜브 상태 변화", fields);
      },
      onError: (e) => report("ERROR", "youtube", "onError", "유튜브 오류", { code: e.data }),
    },
  });
};
const ytScript = document.createElement("script");
ytScript.src = "https://www.youtube.com/iframe_api";
document.head.append(ytScript);

$("load").onclick = () => loadVideo($("video").value);
$("video").onkeydown = (e) => { if (e.key === "Enter") loadVideo($("video").value); };

// ── 받은 메시지 ───────────────────────────────────
client.on("message", (topic, payload, packet) => {
  const kind = topic.slice(base.length + 1);
  const text = payload.toString();
  if (kind === "log/player") return; // 내가 보낸 로그는 report()가 이미 화면에 찍었다
  show(`${kind}  ${text}`);
  if (kind === "status") onStatus(text, Boolean(packet && packet.retain)); // retain: broker가 보관해 둔 마지막 상태
  else if (kind === "playback") onPlayback(text);
});

setStarted(false);
