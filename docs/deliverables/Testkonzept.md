# Testkonzept — Odoo IoT Digital Signage (TRMNL Integration)

Projekt: Odoo IoT Digital Signage (TRMNL Integration)
Version: 1.0  
Datum: 03/10/2026

---

## 1. Überblick / Ziele
Ziel ist, die Qualität, Stabilität, Sicherheit und Bedienbarkeit des Odoo‑Moduls zur Anbindung von TRMNL‑Displays sicherzustellen. Abgedeckte Bereiche: Unit Tests, Datenbanktests, Integrationstests (Polling-basierte Kommunikation zwischen Odoo und TRMNL), Installation, GUI, Stress/Performance, Usability und Security.

---

## 2. Allgemeine Teststrategie
- Iteration 1: Aufbau der Entwicklungs- und Testumgebung (Docker, Odoo, PostgreSQL) sowie Definition der Testfälle und Testdaten. In dieser Phase werden noch keine automatisierten Tests implementiert.
- Iteration ≥2: schrittweise Implementierung von Unit Tests und Durchführung von Integrationstests. Zusätzlich werden manuelle Tests für GUI und Usability durchgeführt.
- Testdaten: einfache Testdatensätze und Dummy-Geräte werden in der Odoo-Datenbank erstellt, um verschiedene Szenarien zu testen.
- Testumgebung: lokale Entwicklungsumgebung mit Docker, Odoo und PostgreSQL. Die Tests werden auf den Entwicklungsrechnern der Teammitglieder durchgeführt.

---

## 3. Unit Tests
- Werden gemacht: Ja (ab Iteration 2).

- Umfang:
  - Odoo-Modelle: Feldvalidierungen, Pflichtfelder und grundlegende Constraints.
  - Geschäftslogik: Verarbeitung und Formatierung der Daten für die JSON-Antwort des Polling-Endpoints.
  - Controller: Prüfung, ob der HTTP-Endpoint korrekte JSON-Antworten liefert.

- Framework:
  - Odoo Test Framework
  - Python `unittest`

- Durchführung:
  Unit Tests werden lokal in der Entwicklungsumgebung ausgeführt.

---

## 4. Datenbank Tests

- Ziel: Sicherstellen der Datenintegrität sowie der korrekten Speicherung und Verarbeitung von Daten in der Odoo-Datenbank.

- Testziele:
  - Validierung von Pflichtfeldern und Feldtypen
  - korrekte Speicherung und Aktualisierung von Datensätzen
  - Konsistenz zwischen den verwendeten Odoo-Modellen

- Vorgehen:
  - Testdatensätze und Dummy-Geräte werden direkt in der Odoo-Datenbank erstellt.
  - Es wird überprüft, ob Datensätze korrekt gespeichert, geändert und wieder ausgelesen werden können.

- Testumgebung:
  - PostgreSQL Datenbank innerhalb der lokalen Docker-Umgebung.
---

## 5. Integrationstests

- Ziel: Überprüfung der Integration zwischen dem Odoo-Modul und den TRMNL-Displays.

- Use Cases / Tests:

  - Polling Flow: Das TRMNL-Gerät ruft den Odoo-Endpoint auf und erhält Daten im JSON-Format.  
    Es wird geprüft, ob der Endpoint erreichbar ist und eine gültige Antwort liefert.

  - Datenänderungen: Änderungen an Daten in Odoo werden gespeichert und beim nächsten Polling korrekt ausgegeben.

  - Fehlerfälle: Tests mit ungültigen oder fehlenden Daten, um zu prüfen, ob das System stabil bleibt und kontrollierte Antworten liefert.

- Testmethoden:
  - HTTP-Anfragen mit `curl` oder Postman
  - Überprüfung der JSON-Antworten
  - Die Tests werden mit einem realen TRMNL-Display durchgeführt.

- Durchführung:
  Integrationstests werden lokal in der Docker-Testumgebung durchgeführt.

---

## 6. Installationstests

- Ziel: Überprüfung, dass das Odoo-Modul korrekt installiert und gestartet werden kann.

- Systeme:
  - Linux (Docker-Umgebung)
  - optional manuell getestet auf Windows oder macOS (Entwicklungsrechner)

- Ablauf:
  1. Start der Docker-Container (Odoo und PostgreSQL)
  2. Installation des Moduls über die Odoo-Oberfläche
  3. Konfiguration eines TRMNL-Displays im System
  4. Überprüfung, ob das Display den Endpoint `/trmnl/data` aufrufen und Daten anzeigen kann

