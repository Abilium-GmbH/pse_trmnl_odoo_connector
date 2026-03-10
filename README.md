# PSE-FS2026

## Projektname
PSE – Odoo IoT für Digital Signage

## Kurzbeschreibung
Ziel: Entwicklung eines Odoo‑Moduls zur Verwaltung von TRMNL e‑Ink Displays und einer Anbindung an TRMNL, sodass verschiedene Daten aus Odoo (z.B. Kalender, Produktinformationen, Preisschilder, Raumbelegung) dynamisch auf den Displays dargestellt werden können.

## Repository-Struktur
- /addons
  - /trmnl
- /docs
  - /client_meetings
  - /deliverables
    - /risk_analysis
    - /status_report
  - /presentations
  - /team_meetings
- /tests
- README.md

## Erste Schritte (Setup)
### Vorbedingungen
Vorausgesetzt sind Docker und Docker Compose. Hilfe bei der Installation findet sich unter: https://docs.docker.com/get-started/get-docker/
#### 1. Repository klonen
##### `git clone https://github.com/KamiyeL/PSE.git` (HTTP)
oder
##### `git clone git@github.com:KamiyeL/PSE.git`  (SSH)
#### 2. PostgreSQL starten
##### `docker compose up -d db`
#### 3. Initialisieren der Datenbank
##### `docker compose run --rm odoo odoo -i base --stop-after-init` 
#### 4. Odoo starten 
##### `docker compose up -d odoo`
#### 5. Odoo Login
Odoo ist nun über einen beliebigen Webbrowser unter folgender Adresse erreichbar:
##### `http://localhost:8069`
Ferner ist auch ein Login direkt im Debug-Modus möglich unter:
##### `http://localhost:8069/odoo/apps?debug=1`
Beim Login fragt Odoo nach E-Mail und Passwort. Beide sind standartmässig auf `admin` gesetzt.
### Weitere Hinweise
#### Folgenutzung
Die Dienste können beendet werden mit:
##### `docker compose down`
Nach dem erstmaligen Setup können die Dienste einfach mit folgendem Befehl gestartet werden:
##### `docker compose up -d`
#### Distro-spezifische Sonderheiten
An dieser Stelle sei darauf hingewiesen, dass einzelne Linux-Distros aufgrund ihrer Eigenheiten ein anderes Vorgehen oder die Nutzung anderer Werkzeuge empfehlen können. Insbesondere können Sicherheitsmodule zu Komplikationen führen. So rät beispielsweise Fedora zur Nutzung von Podman anstatt Docker direkt zu verwenden. Es empfiehlt sich, die Dokumentation der jeweiligen Distribution zu konsultieren.

## Development Team
- Timur Umut Turgul — Key Account Manager (Kundenkontakt)
- Sascha Friedli — Chief Deliverable Officer (Deliverables / Termine)
- Leïla Ayinkamiye — Quality Evangelist (Testkonzept, Tests)
- Claudio Berger — Master Tracker (Statusreports, Tracking)