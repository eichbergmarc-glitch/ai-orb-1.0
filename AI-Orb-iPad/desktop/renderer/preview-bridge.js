/**
 * Nebenwirkungsfreie Browser-Vorschau fuer den echten Orb-Renderer.
 *
 * Electron stellt `window.aiOrb` schon vor dem Laden dieser Datei bereit;
 * dann bleibt sie vollstaendig inaktiv. In einem lokalen Browser ersetzt sie
 * nur die Desktop-Bruecke und den Ereigniskanal. Dadurch laesst sich exakt
 * derselbe gebaute Renderer reproduzierbar aufnehmen und vergleichen.
 */
(function installOrbPreview() {
  "use strict";

  if (window.aiOrb) return;

  // Die Vorschau ist nur die Vorschau.
  //
  // Solange diese Datei jede Seite ohne Electron uebernahm, ersetzte sie
  // auch den echten Ereigniskanal durch eine Attrappe - im Browser sah
  // der Orb dann verbunden aus, obwohl nie ein Ereignis ankam. Sie
  // meldet sich deshalb nur noch, wenn die Adresse ausdruecklich nach
  // einer Aufnahme fragt (?preview=1, ?state=..., ?synaptix=1 ...) oder
  // die Seite ohne Server direkt von der Festplatte geoeffnet wurde.
  // Sonst uebernimmt web-bridge.js und spricht mit dem echten Backend.
  var vorschauParams = new URLSearchParams(window.location.search);
  var vorschauGewollt =
    vorschauParams.has("preview") ||
    vorschauParams.has("state") ||
    vorschauParams.has("synaptix") ||
    vorschauParams.has("professor") ||
    vorschauParams.has("scale") ||
    window.location.protocol === "file:";
  if (!vorschauGewollt) return;

  document.documentElement.dataset.orbPreview = "true";
  document.body.style.background =
    "radial-gradient(circle at 50% 42%, #0b2b56 0%, #03152d 48%, #010816 100%)";

  var params = new URLSearchParams(window.location.search);
  var state = params.get("state") || "idle";
  var professor = params.get("professor") === "1";
  // ?synaptix=1 zeigt das Synaptix-Gehirn statt des Energy-Orb.
  // Voreinstellung bleibt bewusst aus, damit bestehende
  // Referenzaufnahmen unveraendert vergleichbar bleiben.
  var synaptix = params.get("synaptix") === "1";
  var previewScale = Number(params.get("scale") || "0.28");
  if (!Number.isFinite(previewScale)) previewScale = 0.28;
  var backendListeners = [];
  var offsetListeners = [];
  var pointerListeners = [];

  window.aiOrb = {
    getConfig: async function () {
      return {
        orb: {
          energie: true,
          synaptix: synaptix,
          scale: previewScale,
          target_fps: 60,
          idle_fps: 60,
          adaptive_quality: false,
          presence_motion: false,
          bloom_strength: 0.62,
          bloom_radius: 0.35,
          bloom_threshold: 0.42,
          max_pixel_ratio: 1.5,
          transition_seconds: 0.65,
        },
        backend: { events_path: "/events" },
        smart_desktop: { movement_speed: "medium" },
      };
    },
    getBackendUrl: async function () { return "http://127.0.0.1:8765"; },
    onBackendEvent: function (callback) {
      backendListeners.push(callback);
      window.setTimeout(function () {
        callback({ event: "orb.state.changed", payload: { state: state } });
      }, 80);
      if (professor) {
        window.setTimeout(function () {
          callback({ event: "orb.professor.changed", payload: { active: true } });
        }, 120);
      }
    },
    onOrbOffset: function (callback) { offsetListeners.push(callback); },
    onGlobalPointer: function (callback) { pointerListeners.push(callback); },
    reportOrbOffset: function () {},
    performMenuAction: function () {},
    moveWindowBy: function () {},
    commitWindowPosition: function () {},
    showContextMenu: function () {},
    triggerDoubleClickAction: function () {},
    setIgnoreMouseEvents: function () {},
    setInteractionLock: function () {},
    setChatFocus: function () {},
    setSpeaking: function () {},
  };

  window.orbPreview = {
    emit: function (event, payload) {
      backendListeners.forEach(function (callback) {
        callback({ event: event, payload: payload || {} });
      });
    },
    move: function (x, y, immediate) {
      offsetListeners.forEach(function (callback) {
        callback({ x: x, y: y, immediate: immediate !== false });
      });
    },
    pointer: function (x, y) {
      pointerListeners.forEach(function (callback) { callback({ x: x, y: y }); });
    },
  };

  // BackendClient nutzt EventSource. Fuer die Vorschau bleibt die lokale
  // Verbindung offen, damit der Orb nicht kuenstlich in "offline" faellt.
  window.EventSource = function PreviewEventSource() {
    var self = this;
    self.close = function () {};
    window.setTimeout(function () {
      if (typeof self.onopen === "function") self.onopen();
    }, 30);
  };
})();
