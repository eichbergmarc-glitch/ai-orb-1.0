/**
 * zustimmung.js - Rueckfragen des Orb auf dem Geraet beantworten, das gefragt hat.
 *
 * Der Orb fragt nach, bevor er etwas Folgenreiches tut: eine Datei
 * loeschen, ein Programm starten, etwas verschicken. Am Rechner zeigt
 * Electron dafuer ein Fenster.
 *
 * Wer vom iPad aus fragt, sitzt aber nicht vor diesem Fenster. Ohne
 * diese Datei erschiene die Rueckfrage in einem leeren Zimmer, liefe
 * nach der eingestellten Frist ab, und auf dem iPad haette man nur
 * gesehen, dass nichts geschieht - ohne Hinweis worauf gewartet wurde.
 * Genau das ist der Unterschied zwischen "der Orb reagiert nicht" und
 * "der Orb wartet auf deine Erlaubnis".
 *
 * Gefragt wird im Takt statt ueber den Ereigniskanal: Eine Rueckfrage
 * darf nicht verlorengehen, nur weil eine Verbindung kurz abriss - und
 * beim Oeffnen der Seite koennen bereits welche offen sein.
 */
(function installZustimmung() {
  "use strict";

  if (!document.documentElement.dataset.orbWeb) return;

  var TAKT = 2000;
  var offen = null;
  var behaelter = null;

  function bauen() {
    if (behaelter) return behaelter;
    behaelter = document.createElement("div");
    behaelter.className = "zustimmung";
    behaelter.hidden = true;
    behaelter.setAttribute("role", "dialog");
    behaelter.setAttribute("aria-live", "assertive");
    behaelter.innerHTML =
      '<div class="zustimmung__karte">' +
      '<div class="zustimmung__titel">Der Orb fragt</div>' +
      '<div class="zustimmung__text"></div>' +
      '<label class="zustimmung__merken">' +
      '<input type="checkbox" class="zustimmung__haken"> Nicht mehr fragen' +
      "</label>" +
      '<div class="zustimmung__knoepfe">' +
      '<button type="button" class="zustimmung__nein">Nein</button>' +
      '<button type="button" class="zustimmung__ja">Erlauben</button>' +
      "</div></div>";
    document.body.appendChild(behaelter);

    behaelter.querySelector(".zustimmung__ja").addEventListener("click", function () {
      void antworten(true);
    });
    behaelter.querySelector(".zustimmung__nein").addEventListener("click", function () {
      void antworten(false);
    });
    return behaelter;
  }

  function zeigen(frage) {
    var karte = bauen();
    offen = frage;

    var text = frage.detail || frage.permission || "Eine Handlung braucht deine Erlaubnis.";
    if (frage.actor) text = frage.actor + ": " + text;

    karte.querySelector(".zustimmung__text").textContent = text;
    karte.querySelector(".zustimmung__haken").checked = false;
    karte.hidden = false;
  }

  function verbergen() {
    offen = null;
    if (behaelter) behaelter.hidden = true;
  }

  async function antworten(erlaubt) {
    if (!offen) return;
    var merken = behaelter.querySelector(".zustimmung__haken").checked;
    var frage = offen;
    // Erst verbergen, dann senden: Ein zweiter Fingertipp auf denselben
    // Knopf waehrend der Uebertragung wuerde sonst dieselbe Erlaubnis
    // ein zweites Mal erteilen.
    verbergen();

    try {
      await fetch("/security/consent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          request_id: frage.request_id,
          granted: erlaubt,
          remember: merken,
          reason: erlaubt ? "Auf dem Gerät erlaubt." : "Auf dem Gerät abgelehnt.",
        }),
      });
    } catch (fehler) {
      // Die Antwort kam nicht an. Die Frage steht dann beim naechsten
      // Takt wieder da - besser, als sie stillschweigend zu verlieren.
      if (window.orbWeb) window.orbWeb.melde("Antwort kam nicht an.");
    }
  }

  async function nachsehen() {
    if (document.hidden) return;
    try {
      var antwort = await fetch("/security/consent", { credentials: "same-origin" });
      if (!antwort.ok) return;
      var daten = await antwort.json();
      var liste = Array.isArray(daten.pending) ? daten.pending : [];

      if (liste.length === 0) {
        if (offen) verbergen();
        return;
      }
      // Immer die aelteste zuerst - in der Reihenfolge, in der der Orb
      // gefragt hat.
      var naechste = liste[0];
      if (!offen || offen.request_id !== naechste.request_id) zeigen(naechste);
    } catch (fehler) {
      /* Kein Netz gerade. Der naechste Takt versucht es wieder. */
    }
  }

  window.setInterval(nachsehen, TAKT);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) void nachsehen();
  });
  void nachsehen();
})();
