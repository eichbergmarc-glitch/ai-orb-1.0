/**
 * stimme.js - Sprechen und Hoeren auf einem Geraet ohne eigenen Orb.
 *
 * Am Rechner hoert der Orb selbst zu: Ein Mikrofon liegt neben ihm, ein
 * Lautsprecher auch. Auf einem iPad ist beides im Geraet des Menschen,
 * und der Kern steht in einem anderen Zimmer. Diese Datei dreht den Weg
 * deshalb um - der Ton geht hin, die Antwort kommt zurueck.
 *
 * Drei Entscheidungen stecken darin, und jede hat einen Grund:
 *
 * 1. Aufgenommen wird mit der Web-Audio-Schnittstelle, nicht mit dem
 *    MediaRecorder. Der MediaRecorder liefert in Safari eine MP4-Datei,
 *    in Chrome eine WebM-Datei - beide muesste der Rechner erst
 *    umwandeln, und dafuer braeuchte er ein Programm, das auf einem
 *    frisch aufgesetzten Windows selten vorhanden ist. Hier entsteht
 *    stattdessen gleich das, was die Erkennung ohnehin will: 16 kHz,
 *    einkanalig, unkomprimiert.
 *
 * 2. Die Wiedergabe wird beim ersten Fingertipp freigeschaltet. iOS
 *    spielt Ton nur ab, wenn ein Mensch es angestossen hat - eine
 *    Antwort, die Sekunden spaeter eintrifft, gilt nicht mehr als
 *    angestossen. Der stumme Anstoss beim Tippen ist der Trick, mit dem
 *    die spaetere Antwort trotzdem zu hoeren ist.
 *
 * 3. Es gibt einen sichtbaren Knopf statt eines Weckworts. Ein iPad
 *    schlaeft, sobald der Bildschirm aus ist; ein dauerhaft lauschendes
 *    Mikrofon waere ein leeres Versprechen und ein voller Akku weniger.
 */
