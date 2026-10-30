// 연결 확인용 뼈대: broker 연결, 시작·중지 버튼, 받은 메시지 표시.
// TODO(player): YouTube IFrame 플레이어를 붙이고 zt/<기기>/playback의 action으로 playVideo()·pauseVideo()를 부른다.
// 기기는 주소 뒤 ?device=esp32-b로 바꾼다 (기본 esp32-a).

const device = new URLSearchParams(location.search).get("device") || "esp32-a";
const base = `zt/${device}`;
const $ = (id) => document.getElementById(id);
$("device").textContent = device;

const scheme = location.protocol === "https:" ? "wss" : "ws";
const client = mqtt.connect(`${scheme}://${location.host}/mqtt`);

client.on("connect", () => {
  $("broker").textContent = "연결됨";
  client.subscribe(`${base}/#`);
});
client.on("close", () => { $("broker").textContent = "끊김"; });

const log = (line) => {
  const li = document.createElement("li");
  li.textContent = `${new Date().toLocaleTimeString()}  ${line}`;
  $("log").prepend(li);
  while ($("log").children.length > 50) $("log").lastChild.remove();
};

const send = (cmd) => client.publish(`${base}/control`, JSON.stringify({ cmd }), { qos: 1 });

// 시작을 누른 뒤 중지를 누르기 전까지 true. status idle은 세 경우에 온다:
//  - 페이지를 처음 열 때(retain)       → started=false라 무시
//  - 중지를 눌렀을 때(stop에 대한 응답) → 중지 버튼에서 먼저 false로 바꾸므로 무시
//  - 감지 중 ESP32가 재부팅됐을 때      → started=true라 start를 다시 보낸다
let started = false;
const RESTART_COOLDOWN_MS = 2000; // start를 받고도 idle만 계속 오면 무한 반복하지 않도록
let lastAutoStart = 0;

function onStatus(state) {
  if (state !== "idle" || !started) return;
  const now = Date.now();
  if (now - lastAutoStart < RESTART_COOLDOWN_MS) return;
  lastAutoStart = now;
  log("ESP32가 idle로 돌아옴(재부팅) → start 다시 보냄");
  send("start");
}

client.on("message", (topic, payload) => {
  const text = payload.toString();
  if (topic === `${base}/status`) {
    let state;
    try { state = JSON.parse(text).state; } catch {} // retain을 지우는 빈 메시지 등은 버린다
    if (state) $("esp32").textContent = state;
    log(`${topic.slice(base.length + 1)}  ${text}`);
    if (state) onStatus(state);
    return;
  }
  log(`${topic.slice(base.length + 1)}  ${text}`);
});

$("start").onclick = () => { started = true; send("start"); };
$("stop").onclick = () => { started = false; send("stop"); };
