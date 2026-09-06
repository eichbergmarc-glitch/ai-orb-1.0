interface FlipperStatus { connected:boolean; port:string|null; deviceName:string|null; serial:string|null; qFlipperInstalled:boolean; wifiBoardConnected:boolean }
interface FlipperBridge { status():Promise<FlipperStatus>; openQFlipper():Promise<boolean>; chooseApp():Promise<string|null> }
declare global { interface Window { flipperCenter: FlipperBridge } }
const byId=(id:string)=>document.getElementById(id)!;
async function refresh():Promise<void>{
  byId("status-line").textContent="Geräte werden geprüft …";
  const s=await window.flipperCenter.status(); const connection=byId("connection");
  connection.classList.toggle("online",s.connected);
  connection.querySelector("strong")!.textContent=s.connected?`Verbunden · ${s.port??"USB"}`:"Nicht verbunden";
  byId("device-name").textContent=s.connected?(s.deviceName??"Flipper Zero"):"Kein Flipper erkannt";
  byId("device-port").textContent=s.port??"–"; byId("device-serial").textContent=s.serial??"–";
  byId("bridge-status").textContent=s.qFlipperInstalled?"qFlipper bereit":"Nicht installiert";
  const wifi=byId("wifi-status"); wifi.textContent=s.wifiBoardConnected?"Direkt per USB erkannt":"Nicht direkt verbunden";
  wifi.className=`badge ${s.wifiBoardConnected?"safe":"warn"}`;
  byId("status-line").textContent=s.connected?"Flipper bereit":"USB-Verbindung prüfen";
}
document.querySelectorAll<HTMLButtonElement>(".tabs button").forEach(button=>button.addEventListener("click",()=>{
  document.querySelectorAll(".tabs button,.page").forEach(el=>el.classList.remove("active")); button.classList.add("active"); byId(button.dataset.tab!).classList.add("active");
}));
document.querySelectorAll<HTMLElement>("[data-open-qflipper]").forEach(el=>el.addEventListener("click",async()=>{byId("status-line").textContent=(await window.flipperCenter.openQFlipper())?"Live-Steuerung geöffnet":"qFlipper wurde nicht gefunden";}));
byId("remote").addEventListener("click",async()=>{await window.flipperCenter.openQFlipper();});
byId("refresh").addEventListener("click",refresh); byId("wifi-refresh").addEventListener("click",refresh);
byId("choose-fap").addEventListener("click",async()=>{const selected=await window.flipperCenter.chooseApp();if(!selected)return;byId("app-result").textContent=`Ausgewählt: ${selected}. Öffne im qFlipper-Dateimanager /ext/apps und lade die App dort hoch.`;await window.flipperCenter.openQFlipper();});
void refresh(); export {};