(function installStimme() {
  "use strict";

  // Nur im Browser. In Electron hoert der Orb mit seinem eigenen Mikrofon.
  if (!document.documentElement.dataset.orbWeb) return;

  var ZIELRATE = 16000;
  var HOECHSTDAUER = 60000;

  //: Ab welchem Pegel etwas als Sprache gilt. Wird beim Start an die
  //: Stille im Raum angepasst - ein Ventilator im Hintergrund ist sonst
  //: dauerhaft "Sprache", und die Aufnahme hoerte nie auf.
  var GRUNDSCHWELLE = 0.012;

  //: Wie lange still sein muss, damit die Aufnahme von selbst endet.
  //: Kuerzer schneidet Denkpausen mitten im Satz ab; laenger haengt am
  //: Ende jeder Frage als Wartezeit dran.
  var STILLE_MS = 1300;

  //: Vor dieser Zeit wird nicht abgebrochen, auch wenn es still ist.
  var MINDESTDAUER_MS = 700;

  var kontext = null;
  var quelle = null;
  var verarbeiter = null;
  var strom = null;
  var stuecke = [];
  var laeuft = false;
  var abgabeLaeuft = false;
  var stoppUhr = null;
  var tonspur = null;
  var freigeschaltet = false;

  var schwelle = GRUNDSCHWELLE;
  var grundrauschen = [];
  var letzteStimme = 0;
  var beginn = 0;
  var etwasGehoert = false;

  //: Freihaendig (12.11.2026): Das Handy hoert dauerhaft zu, und Synapse
  //: antwortet auf "Hey Synapse ..." - ohne den Knopf jedes Mal zu
  //: druecken. Einmal tippen schaltet es ein (iOS verlangt dafuer einen
  //: Fingertipp), nochmal tippen schaltet es aus.
  var dauer = false;
  var dauerErste = false;
  var abbruchOhneAbgabe = false;

  var knopf = document.getElementById("stimme-knopf");
  var anzeige = document.getElementById("stimme-anzeige");

  function melde(text) {
    if (anzeige) anzeige.textContent = text || "";
  }

  function zustand(name) {
    if (knopf) knopf.dataset.zustand = name;
  }

  /** Nimmt einen liegengebliebenen Abspiel-Knopf weg. */
  function nachreichenWeg() {
    var alt = document.getElementById("stimme-nachreichen");
    if (alt) alt.remove();
  }

  /** Der mittlere Pegel eines Stuecks - wie laut es gerade ist. */
  function pegel(daten) {
    var summe = 0;
    for (var i = 0; i < daten.length; i++) summe += daten[i] * daten[i];
    return Math.sqrt(summe / daten.length);
  }

  /**
   * Schaltet die Tonwiedergabe frei.
   *
   * Muss aus einem echten Fingertipp heraus geschehen, sonst verweigert
   * iOS spaeter jede Wiedergabe - ohne Fehlermeldung, einfach lautlos.
   */
  function tonFreischalten() {
    wiedergabeVorbereiten();
    if (freigeschaltet) return;
    freigeschaltet = true;
    tonspur = new Audio();
    tonspur.preload = "auto";
    tonspur.src =
      "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA=";
    var versuch = tonspur.play();
    if (versuch && typeof versuch.catch === "function") versuch.catch(function () {});
  }

  /** Rechnet die Aufnahme auf 16 kHz herunter. */
  function herunterrechnen(daten, vonRate) {
    if (vonRate === ZIELRATE) return daten;
    var verhaeltnis = vonRate / ZIELRATE;
    var laenge = Math.round(daten.length / verhaeltnis);
    var ergebnis = new Float32Array(laenge);
    var gelesen = 0;
    for (var i = 0; i < laenge; i++) {
      var bis = Math.round((i + 1) * verhaeltnis);
      var summe = 0;
      var anzahl = 0;
      // Mitteln statt jeden n-ten Wert nehmen: Wer einfach auslaesst,
      // erzeugt Zerrbilder hoher Toene, und die Erkennung hoert sie als
      // Zischen mit.
      for (var j = gelesen; j < bis && j < daten.length; j++) {
        summe += daten[j];
        anzahl++;
      }
      ergebnis[i] = anzahl > 0 ? summe / anzahl : 0;
      gelesen = bis;
    }
    return ergebnis;
  }

  /**
   * Schneidet Stille am Anfang und am Ende weg.
   *
   * Das ist die wirksamste Zeile im ganzen Sprachweg. Die Erkennung
   * rechnet ueber die gesamte Aufnahme, nicht nur ueber das Gesprochene:
   * Eine halbe Minute Aufnahme mit drei Sekunden Sprache kostete
   * dreizehn Sekunden Erkennung. Dieselben drei Sekunden allein kosten
   * ein bis zwei. Ein Fingerbreit Rand bleibt stehen, damit kein Laut
   * abgeschnitten wird.
   */
  function stilleWegschneiden(daten, rate) {
    var fensterlaenge = Math.max(1, Math.round(rate * 0.02));
    var rand = Math.round(rate * 0.15);

    var erstes = -1;
    var letztes = -1;
    for (var start = 0; start + fensterlaenge <= daten.length; start += fensterlaenge) {
      if (pegel(daten.subarray(start, start + fensterlaenge)) > schwelle) {
        if (erstes < 0) erstes = start;
        letztes = start + fensterlaenge;
      }
    }

    if (erstes < 0) return daten;  // Nichts gefunden - lieber alles schicken.

    var von = Math.max(0, erstes - rand);
    var bis = Math.min(daten.length, letztes + rand);
    return daten.subarray(von, bis);
  }

  async function starten() {
    if (laeuft || abgabeLaeuft) return;
    tonFreischalten();
    if (!dauer) nachreichenWeg();

    try {
      strom = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (fehler) {
      // Der haeufigste Fall hat nichts mit Erlaubnis zu tun: Ohne
      // verschluesselte Verbindung gibt Safari das Mikrofon gar nicht
      // erst heraus.
      if (!window.isSecureContext) {
        melde("Mikrofon braucht eine verschlüsselte Verbindung (https).");
      } else {
        melde("Kein Zugriff auf das Mikrofon.");
      }
      zustand("aus");
      return;
    }

    kontext = new (window.AudioContext || window.webkitAudioContext)();
    if (kontext.state === "suspended") {
      try {
        await Promise.race([kontext.resume(), warte(800)]);
      } catch (fehler) { /* unten behandelt */ }
    }
    // Ohne Fingertipp laesst iOS den Ton-Kontext manchmal schlafen. Dann
    // kommt kein einziger Ton an - lieber ehrlich aufgeben und um einen
    // Tipp bitten (siehe automatischStarten).
    if (kontext.state !== "running") {
      try { strom.getTracks().forEach(function (spur) { spur.stop(); }); } catch (f) { /* egal */ }
      try { await kontext.close(); } catch (f) { /* egal */ }
      kontext = null;
      return "gesperrt";
    }

    // Wiedergabe ueber Web Audio (12.11.2026): Startet das Zuhoeren beim
    // Oeffnen der Seite ohne Fingertipp, verweigert iOS dem Audio-Element
    // jede Wiedergabe - die Antwort kam an, blieb aber stumm. Ein
    // Ton-Kontext, der WAEHREND der Mikrofon-Aufnahme entsteht, laeuft
    // dagegen ohne Tipp. Er bleibt offen und spielt alle Antworten.
    wiedergabeVorbereiten();

    quelle = kontext.createMediaStreamSource(strom);
    verarbeiter = kontext.createScriptProcessor(4096, 1, 1);

    stuecke = [];
    schwelle = GRUNDSCHWELLE;
    grundrauschen = [];
    etwasGehoert = false;
    beginn = Date.now();
    letzteStimme = beginn;

    verarbeiter.onaudioprocess = function (ereignis) {
      if (!laeuft) return;
      var eingang = ereignis.inputBuffer.getChannelData(0);
      stuecke.push(new Float32Array(eingang));

      var jetzt = Date.now();
      var laut = pegel(eingang);

      // Die ersten Stuecke geben den Raum wieder, nicht die Stimme.
      // Aus ihnen entsteht die Schwelle - in einer lauten Kueche eine
      // andere als in einem stillen Zimmer.
      if (grundrauschen.length < 5) {
        grundrauschen.push(laut);
        if (grundrauschen.length === 5) {
          var mittel = grundrauschen.reduce(function (a, b) { return a + b; }, 0) / 5;
          schwelle = Math.max(GRUNDSCHWELLE, mittel * 3.5);
        }
        return;
      }

      if (laut > schwelle) {
        letzteStimme = jetzt;
        etwasGehoert = true;
        return;
      }

      // Freihaendig: Solange niemand spricht, nur die letzte Sekunde
      // behalten - sonst waechst die Aufnahme ueber Minuten Stille.
      if (dauer && !etwasGehoert && stuecke.length > 8) {
        stuecke = stuecke.slice(-4);
        beginn = jetzt;
        return;
      }

      // Von selbst aufhoeren, wenn jemand zu Ende gesprochen hat.
      if (
        etwasGehoert &&
        jetzt - beginn > MINDESTDAUER_MS &&
        jetzt - letzteStimme > STILLE_MS
      ) {
        void beenden();
      }
    };

    quelle.connect(verarbeiter);
    var stumm = kontext.createGain();
    stumm.gain.value = 0;
    verarbeiter.connect(stumm);
    stumm.connect(kontext.destination);

    laeuft = true;
    zustand("hoert");
    melde(dauer
      ? (dauerErste ? "Ich höre … (freihändig an)" : "Freihändig – sag „Hey Synapse …“")
      : "Ich höre … (hört von selbst auf)");

    stoppUhr = window.setTimeout(function () {
      void beenden();
    }, HOECHSTDAUER);
  }

  async function beenden() {
    if (!laeuft) return;
    laeuft = false;
    window.clearTimeout(stoppUhr);

    try {
      if (verarbeiter) {
        verarbeiter.onaudioprocess = null;
        verarbeiter.disconnect();
      }
      if (quelle) quelle.disconnect();
      if (strom) strom.getTracks().forEach(function (spur) { spur.stop(); });
    } catch (fehler) {
      /* Ein Abbau, der stolpert, darf die Aufnahme nicht verschlucken. */
    }

    var rate = kontext ? kontext.sampleRate : ZIELRATE;
    if (kontext) {
      try { await kontext.close(); } catch (fehler) { /* schon zu */ }
      kontext = null;
    }

    if (abbruchOhneAbgabe) {
      abbruchOhneAbgabe = false;
      stuecke = [];
      zustand("aus");
      return;
    }

    var gesamt = 0;
    stuecke.forEach(function (stueck) { gesamt += stueck.length; });
    if (gesamt < rate * 0.3 || (dauer && !etwasGehoert)) {
      stuecke = [];
      if (dauer) { weiterHoeren(); return; }
      melde("Das war zu kurz.");
      zustand("aus");
      return;
    }

    var alles = new Float32Array(gesamt);
    var stelle = 0;
    stuecke.forEach(function (stueck) { alles.set(stueck, stelle); stelle += stueck.length; });
    stuecke = [];

    var knapp = stilleWegschneiden(alles, rate);
    await abgeben(alsWav(herunterrechnen(knapp, rate)));
  }

  /** Verpackt die Werte als WAV-Datei. */
  function alsWav(daten) {
    var puffer = new ArrayBuffer(44 + daten.length * 2);
    var sicht = new DataView(puffer);

    function text(versatz, wort) {
      for (var i = 0; i < wort.length; i++) sicht.setUint8(versatz + i, wort.charCodeAt(i));
    }

    text(0, "RIFF");
    sicht.setUint32(4, 36 + daten.length * 2, true);
    text(8, "WAVE");
    text(12, "fmt ");
    sicht.setUint32(16, 16, true);
    sicht.setUint16(20, 1, true);
    sicht.setUint16(22, 1, true);
    sicht.setUint32(24, ZIELRATE, true);
    sicht.setUint32(28, ZIELRATE * 2, true);
    sicht.setUint16(32, 2, true);
    sicht.setUint16(34, 16, true);
    text(36, "data");
    sicht.setUint32(40, daten.length * 2, true);

    var stelle = 44;
    for (var i = 0; i < daten.length; i++, stelle += 2) {
      var wert = Math.max(-1, Math.min(1, daten[i]));
      sicht.setInt16(stelle, wert < 0 ? wert * 0x8000 : wert * 0x7fff, true);
    }
    return new Blob([puffer], { type: "audio/wav" });
  }

  var warteUhr = null;

  /** Zeigt, dass gearbeitet wird - und wie lange schon. */
  function warteAnzeige(an, was) {
    window.clearInterval(warteUhr);
    if (!an) return;
    var start = Date.now();
    melde(was);
    // Ein Knopf, der sich nicht ruehrt, sieht nach Absturz aus.
    warteUhr = window.setInterval(function () {
      melde(was + " " + Math.round((Date.now() - start) / 1000) + " s");
    }, 1000);
  }

  function warte(millisekunden) {
    return new Promise(function (fertig) {
      window.setTimeout(fertig, millisekunden);
    });
  }

  async function abgeben(blob) {
    abgabeLaeuft = true;
    zustand("denkt");
    warteAnzeige(true, "Einen Moment …");

    try {
      var kopf = { "Content-Type": "audio/wav" };
      // Die erste Aufnahme nach dem Einschalten gilt immer (man hat ja
      // gerade getippt); danach nur mit Weckwort oder kurz nach einer Antwort.
      if (dauer && !dauerErste) kopf["X-Orb-Dauer"] = "1";
      dauerErste = false;
      var antwort = await fetch("/stimme/aufnahme", {
        method: "POST",
        headers: kopf,
        body: blob,
        credentials: "same-origin",
      });

      if (!antwort.ok) {
        melde(antwort.status === 401 ? "Nicht angemeldet." : "Der Orb antwortet nicht.");
        return;
      }

      var ergebnis = await antwort.json();

      if (!ergebnis.frage) {
        // Freihaendig ist das der Normalfall (kein "Hey Synapse"): still
        // weiterhoeren statt "Nichts verstanden" zu zeigen.
        if (!dauer) melde("Nichts verstanden.");
        return;
      }

      window.orbWeb.gesagt(ergebnis.frage, "user");
      if (ergebnis.antwort) window.orbWeb.gesagt(ergebnis.antwort, "orb");

      // Ein Bedienbefehl wirkt sofort, noch bevor die Bestaetigung
      // gesprochen ist. Wer "Chat aktivieren" sagt, will den Chat sehen
      // und nicht zuerst hoeren, dass er gleich kommt.
      if (ergebnis.befehl === "chat_auf") window.orbWeb.chatZeigen(true);
      if (ergebnis.befehl === "chat_zu") window.orbWeb.chatZeigen(false);

      // Handy-Aktionen (12.11.2026): Anruf, SMS/WhatsApp, App, PDF.
      zeigeAktionen(ergebnis.aktionen || []);

      if (ergebnis.auftrag && ergebnis.teile > 0) {
        melde("");
        if (dauer) {
          // Freihaendig: erst zu Ende sprechen, dann wieder zuhoeren - sonst
          // hoert sich das Handy selbst.
          sprichtNoch = vorlesen(ergebnis.auftrag, ergebnis.teile);
        } else {
          // Nicht warten: Das Sprechen laeuft weiter, waehrend der Knopf
          // schon wieder bereit ist.
          void vorlesen(ergebnis.auftrag, ergebnis.teile);
        }
      } else if (ergebnis.ton) {
        // Die Antwort kommt noch in der alten Form: eine einzige Datei
        // statt Stuecken.
        //
        // Das passiert regelmaessig und ist keine Stoerung: Die
        // Oberflaeche wird bei jedem Aufruf frisch von der Platte
        // geliefert, der Python-Kern dagegen erst beim naechsten Start
        // ausgetauscht. Zwischen einer Aenderung und dem Neustart reden
        // also eine neue Seite und ein alter Kern miteinander. Wer nur
        // die neue Form kennt, laesst den Orb in dieser Zeit verstummen -
        // und es sieht aus wie ein Fehler, obwohl nur die Uhren
        // verschieden gehen.
        melde("");
        void vorlesenEinzeln("/stimme/ton?datei=" + encodeURIComponent(ergebnis.ton));
      } else if (ergebnis.antwort) {
        melde("Antwort steht im Chat - Stimme kam nicht zustande.");
      } else {
        melde("Keine Antwort erhalten.");
      }
    } catch (fehler) {
      melde("Die Verbindung brach ab.");
      handyMeldung("Fehler bei der Abgabe: " + (fehler && (fehler.message || fehler.name)));
    } finally {
      warteAnzeige(false);
      abgabeLaeuft = false;
      zustand("aus");
      if (dauer) {
        var warten = sprichtNoch;
        sprichtNoch = null;
        if (warten) { try { await warten; } catch (f) { /* egal */ } }
        weiterHoeren();
      }
    }
  }

  /**
   * Knoepfe fuer das, was Synapse auf dem Handy vorbereitet hat.
   *
   * iOS laesst eine Webseite nicht selbst anrufen oder senden - wohl aber
   * einen Verweis oeffnen, wenn der Mensch darauf tippt. Darum ein grosser
   * Knopf pro Aktion: "Peter anrufen", "WhatsApp an Peter senden",
   * "Reiseplan oeffnen".
   */
  var aktionsLeiste = null;
  var SYMBOLE = { anruf: "📞", nachricht: "💬", app: "📱", kurzbefehl: "⚡", dokument: "📄" };

  function zeigeAktionen(aktionen) {
    if (!aktionen || !aktionen.length) return;
    if (aktionsLeiste) aktionsLeiste.remove();
    aktionsLeiste = document.createElement("div");
    aktionsLeiste.setAttribute("role", "dialog");
    aktionsLeiste.style.cssText =
      "position:fixed;left:12px;right:12px;bottom:calc(16px + env(safe-area-inset-bottom));" +
      "z-index:9999;display:flex;flex-direction:column;gap:10px;padding:14px;" +
      "background:rgba(14,20,32,0.96);border:1px solid rgba(120,170,255,0.35);" +
      "border-radius:18px;box-shadow:0 10px 40px rgba(0,0,0,0.5);" +
      "font-family:system-ui,-apple-system,sans-serif;";
    aktionen.forEach(function (aktion) {
      var verweis = document.createElement("a");
      verweis.href = aktion.url;
      if (aktion.art === "dokument") verweis.target = "_blank";
      verweis.rel = "noopener";
      verweis.textContent = (SYMBOLE[aktion.art] || "➜") + "  " + aktion.titel;
      verweis.style.cssText =
        "display:block;padding:16px 18px;border-radius:14px;text-decoration:none;" +
        "font-size:18px;font-weight:600;color:#fff;text-align:center;" +
        "background:" + (aktion.art === "anruf" ? "#2e9e5b" : "#2f6fde") + ";";
      verweis.addEventListener("click", function () {
        tonFreischalten();
        window.setTimeout(function () {
          if (aktionsLeiste && aktion.art !== "dokument") { aktionsLeiste.remove(); aktionsLeiste = null; }
        }, 400);
      });
      aktionsLeiste.appendChild(verweis);
    });
    var zu = document.createElement("button");
    zu.type = "button";
    zu.textContent = "Schliessen";
    zu.style.cssText =
      "padding:10px;border:0;border-radius:12px;background:transparent;" +
      "color:#9fb3cf;font-size:15px;";
    zu.addEventListener("click", function (ereignis) {
      ereignis.stopPropagation();
      if (aktionsLeiste) { aktionsLeiste.remove(); aktionsLeiste = null; }
    });
    aktionsLeiste.appendChild(zu);
    document.body.appendChild(aktionsLeiste);
  }

  var sprichtNoch = null;

  /** Freihaendig: nach einer kurzen Pause wieder zuhoeren. */
  function weiterHoeren() {
    if (!dauer) return;
    window.setTimeout(function () {
      if (dauer && !laeuft && !abgabeLaeuft) void starten();
    }, 400);
  }

  /**
   * Holt ein Sprechstueck - und wartet, wenn es noch entsteht.
   *
   * Der Server antwortet mit 202, solange ein Stueck noch erzeugt wird.
   * Das ist keine Absage, sondern ein "gleich". Geholt wird als Datei
   * statt ueber die Adresse des Abspielers: So laesst sich ein "gleich"
   * von einem "gibt es nicht" unterscheiden - der Abspieler koennte das
   * nicht, er saehe nur, dass nichts kommt.
   */
  async function holeStueck(auftrag, nummer) {
    for (var versuch = 0; versuch < 150; versuch++) {
      try {
        var antwort = await fetch(
          "/stimme/ton?auftrag=" + encodeURIComponent(auftrag) + "&teil=" + nummer,
          { credentials: "same-origin" }
        );
      } catch (fehler) {
        return null;
      }
      if (antwort.status === 202) {
        await warte(700);
        continue;
      }
      if (!antwort.ok) return null;
      return await antwort.blob();
    }
    return null;
  }

  var wiedergabe = null;

  function wiedergabeVorbereiten() {
    try {
      if (!wiedergabe || wiedergabe.state === "closed") {
        wiedergabe = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (wiedergabe.state !== "running") {
        var p = wiedergabe.resume();
        if (p && p.catch) p.catch(function () {});
      }
    } catch (fehler) {
      wiedergabe = null;
    }
  }

  /** Spielt eine Datei ab und wartet, bis sie zu Ende ist. */
  async function abspielen(stueck) {
    if (wiedergabe && wiedergabe.state === "suspended") {
      try { await Promise.race([wiedergabe.resume(), warte(500)]); } catch (f) { /* egal */ }
    }
    if (wiedergabe && wiedergabe.state === "running") {
      try {
        var roh = await stueck.arrayBuffer();
        var puffer = await new Promise(function (gut, schlecht) {
          var r = wiedergabe.decodeAudioData(roh, gut, schlecht);
          if (r && r.then) r.then(gut, schlecht);
        });
        return await new Promise(function (fertig) {
          var q = wiedergabe.createBufferSource();
          q.buffer = puffer;
          q.connect(wiedergabe.destination);
          var vorbei = false;
          function schluss() { if (!vorbei) { vorbei = true; fertig("fertig"); } }
          q.onended = schluss;
          window.setTimeout(schluss, puffer.duration * 1000 + 2000);
          q.start(0);
        });
      } catch (fehler) {
        /* weiter mit dem Audio-Element */
      }
    }
    return abspielenElement(stueck);
  }

  /** Die alte Wiedergabe ueber ein Audio-Element (braucht unter iOS einen Tipp). */
  function abspielenElement(stueck) {
    return new Promise(function (fertig) {
      var adresse = URL.createObjectURL(stueck);
      if (!tonspur) tonspur = new Audio();
      tonspur.src = adresse;

      var beendet = false;
      var waechter = null;
      function schluss(ergebnis) {
        if (beendet) return;
        beendet = true;
        if (waechter) window.clearInterval(waechter);
        URL.revokeObjectURL(adresse);
        fertig(ergebnis);
      }

      // Waechter: Safari meldet das Ende nicht immer ("ended" bleibt aus,
      // wenn die Wiedergabe kurz unterbrochen wurde). Dann hing die
      // Antwort fuer immer an diesem Stueck, und die Stimme war weg.
      var letzteZeit = -1;
      var stillstand = 0;
      waechter = window.setInterval(function () {
        if (tonspur.ended) { schluss("fertig"); return; }
        if (tonspur.currentTime === letzteZeit) {
          stillstand += 1;
          if (stillstand >= 4 && tonspur.currentTime > 0) {
            // Vier Sekunden ohne Fortschritt nach begonnener Wiedergabe:
            // erst noch einmal anschieben, dann weiter zum naechsten Stueck.
            if (tonspur.paused && stillstand === 4) {
              var p = tonspur.play();
              if (p && p.catch) p.catch(function () {});
            }
            if (stillstand >= 8) schluss("fertig");
          }
        } else {
          stillstand = 0;
          letzteZeit = tonspur.currentTime;
        }
      }, 1000);

      tonspur.onended = function () { schluss("fertig"); };
      tonspur.onerror = function () { schluss("kaputt"); };

      var versuch = tonspur.play();
      if (versuch && typeof versuch.catch === "function") {
        versuch.catch(function (fehler) {
          // Die Art des Fehlers entscheidet, was zu tun ist - und was zu
          // sagen. "NotAllowedError" heisst: Der Ton liegt bereit, iOS
          // will nur eine Geste sehen. Jeder andere Fehler heisst: Es
          // gibt nichts abzuspielen.
          schluss((fehler && fehler.name) === "NotAllowedError" ? "gesperrt" : "kaputt");
        });
      }
    });
  }

  /**
   * Liest die Antwort vor - Stueck fuer Stueck.
   *
   * Waehrend ein Stueck laeuft, wird das naechste schon geholt. Dadurch
   * entsteht keine Pause zwischen den Saetzen, obwohl der Rechner noch
   * daran arbeitet.
   */
  /**
   * Bildschirm wach halten, solange gesprochen wird (12.11.2026).
   *
   * Ging das iPhone mitten in der Antwort in die Sperre, haelt Safari die
   * Seite an - die Stimme brach ab. Die Wake-Lock-Schnittstelle gibt es in
   * Safari seit iOS 16.4; wo sie fehlt, passiert einfach nichts.
   */
  var wachhalter = null;
  async function wachHalten(an) {
    try {
      if (an && !wachhalter && navigator.wakeLock && navigator.wakeLock.request) {
        wachhalter = await navigator.wakeLock.request("screen");
        wachhalter.addEventListener("release", function () { wachhalter = null; });
      } else if (!an && wachhalter) {
        var w = wachhalter;
        wachhalter = null;
        await w.release();
      }
    } catch (fehler) {
      wachhalter = null;
    }
  }

  async function vorlesen(auftrag, anzahl) {
    zustand("spricht");
    void wachHalten(true);

    var naechstes = holeStueck(auftrag, 0);
    var verloren = 0;

    for (var nummer = 0; nummer < anzahl; nummer++) {
      var stueck = await naechstes;

      // Ein Stueck fehlt? Einmal nachfassen, bevor aufgegeben wird - ein
      // kurzer Netzaussetzer (Tailscale, Mobilfunk) soll nicht die ganze
      // restliche Antwort kosten.
      if (!stueck) stueck = await holeStueck(auftrag, nummer);

      // Das uebernaechste schon anfordern, bevor dieses abgespielt wird.
      naechstes = nummer + 1 < anzahl ? holeStueck(auftrag, nummer + 1) : null;

      if (!stueck) {
        verloren++;
        if (nummer === 0 || verloren > 1) {
          melde(nummer === 0 ? "Der Ton kam nicht an." : "Die Stimme ist mittendrin ausgefallen.");
          handyMeldung("Ton nicht geholt: Stueck " + nummer + " von " + anzahl);
          break;
        }
        continue;  // dieses eine Stueck auslassen, mit dem naechsten weiter
      }

      var ergebnis = await abspielen(stueck);
      if (ergebnis === "kaputt") ergebnis = await abspielen(stueck);
      if (ergebnis === "gesperrt") {
        handyMeldung("Wiedergabe von iOS gesperrt (Stueck " + nummer + ")");
        melde("Antwort ist da – tippen zum Abspielen.");
        void wachHalten(false);
        nachreichen(stueck, auftrag, nummer, anzahl);
        return;
      }
      if (ergebnis === "kaputt") {
        verloren++;
        if (verloren > 1) {
          melde("Der Ton kam nicht an.");
          break;
        }
      }
    }

    handyMeldung("vorgelesen: " + (anzahl - verloren) + " von " + anzahl + " Stueck(en)" +
      (wiedergabe ? ", WebAudio " + wiedergabe.state : ", ohne WebAudio"));
    if (!dauer) void wachHalten(false);
    zustand("aus");
  }

  /** Spielt eine einzelne Tondatei ab (die aeltere Form der Antwort). */
  async function vorlesenEinzeln(adresse) {
    zustand("spricht");
    try {
      var antwort = await fetch(adresse, { credentials: "same-origin" });
      if (!antwort.ok) {
        melde("Der Ton kam nicht an.");
        zustand("aus");
        return;
      }
      var stueck = await antwort.blob();
      var ergebnis = await abspielen(stueck);
      if (ergebnis === "gesperrt") {
        melde("Antwort ist da.");
        nachreichen(stueck, "", 0, 1);
        return;
      }
      if (ergebnis === "kaputt") melde("Der Ton kam nicht an.");
    } catch (fehler) {
      melde("Der Ton kam nicht an.");
    }
    zustand("aus");
  }

  /** Bietet einen Knopf an, wenn iOS die Wiedergabe verweigert hat. */
  function nachreichen(stueck, auftrag, nummer, anzahl) {
    zustand("aus");
    var vorhanden = document.getElementById("stimme-nachreichen");
    if (vorhanden) vorhanden.remove();

    var knopf = document.createElement("button");
    knopf.id = "stimme-nachreichen";
    knopf.type = "button";
    knopf.className = "stimme__nachreichen";
    knopf.textContent = "▶ Antwort abspielen";
    knopf.addEventListener("click", async function () {
      knopf.remove();
      melde("");
      zustand("spricht");
      // Aus einem Fingertipp heraus laesst iOS die Wiedergabe zu.
      var ergebnis = await abspielen(stueck);
      if (ergebnis === "fertig" && nummer + 1 < anzahl) {
        await vorlesen2(auftrag, nummer + 1, anzahl);
      }
      zustand("aus");
    });

    var behaelter = document.getElementById("stimme");
    if (behaelter) behaelter.insertBefore(knopf, behaelter.firstChild);
  }

  /** Setzt das Vorlesen ab einem bestimmten Stueck fort. */
  async function vorlesen2(auftrag, ab, anzahl) {
    for (var nummer = ab; nummer < anzahl; nummer++) {
      var stueck = await holeStueck(auftrag, nummer);
      if (!stueck) return;
      if ((await abspielen(stueck)) !== "fertig") return;
    }
  }

  var chatKnopf = document.getElementById("chat-knopf");
  if (chatKnopf) {
    chatKnopf.addEventListener("click", function (ereignis) {
      ereignis.preventDefault();
      window.orbWeb.chatZeigen(!window.orbWeb.chatOffen());
    });
  }

  var chatSchliessen = document.getElementById("chat-close");
  if (chatSchliessen) {
    // Das Kreuz im Chat schliesst ihn - der Knopf unten muss das
    // mitbekommen, sonst zeigt er weiter "offen" an.
    chatSchliessen.addEventListener("click", function () {
      window.setTimeout(function () { window.orbWeb.chatZeigen(false); }, 0);
    });
  }

  if (knopf) {
    knopf.addEventListener("click", function (ereignis) {
      ereignis.preventDefault();
      if (dauer) {
        // Freihaendig aus: laufende Aufnahme verwerfen - und das merken,
        // damit die Seite beim naechsten Oeffnen nicht von selbst zuhoert.
        dauer = false;
        merkeFreihaendig(false);
        void wachHalten(false);
        if (laeuft) { abbruchOhneAbgabe = true; void beenden(); }
        melde("Freihändig aus.");
        zustand("aus");
        return;
      }
      if (laeuft) {
        void beenden();
        return;
      }
      // Einmal tippen: freihaendig an. Die erste Frage braucht kein Weckwort.
      dauer = true;
      dauerErste = true;
      merkeFreihaendig(true);
      void wachHalten(true);
      void starten();
    });
    zustand("aus");
    automatischStarten();
  }

  /**
   * Beim Oeffnen der Seite sofort freihaendig zuhoeren (12.11.2026).
   *
   * Marc will das Mikrofon nicht jedes Mal antippen: Seite auf, "Hey
   * Synapse", fertig. Das klappt, sobald Safari das Mikrofon fuer diese
   * Adresse dauerhaft erlaubt hat. Laesst iOS den Ton ohne Fingertipp
   * nicht zu, genuegt EIN Tipp irgendwo auf der Seite - nicht gezielt auf
   * den Knopf.
   */
  function merkeFreihaendig(an) {
    try { window.localStorage.setItem("orbFreihaendig", an ? "an" : "aus"); } catch (f) { /* egal */ }
  }

  function freihaendigGewuenscht() {
    try { return window.localStorage.getItem("orbFreihaendig") !== "aus"; } catch (f) { return true; }
  }

  /**
   * Seit 12.11.2026 (Nachmittag): IMMER ein Tipp zum Start.
   *
   * Das Zuhoeren ohne Tipp lief zwar, aber iOS liess die Antworten dann
   * nicht abspielen - Synapse "antwortete nicht", obwohl die Antwort
   * fertig war. Ein einziger Tipp irgendwo auf der Seite schaltet Ton UND
   * Mikrofon frei; danach laeuft alles freihaendig mit "Hey Synapse".
   */
  async function automatischStarten() {
    if (!freihaendigGewuenscht() || dauer || laeuft) return;
    var schleier = document.createElement("div");
    schleier.id = "stimme-start";
    schleier.style.cssText =
      "position:fixed;inset:0;z-index:9998;display:flex;align-items:center;" +
      "justify-content:center;background:rgba(5,10,20,0.55);" +
      "font-family:system-ui,-apple-system,sans-serif;";
    var text = document.createElement("div");
    text.textContent = "Tippen – dann hört Synapse auf „Hey Synapse“";
    text.style.cssText =
      "padding:22px 26px;border-radius:18px;background:rgba(14,20,32,0.95);" +
      "color:#fff;font-size:20px;font-weight:600;text-align:center;max-width:80%;" +
      "border:1px solid rgba(120,170,255,0.4);";
    schleier.appendChild(text);
    document.body.appendChild(schleier);

    function einTipp(ereignis) {
      if (ereignis) { ereignis.preventDefault(); ereignis.stopPropagation(); }
      schleier.remove();
      if (dauer || laeuft) return;
      // Ton und Mikrofon muessen aus genau diesem Tipp heraus starten.
      freigeschaltet = false;
      tonFreischalten();
      dauer = true;
      dauerErste = false;
      merkeFreihaendig(true);
      void wachHalten(true);
      handyMeldung("gestartet (freihaendig, nach Tipp)");
      void starten();
    }
    schleier.addEventListener("click", einTipp, { once: true });
  }

  /**
   * Neue Fassung? Dann neu laden (12.11.2026). Safari liess die Seite
   * sonst mit dem alten Programm weiterlaufen, und Korrekturen kamen nie an.
   * Nur wenn gerade nichts laeuft - nie mitten in einer Antwort.
   */
  var eigeneVersion = null;
  async function versionPruefen() {
    try {
      var antwort = await fetch("/stimme/version", { cache: "no-store", credentials: "same-origin" });
      if (!antwort.ok) return;
      var v = (await antwort.json()).version || "";
      if (!v) return;
      if (eigeneVersion === null) { eigeneVersion = v; return; }
      if (v !== eigeneVersion && !abgabeLaeuft && !sprichtNoch) {
        handyMeldung("neue Fassung - Seite wird neu geladen");
        window.location.reload();
      }
    } catch (f) { /* egal */ }
  }
  void versionPruefen();
  window.setInterval(versionPruefen, 60000);

  /** Kurze Rueckmeldung an den PC, damit Fehler im Protokoll stehen. */
  function handyMeldung(text) {
    try {
      void fetch("/stimme/meldung", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: String(text).slice(0, 300) }),
        credentials: "same-origin",
      }).catch(function () {});
    } catch (f) { /* egal */ }
  }
})();
