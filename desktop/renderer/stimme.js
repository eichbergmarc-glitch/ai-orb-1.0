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
    nachreichenWeg();

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
    if (kontext.state === "suspended") await kontext.resume();

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
    melde("Ich höre … (hört von selbst auf)");

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

    var gesamt = 0;
    stuecke.forEach(function (stueck) { gesamt += stueck.length; });
    if (gesamt < rate * 0.3) {
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
      var antwort = await fetch("/stimme/aufnahme", {
        method: "POST",
        headers: { "Content-Type": "audio/wav" },
        body: blob,
        credentials: "same-origin",
      });

      if (!antwort.ok) {
        melde(antwort.status === 401 ? "Nicht angemeldet." : "Der Orb antwortet nicht.");
        return;
      }

      var ergebnis = await antwort.json();

      if (!ergebnis.frage) {
        melde("Nichts verstanden.");
        return;
      }

      window.orbWeb.gesagt(ergebnis.frage, "user");
      if (ergebnis.antwort) window.orbWeb.gesagt(ergebnis.antwort, "orb");

      // Ein Bedienbefehl wirkt sofort, noch bevor die Bestaetigung
      // gesprochen ist. Wer "Chat aktivieren" sagt, will den Chat sehen
      // und nicht zuerst hoeren, dass er gleich kommt.
      if (ergebnis.befehl === "chat_auf") window.orbWeb.chatZeigen(true);
      if (ergebnis.befehl === "chat_zu") window.orbWeb.chatZeigen(false);

      if (ergebnis.auftrag && ergebnis.teile > 0) {
        melde("");
        // Nicht warten: Das Sprechen laeuft weiter, waehrend der Knopf
        // schon wieder bereit ist.
        void vorlesen(ergebnis.auftrag, ergebnis.teile);
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
    } finally {
      warteAnzeige(false);
      abgabeLaeuft = false;
      zustand("aus");
    }
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

  /** Spielt eine Datei ab und wartet, bis sie zu Ende ist. */
  function abspielen(stueck) {
    return new Promise(function (fertig) {
      var adresse = URL.createObjectURL(stueck);
      if (!tonspur) tonspur = new Audio();
      tonspur.src = adresse;

      var beendet = false;
      function schluss(ergebnis) {
        if (beendet) return;
        beendet = true;
        URL.revokeObjectURL(adresse);
        fertig(ergebnis);
      }

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
  async function vorlesen(auftrag, anzahl) {
    zustand("spricht");

    var naechstes = holeStueck(auftrag, 0);

    for (var nummer = 0; nummer < anzahl; nummer++) {
      var stueck = await naechstes;

      // Das uebernaechste schon anfordern, bevor dieses abgespielt wird.
      naechstes = nummer + 1 < anzahl ? holeStueck(auftrag, nummer + 1) : null;

      if (!stueck) {
        melde(nummer === 0 ? "Der Ton kam nicht an." : "Die Stimme ist mittendrin ausgefallen.");
        break;
      }

      var ergebnis = await abspielen(stueck);
      if (ergebnis === "gesperrt") {
        melde("Antwort ist da.");
        nachreichen(stueck, auftrag, nummer, anzahl);
        return;
      }
      if (ergebnis === "kaputt") {
        melde("Der Ton kam nicht an.");
        break;
      }
    }

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
      if (laeuft) {
        void beenden();
      } else {
        void starten();
      }
    });
    zustand("aus");
  }
})();
