/**
 * web-bridge.js - Der Orb im normalen Browser (iPad, Handy, fremder Rechner).
 *
 * Der Renderer spricht mit dem Betriebssystem nur ueber `window.aiOrb`.
 * In Electron legt `preload.ts` diese Bruecke an; im Browser gibt es
 * keinen Hauptprozess, der Fenster verschiebt oder Ordner oeffnet.
 *
 * Diese Datei ersetzt genau diese Bruecke - und nur sie:
 *
 * * Alles, was der Browser selbst kann (Konfiguration holen, Ereignisse
 *   empfangen, den Orb bewegen), wird hier ehrlich ausgefuehrt.
 * * Alles, was zwingend den Rechner braucht (Ordner oeffnen, Programm
 *   beenden), bleibt wirkungslos. Die zugehoerigen Knoepfe blendet
 *   `orb.css` ueber `[data-orb-web]` aus, damit niemand ins Leere tippt.
 *
 * Die Datei laedt VOR `renderer.js` und tut nichts, wenn `window.aiOrb`
 * bereits existiert. Electron und die Referenz-Vorschau bleiben dadurch
 * vollkommen unberuehrt.
 */
(function installWebBridge() {
  "use strict";

  // Electron (preload) oder die Referenz-Vorschau war schneller.
  if (window.aiOrb) return;
  // Ohne Server gibt es kein Backend - dann bleibt die Seite wie sie ist.
  if (window.location.protocol === "file:") return;

  var origin = window.location.origin;
  var backendListeners = [];
  var offsetListeners = [];
  var pointerListeners = [];

  // Der Versatz des Orb gegenueber der Bildmitte, in Pixeln - dieselbe
  // Groesse, die im Desktop-Betrieb der Hauptprozess fuehrt.
  var offset = { x: 0, y: 0 };

  document.documentElement.dataset.orbWeb = "true";

  /** Schickt ein Ereignis an alle Zuhoerer im Renderer. */
  function melde(name, payload) {
    backendListeners.forEach(function (callback) {
      try {
        callback({ event: name, payload: payload || {} });
      } catch (fehler) {
        // Ein stolpernder Zuhoerer darf die uebrigen nicht mitreissen.
        console.error("[web-bridge] Zuhoerer meldete Fehler:", fehler);
      }
    });
  }

  /**
   * Wie weit der Orb aus der Mitte darf.
   *
   * Er soll am Rand nicht halb verschwinden: ein Achtel der Seite bleibt
   * auf jeder Seite frei. Auf dem iPad ist das genug Platz zum Schieben
   * und trotzdem keine Falle, aus der man den Orb nicht zurueckholt.
   */
  function spielraum() {
    return {
      x: Math.max(0, window.innerWidth / 2 - window.innerWidth / 8),
      y: Math.max(0, window.innerHeight / 2 - window.innerHeight / 8),
    };
  }

  /** Verschiebt den Orb innerhalb der Seite. */
  function verschiebe(dx, dy) {
    var raum = spielraum();
    offset.x = Math.min(raum.x, Math.max(-raum.x, offset.x + dx));
    offset.y = Math.min(raum.y, Math.max(-raum.y, offset.y + dy));
    offsetListeners.forEach(function (callback) {
      callback({ x: offset.x, y: offset.y, immediate: true });
    });
  }

  // Dreht jemand das iPad, kann der Orb ausserhalb liegen. Ein Schub um
  // null Pixel zwingt ihn zurueck in den erlaubten Bereich.
  window.addEventListener("resize", function () {
    verschiebe(0, 0);
  });

  /**
   * Passt die Konfiguration an die Seite an, in der der Orb hier steht.
   *
   * Am Desktop ist das Fenster nur wenig groesser als der Orb - deshalb
   * genuegt dort ein kleiner Wert. Im Browser ist die ganze Seite sein
   * Raum; mit demselben Wert sass er als Muenze in einer leeren Flaeche.
   * Der Wert wird darum verdoppelt, aber gedeckelt, damit der Orb auch
   * auf einem schmalen Handy nicht ueber den Rand waechst.
   *
   * Wer es genau steuern will, setzt in der config.yaml unter `orb`
   * einen eigenen Wert `web_scale` - der hat immer Vorrang.
   */
  function fuerDenBrowser(config) {
    if (!config || typeof config !== "object") return {};
    var orb = config.orb;
    if (!orb || typeof orb !== "object") return config;

    if (typeof orb.web_scale === "number") {
      orb.scale = orb.web_scale;
    } else {
      var vorgabe = typeof orb.scale === "number" ? orb.scale : 0.28;
      orb.scale = Math.min(0.6, vorgabe * 2);
    }
    return config;
  }

  window.aiOrb = {
    /**
     * Holt die Konfiguration vom Backend.
     *
     * Faellt die Antwort aus, startet der Orb mit seinen Vorgabewerten -
     * sichtbar, statt gar nicht.
     */
    getConfig: function () {
      return fetch(origin + "/config", { credentials: "same-origin" })
        .then(function (antwort) {
          return antwort.ok ? antwort.json() : {};
        })
        .catch(function () {
          return {};
        })
        .then(fuerDenBrowser);
    },

    /** Das Backend liefert diese Seite selbst aus - gleiche Herkunft. */
    getBackendUrl: function () {
      return Promise.resolve(origin);
    },

    onBackendEvent: function (callback) {
      backendListeners.push(callback);
    },
    onOrbOffset: function (callback) {
      offsetListeners.push(callback);
    },
    onGlobalPointer: function (callback) {
      pointerListeners.push(callback);
    },

    /** Der Renderer meldet, wo der Orb gerade wirklich steht. */
    reportOrbOffset: function (x, y) {
      offset.x = x;
      offset.y = y;
    },

    performMenuAction: function (action) {
      if (action === "chat" || action === "search") {
        // Auf dem iPad ist die Tastatur der kuerzeste Weg zur Frage.
        melde("orb.chat.requested", { action: "open", source: "menue" });
        return;
      }
      // "files", "settings" und "quit" betreffen den Rechner, auf dem der
      // Kern laeuft. Aus der Ferne waere das eine Fernsteuerung fremder
      // Fenster - die Knoepfe sind im Browser deshalb ausgeblendet.
      console.info("[web-bridge] '" + action + "' gibt es nur am Rechner selbst.");
    },

    moveWindowBy: function (dx, dy) {
      verschiebe(dx, dy);
    },
    commitWindowPosition: function () {},
    showContextMenu: function () {},

    /** Doppeltippen oeffnet den Chat - der Rechner bleibt unberuehrt. */
    triggerDoubleClickAction: function () {
      melde("orb.chat.requested", { action: "open", source: "doppeltipp" });
    },

    setIgnoreMouseEvents: function () {},
    setInteractionLock: function () {},
    setChatFocus: function () {},
    setSpeaking: function () {},
    showLectureVisual: function () {},
  };

  /**
   * Schreibt einen Satz in den Chat - egal ob getippt oder gesprochen.
   *
   * Gesprochenes verschwindet, sobald es verklungen ist. Wer den Orb
   * unterwegs fragt, will spaeter nachlesen koennen, was er gefragt hat
   * und was zurueckkam - erst recht, wenn nebenan jemand redet und man
   * nicht sicher ist, ob man richtig gehoert hat.
   *
   * Geschrieben wird immer, **geoeffnet** wird nichts. Wer spricht, will
   * zuhoeren und nicht lesen; ein Fenster, das sich bei jeder Antwort
   * selbst aufschiebt, verdeckt den Orb und muss jedes Mal weggetippt
   * werden. Das Geschriebene wartet im Chat, bis jemand es sehen will.
   */
  function gesagt(text, wer) {
    var behaelter = document.getElementById("chat-messages");
    if (!behaelter || !text) return;

    var zeile = document.createElement("div");
    zeile.className = "chat-message chat-message--" + (wer === "user" ? "user" : "orb");
    zeile.textContent = text;
    behaelter.appendChild(zeile);
    behaelter.scrollTop = behaelter.scrollHeight;
  }

  /**
   * Zeigt oder verbirgt den Chat.
   *
   * Auf einem iPad gibt es keinen Rechtsklick, und das lange Druecken
   * auf den Orb finden nur die, denen man es gesagt hat. Deshalb muss
   * der Chat auch auf anderem Weg erreichbar sein: ueber einen sichtbaren
   * Knopf und ueber das gesprochene Wort.
   */
  function chatZeigen(an) {
    var panel = document.getElementById("chat-panel");
    if (!panel) return false;
    panel.hidden = !an;
    if (an) {
      var behaelter = document.getElementById("chat-messages");
      if (behaelter) behaelter.scrollTop = behaelter.scrollHeight;
    }
    document.documentElement.dataset.chatOffen = an ? "ja" : "nein";
    return true;
  }

  function chatOffen() {
    var panel = document.getElementById("chat-panel");
    return Boolean(panel) && panel.hidden === false;
  }

  // Der Chat laesst sich auf drei Wegen oeffnen: ueber den Knopf, ueber
  // das gesprochene Wort und ueber das Orb-Menue. Der dritte geht am
  // Renderer vorbei - wuerde nur `chatZeigen` den Zustand vermerken,
  // zeigte der Knopf nach einem Menue-Klick das Gegenteil an. Also wird
  // das Fenster selbst beobachtet statt der Weg dorthin.
  (function chatBeobachten() {
    var panel = document.getElementById("chat-panel");
    if (!panel || typeof MutationObserver !== "function") return;

    function merken() {
      document.documentElement.dataset.chatOffen = panel.hidden ? "nein" : "ja";
    }

    new MutationObserver(merken).observe(panel, {
      attributes: true,
      attributeFilter: ["hidden"],
    });
    merken();
  })();

  window.orbWeb = {
    melde: melde,
    gesagt: gesagt,
    chatZeigen: chatZeigen,
    chatOffen: chatOffen,
    zeigerZuhoerer: pointerListeners,
  };
})();