- Erfolg:
  Das Modul lässt sich ohne Fehler installieren und das TRMNL-Display kann Daten aus Odoo abrufen und anzeigen.
---

## 7. GUI Tests

- Strategie:
  Die Benutzeroberfläche des Odoo-Moduls wird hauptsächlich manuell getestet.

- Umfang:
  - Anlegen und Bearbeiten eines TRMNL-Displays im Odoo-Modul
  - Überprüfung der Formularvalidierungen
  - Speicherung und Anzeige der konfigurierten Daten

- Durchführung:
  Die Tests werden über das Odoo Web Interface durchgeführt, indem typische Benutzeraktionen im System ausgeführt werden.

- Dokumentation:
  Fehler oder unerwartetes Verhalten werden mit Screenshots und einer kurzen Beschreibung dokumentiert.

---

## 8. Stress / Performance Tests

- Ziel: Überprüfung, ob das System mehrere gleichzeitige Anfragen verarbeiten kann.

- Testszenarien:
  - Mehrere gleichzeitige HTTP-Anfragen an den Polling-Endpoint `/trmnl/data`
  - Wiederholte Datenabfragen über einen längeren Zeitraum

- Tools:
  - `curl`
  - Apache Benchmark (`ab`)

- Durchführung:
  Mehrere Anfragen werden parallel an den Endpoint gesendet, um zu prüfen,
  ob der Server weiterhin korrekt antwortet.

- Erwartetes Ergebnis:
  Der Endpoint bleibt erreichbar und liefert weiterhin gültige JSON-Antworten.

---

## 9. Usability Tests

- Ziel: Überprüfung, ob die Einrichtung und Nutzung des Systems für Benutzer verständlich und einfach durchzuführen ist.

- Zielgruppe:
  - Administratoren, die das TRMNL-Display mit Odoo verbinden und konfigurieren.

- Vorgehen:
  - Teammitglieder führen die Einrichtung eines TRMNL-Displays durch.
  - Dabei wird überprüft, ob die notwendigen Schritte verständlich sind und ohne Probleme durchgeführt werden können.

- Bewertung:
  - Verständlichkeit der Konfiguration
  - Klarheit der Benutzeroberfläche
  - mögliche Fehlermeldungen oder unklare Schritte

- Ergebnis:
  Gefundene Usability-Probleme werden dokumentiert und wenn möglich verbessert.

---

## 10. Security Tests

- Ziel: Überprüfung grundlegender Sicherheitsaspekte der Anwendung.

- Tests:
  - Zugriff auf den Endpoint wird überprüft (z. B. mit gültigen und ungültigen Anfragen).
  - Überprüfung, dass sensible Daten nicht unbeabsichtigt im System ausgegeben werden.
  - Testen des Systems mit unerwarteten oder fehlerhaften Eingaben.

- Tools:
  - `curl`
  - manuelle Tests

- Erwartetes Ergebnis:
  Das System reagiert stabil auf ungültige Anfragen und gibt keine sensiblen Informationen preis.

---

## 11. Logging und Testresultate

- Logging:
  Das System verwendet die Standard-Logs von Odoo, um Fehler oder unerwartetes Verhalten zu protokollieren.

- Dokumentation der Tests:
  Die Ergebnisse der durchgeführten Tests werden während der Entwicklung dokumentiert.

- Abschluss:
  Am Ende des Projekts werden die wichtigsten Testergebnisse zusammen mit der Projektdokumentation abgegeben.

---



## 12. Iterationsplan

**Iteration 1**

* Testumgebung einrichten
* Testfälle definieren

**Iteration 2**

* Unit Tests implementieren
* Integrationstests durchführen

**Iteration 3**

* GUI-Tests und Usability-Tests
* Stress Tests durchführen

**Iteration 4**

* finale Tests
* Dokumentation der Resultate


---
## 13. Beispiel-Testfälle

TC-01: Polling Endpoint liefert gültige JSON-Daten  
Erwartet: HTTP Status 200 und gültige JSON-Antwort.

TC-02: Änderung eines Datensatzes in Odoo  
Erwartet: Änderungen erscheinen nach dem nächsten Polling-Aufruf.

TC-03: Ungültige Anfrage an Endpoint  
Erwartet: System reagiert stabil und gibt kontrollierte Fehlermeldung zurück.




