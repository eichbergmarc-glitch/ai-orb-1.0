"""Ersetzt in app.asar die Oberflaeche (desktop/electron/dist) durch den aktuellen Stand.

Aufruf: python asar_erneuern.py <app.asar> <projekt/desktop/electron/dist> <ziel.asar>
"""
import copy
import json
import os
import struct
import sys

quelle, dist, ziel = sys.argv[1:4]

with open(quelle, "rb") as f:
    kopf = f.read(16)
    s = struct.unpack("<I", kopf[4:8])[0]
    laenge = struct.unpack("<I", kopf[12:16])[0]
    baum = json.loads(f.read(laenge))
    basis = 8 + s

    # Neue Dateien einsammeln: dist/electron und dist/renderer, ohne Sicherungen.
    neu = {}
    for teil in ("electron", "renderer"):
        wurzel = os.path.join(dist, teil)
        for ordner, _, dateien in os.walk(wurzel):
            for name in dateien:
                if ".vor-" in name or name.endswith(".map"):
                    continue
                pfad = os.path.join(ordner, name)
                rel = os.path.relpath(pfad, dist).replace(os.sep, "/")
                neu["desktop/electron/dist/" + rel] = pfad

    def knoten(pfad, anlegen):
        node = baum
        teile = pfad.split("/")
        for k in teile[:-1]:
            node = node.setdefault("files", {})
            if k not in node:
                if not anlegen:
                    return None, None
                node[k] = {"files": {}}
            node = node[k]
        return node.setdefault("files", {}), teile[-1]

    for rel in neu:
        eltern, name = knoten(rel, True)
        eltern.setdefault(name, {})

    # Alle Dateien in Reihenfolge neu ablegen.
    ausgabe = []  # (pfad, quelle) quelle = ("alt", offset, size) | ("neu", datei)
    neuer_baum = copy.deepcopy(baum)

    def gehen(node, neu_node, prefix):
        for k in list(node.get("files", {})):
            v = node["files"][k]
            nv = neu_node["files"][k]
            rel = (prefix + "/" + k).lstrip("/")
            if "files" in v:
                gehen(v, nv, rel)
                continue
            if v.get("unpacked") or "link" in v:
                continue
            if rel in neu:
                ausgabe.append((nv, ("neu", neu[rel])))
                nv.pop("integrity", None)
            else:
                ausgabe.append((nv, ("alt", int(v["offset"]), int(v["size"]))))

    gehen(baum, neuer_baum, "")

    offset = 0
    for nv, q in ausgabe:
        groesse = os.path.getsize(q[1]) if q[0] == "neu" else q[2]
        nv["offset"] = str(offset)
        nv["size"] = groesse
        offset += groesse

    j = json.dumps(neuer_baum, separators=(",", ":")).encode("utf-8")
    ausgerichtet = (len(j) + 3) // 4 * 4
    nutz = 4 + ausgerichtet
    kopfgroesse = 4 + nutz
    with open(ziel, "wb") as o:
        o.write(struct.pack("<IIII", 4, kopfgroesse, nutz, len(j)))
        o.write(j + b"\0" * (ausgerichtet - len(j)))
        for nv, q in ausgabe:
            if q[0] == "neu":
                with open(q[1], "rb") as g:
                    o.write(g.read())
            else:
                f.seek(basis + q[1])
                rest = q[2]
                while rest:
                    stueck = f.read(min(rest, 1 << 20))
                    o.write(stueck)
                    rest -= len(stueck)

print(f"{len(neu)} Dateien ersetzt/ergaenzt, {len(ausgabe)} Dateien im Archiv -> {ziel}")
