#PSE-FS26

## Projektname
PSE — Odoo IoT für Digital Signage

## Kurzprojektbeschreibung
Ziel: Entwicklung eines Odoo‑Moduls zur Verwaltung von TRMNL e‑Ink Displays und einer Anbindung an TRMNL, sodass verschiedene Daten aus Odoo (z.B. Kalender, Produktinformationen, Preisschilder, Raumbelegung) dynamisch auf den Displays dargestellt werden können.

Kernfunktionen
- Geräteverwaltung in Odoo (Registrierung, Metadaten, Standort)
- Content‑Mapping (Welche Odoo‑Daten werden auf welchem Display gezeigt)
- Scheduling / Updates (Zeitpläne für Inhalte)
- Kommunikation mit TRMNL (API/HTTP/Webhooks, Auth)
- Logging, Monitoring, Fehlerbehandlung
- Installations‑ und Betriebsanleitungen

Quellen
- Odoo: https://www.odoo.com
- TRMNL Developer Docs: https://trmnl.com/developers
- Projektproposal/Vorlesungsunterlagen (PSE Handbuch & Zeitplan)

## Kunde & Ansprechpartner
- Kunde: Abilium GmbH  
- Ansprechpartner:
  - Jakob Schaerer — jakob.schaerer@abilium.com
  - Severin Zumbrunn — severin.zumbrunn@abilium.com

## Team / Gruppenmitglieder
- Timur Umut Turgul — Key Account Manager (Kundenkontakt)
- Sascha Friedli — Chief Deliverable Officer (Deliverables / Termine)
- Leïla Ayinkamiye — Quality Evangelist (Testkonzept, Tests)
- Claudio Berger — Master Tracker (Statusreports, Tracking)


## Rollenbeschreibung
- Key Account Manager: Single point of contact zum Kunden, organisiert Kundentermine.
- Chief Deliverable Officer: Zuständig für pünktliche Abgabe von Deliverables.
- Quality Evangelist: Testkonzept erstellen, Tests koordinieren und Abnahme begleiten.
- Master Tracker: Wöchentliche Statusberichte, Zeitschätzungen, Aktualisierung Arbeitsplan.

## Repository Struktur (Vorschlag)
- /docs
  - /design
  - /user_manual
  - /test
  - /meeting_notes
  - /deliverables
- /odoo_module
  - __manifest__.py, models/, views/, controllers/, static/
- /integration
  - trmnl_client/, mocks/, api_tests/
- /scripts
  - setup.sh, migrate.sh
- /ci
  - pipeline configs (github actions / gitlab ci)
- requirements.txt
- README.md

## Erste Schritte (Setup)
1. Repository klonen: git clone <repo-url>
2. Virtuelle Umgebung: python -m venv .venv && source .venv/bin/activate
3. Abhängigkeiten: pip install -r requirements.txt
4. Odoo‑Entwicklungsinstanz einrichten (Version eintragen)
5. PostgreSQL konfigurieren und DB anlegen
6. Modul installieren in Odoo Developer Mode (Ordner /odoo_module)
7. TRMNL‑Docs sichten; API‑Zugänge/Keys über Key Account Manager anfragen
8. CI initialisieren (push → Tests)

## Branching & Workflow
- ...
- Pull Requests mit mindestens 1 Reviewer

## Tasks, Planning & Schätzung
- Planning Game zu Beginn jeder Iteration mit Kunde: Kunde schreibt Stories, Team schätzt in idealen Personentagen, Kunde priorisiert.
- Nach Planning Game: Detailplanung (Tasks, Verantwortliche eintragen, Aufwand schätzen.
- Tasks sollen klein, testbar und mit klarer Verantwortlichkeit sein.

## Deliverables & Deadlines 
- Arbeitsplan(04.03.2026)
- Analyse der ersten Iteration(18.03.2026)
- Testkonzept und Testresultate(01.04.2026)
- Produkt(13.05.2026)
- Dokumentation(13.05.2026)

Iteration Deadlines
- Ende Iteration 1: Testkonzept V1, Analyse Iteration 1
- Ende Iteration 2: Testkonzept V2, Demo 1
- Ende Iteration 3: Technologie & Architektur Präsentation
- Ende Iteration 4: Testresultate, Dokumentation, Schlussdemo

## Teststrategie
- Unit Tests (pytest / unittest)
- Datenbanktests (Fixtures, Testdaten)
- Integrationstests (Odoo module <-> TRMNL API, end‑to‑end)
- Installationstests (Anleitung prüfen)
- Usability Tests (kurze Sessions mit Zielanwendern)
- Testkonzept V1: Ende Iteration 1, V2: Ende Iteration 2

## TRMNL / Hardware
- Physische TRMNL e‑Ink Displays sind für Entwicklung nicht sofort nötig.
- Entwicklung gegen API/Mocks/Emulator starten.
- Physische Geräte für Integration/Demo später beschaffen (evtl. Kunde stellt Geräte).
- Frühzeitig API‑Specs / Auth‑Methodik vom Kunden / Abilium anfordern.

## Statusreport & Risikoanalyse (Template)
Statusreport (wöchentlich)
- Kurzer Text (Status bzgl. Iterationsziele, 2–3 Sätze)
- Ampel: OK / IM VERZUG / KRITISCH
- Hinweis auf Blocker + Maßnahmen

Risikoanalyse
- Risiko: kurzer Titel
- Eintrittswahrscheinlichkeit: sehr gross / gross / klein / sehr klein
- Gewichtung (1 Satz)
- Gegenmassnahme (1 Satz)

## Präsentationen & Demos
- Alle Gruppenmitglieder müssen mindestens eine Präsentation oder Demo halten.
- Demos mit Story‑Durchlauf, Plan B bei Ausfall.
- Technische/Architektur‑Präsentation: Frameworks, Architekturdiagramme, Designentscheidungen.

## Reporting / Meetings
- Wöchentliches Teammeeting (fester Termin), Agenda + Sitzungsleiter + Protokollführer
- Kundensitzungen: Planning Game zu Iterationsstart
- Code Reviews regelmäßig, mindestens 1 Reviewer vor Merge

## To‑Do (erste Woche) — Checkliste
- [ ] Handbuch & Projektbeschreibung lesen
- [x] Teamrollen festlegen und im Repo eintragen
- [ ] Repository anlegen / Zugriff sicherstellen
- [ ] Wöchentlichen Meetingtermin festlegen
- [ ] Kunde kontaktieren (Key Account Manager) → Planning Game Termin vereinbaren
- [ ] Lokale Odoo‑Instanz & DB einrichten
- [ ] TRMNL‑Docs sichten, API‑Zugang klären

## Issues & Ticketing
- Nutzt GitHub Issues
- Jede Story/Task hat Aufwandsschätzung (ideale Personentage) und Akzeptanzkriterien

## Lizenz
- TODO: Lizenz mit Kunde klären.
