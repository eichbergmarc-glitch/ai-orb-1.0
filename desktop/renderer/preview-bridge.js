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

  document.documentElement.dataset.orbPreview = "true";
  document.body.style.background =
    "radial-gradient(circle at 50% 42%, #0b2b56 0%, #03152d 48%, #010816 100%)";

  var params = new URLSearchParams(window.location.search);
  var state = params.get("state") || "idle";
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
