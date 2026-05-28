# PSE-FS2026: Odoo IoT für Digital Signage

## Kurzbeschreibung
Ziel: Entwicklung eines Odoo‑Moduls zur Verwaltung von TRMNL e‑Ink Displays und einer Anbindung an TRMNL, sodass verschiedene Daten aus Odoo (z.B. Kalender, Produktinformationen, Preisschilder, Raumbelegung) dynamisch auf den Displays dargestellt werden können.

## Repository-Struktur
```
.
├── addons/
│   └── trmnl/
│       ├── data/
│       ├── models/
│       │   └── providers/
│       ├── security/
│       └── views/
├── data/
├── compose.yaml
├── Dockerfile
├── LICENSE
├── README.md
└── requirements.txt
```


## Erste Schritte (Setup PostgreSQL & Odoo)
### Vorbedingungen
Vorausgesetzt sind Docker und Docker Compose. Hilfe bei der Installation findet sich unter: https://docs.docker.com/get-started/get-docker/  

---
### 1. Repository klonen
HTTP:
```
git clone https://github.com/Abilium-GmbH/pse_trmnl_odoo_connector.git
```
oder SSH:
```
git clone git@github.com:Abilium-GmbH/pse_trmnl_odoo_connector.git
```
Hinweis: Die folgenden Docker-Compose-Befehle müssen im Root-Verzeichnis des geklonten Repositorys ausgeführt werden, in dem sich die Datei compose.yaml befindet.
### 2. PostgreSQL starten
```
docker compose up -d db
```
### 3. Initialisieren der Datenbank
```
docker compose run --rm odoo odoo -d odoo -i base --stop-after-init
```
### 4. Odoo starten 
```
docker compose up -d odoo
```
### 5. Odoo Login
Odoo ist nun über einen beliebigen Webbrowser unter folgender Adresse erreichbar:
```
http://localhost:8069
```
Ferner ist auch ein Login direkt im Debug-Modus möglich unter:
```
http://localhost:8069/odoo/apps?debug=1
```
Beim Login fragt Odoo nach E-Mail und Passwort. Beide sind standartmässig auf `admin` gesetzt.  

---
## TRMNL Display mit Odoo verbinden
Nach dem erfolgreichen Setup kann ein **TRMNL Display** mit Odoo verbunden und über das Odoo-Backend mit Inhalten gesteuert werden.
### Voraussetzung
- Odoo läuft lokal über Docker

- Das Modul TRMNL ist installiert

- Ein TRMNL Gerät ist eingerichtet

- Im TRMNL Dashboard wurde das Plugin Webhook Image (Experimental) erstellt

### 1. TRMNL Webhook URL erstellen
- 1. Im TRMNL Dashboard anmelden
- 2. Plugin Webhook Image (Experimental) öffnen
- 3. Neue Plugin-Instanz erstellen
- 4. Einen Namen vergeben, z. B Odoo Display
- 5. Plugin speichern
Beispiel:
```
https://trmnl.com/api/plugin_settings/<id>/image
```
Diese URL wird später in Odoo eingetragen.

---
### 2. TRMNL Modul in Odoo installieren
- 1. Odoo öffnen

- 2. Zu Apps wechseln

- 3. Nach TRMNL suchen

- 4. Modul installieren

Danach erscheint im Menü ein neuer Bereich:
```
TRMNL → Devices
```

### 3. TRMNL Device in Odoo anlegen
- 1. In Odoo öffnen:

```
TRMNL → Devices
```

- 2. Neues Device erstellen

Folgende Felder ausfüllen:

```
Display Name
Device ID
Webhook URL
Content Type
```
Beispiel:

```
Display Name: Office Display
Device ID: 123
Webhook URL: https://trmnl.com/api/plugin_settings/.../image
Content Type: Custom Message
 ```
### 4. Custom Message konfigurieren
Um eine eigene Nachricht anzuzeigen:

- 1. Content Type auswählen:

```
Custom Message
```

- 2. Feld Custom Message ausfüllen, z. B.

```
Willkommen bei Abilium
```

- 3. Änderungen speichern

### 5. Inhalt an TRMNL senden
- 1. Im Device-Formular auf

```
Send to TRMNL
```

klicken.

- 2. Anschließend den Button auf der Rückseite des TRMNL Displays drücken, damit das Gerät den neuen Inhalt lädt.

### 6. Erwartetes Ergebnis
Das TRMNL Display zeigt nun die Nachricht aus Odoo.

Beispiel:

```
Office Display
--------------
Willkommen bei Abilium
```

### Weitere Hinweise
#### Folgenutzung
Die Dienste können beendet werden mit:
```
docker compose down
```
Nach dem erstmaligen Setup können die Dienste einfach mit folgendem Befehl gestartet werden:
```
docker compose up -d
```
#### Umgebungsvariablen (Secrets)
Das `compose.yaml` verwendet eine `.env`-Datei zur Konfiguration von Umgebungsvariablen. Wenn keine `.env`-Datei vorhanden ist, greifen automatisch die im `compose.yaml` definierten Standardwerte.  

Um eigene Secrets oder Konfigurationswerte zu verwenden:

1. `.env.example` zu `.env` kopieren:
   ```
   cp .env.example .env
   ```
2. Die gewünschten Werte in der `.env`-Datei anpassen
#### Distro-spezifische Sonderheiten
An dieser Stelle sei darauf hingewiesen, dass einzelne Linux-Distros aufgrund ihrer Eigenheiten ein anderes Vorgehen oder die Nutzung anderer Werkzeuge empfehlen können. Insbesondere können Sicherheitsmodule zu Komplikationen führen. So rät beispielsweise Fedora zur Nutzung von Podman anstatt Docker direkt zu verwenden. Es empfiehlt sich, die Dokumentation der jeweiligen Distribution zu konsultieren.



## Development Team
- Timur Umut Turgul — Key Account Manager (Kundenkontakt)
- Sascha Friedli — Chief Deliverable Officer (Deliverables / Termine)
- Leïla Ayinkamiye — Quality Evangelist (Testkonzept, Tests)
- Claudio Berger — Master Tracker (Statusreports, Tracking)
