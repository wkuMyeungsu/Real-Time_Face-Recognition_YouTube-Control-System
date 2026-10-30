// 연결 확인용 뼈대: broker 연결, 시작·중지 버튼, 받은 메시지 표시.
// TODO(web): YouTube IFrame 플레이어를 붙이고 zt/<기기>/player의 action으로 playVideo()·pauseVideo()를 부른다.
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

client.on("message", (topic, payload) => {
  const text = payload.toString();
  if (topic === `${base}/status`) {
    try { $("esp32").textContent = JSON.parse(text).state; } catch {}
  }
  const li = document.createElement("li");
  li.textContent = `${new Date().toLocaleTimeString()}  ${topic.slice(base.length + 1)}  ${text}`;
  $("log").prepend(li);
  while ($("log").children.length > 50) $("log").lastChild.remove();
});

const send = (cmd) => client.publish(`${base}/control`, JSON.stringify({ cmd }), { qos: 1 });
$("start").onclick = () => send("start");
$("stop").onclick = () => send("stop");
