# Protokoll – Kundenmeeting  
**Datum:** 03.03.2026  
**Projekt:** Odoo IoT – Digital Signage  
**Kunde:** Abilium GmbH  

---

## 1. Ziel des Projekts

Entwicklung eines Odoo-Moduls zur:

- Verwaltung von Digital-Signage-Geräten (TRMNL)
- Anzeige von Odoo-Daten auf einem e-Ink-Display
- Einfachen Verbindung zwischen Odoo und dem Gerät

---

## 2. Technische Rahmenbedingungen

### Odoo

- Entwicklung im **Odoo Framework (Python)**
- IDE:  
  - Cursor (AI IDE)  
  - Visual Studio Code mit Odoo-Extension
- Bei AI-Prompts immer angeben:
  - Odoo Version (z. B. v19)
  - Enterprise oder Community Edition
- Terminal ist grundsätzlich identisch

### Modulstruktur (Odoo)

Jedes Custom Modul besteht aus:

- `__init__.py`
- `__manifest__.py`
- `models/` → Datenbanktabellen
- `views/` → XML-Views
- `controllers/` → Schnittstelle nach außen (API)
- optional: `security/`, `data/`, etc.

Addons-Ordner enthält alle Custom-Module.

---

## 3. Systemarchitektur

### Grundidee

- Odoo definiert, **was auf dem Display angezeigt wird**
- Modularer Aufbau (z. B. Kalender-Modul als Datenquelle)
- Modul möglichst generisch und Open-Source-fähig halten

### Containerisierung

- Docker Compose Setup erstellen
- Zwei Container:
  - Odoo
  - Datenbank (PostgreSQL)
- Container kommunizieren miteinander
- Odoo-Image von Docker Hub verwenden
- Anleitung für Dockerfile prüfen

### Lokales Setup

- Odoo Version 19 klonen
- In VS Code als Workspace einbinden
- Addons-Folder korrekt verlinken

---

## 4. Kernfragen aus dem Meeting

### Geräteanbindung

- Wie wird das Gerät identifiziert?
- Wie verbindet sich das Gerät mit Odoo?
- Wie wird es im System dargestellt?
- Webhooks?
- REST-Endpoint definieren?
- Wie findet das Gerät den Endpoint?

### Geräteverwaltung

- Zentrale Liste aller verbundenen Geräte
- Verwaltung an einem Ort
- Debug-Modus nötig, um App zu laden?

---

## 5. Anforderungen (erste Einschätzung)

### Priorität 1 – Höchstes Risiko

- Verbindung zwischen Odoo und Gerät herstellen
- Endpoint definieren
- Geräteidentifikation klären

→ Das soll als erstes umgesetzt werden.

### Weitere Anforderungen

- Einfache Einrichtung für Kunden
  - z. B. QR-Code scannen zur Registrierung
- Zentrale Geräteübersicht
- Definieren, was auf dem Display angezeigt wird
- Daten aus verschiedenen Odoo-Modulen nutzbar machen
- App oder Core-Feature? (Architekturentscheidung)

---

## 6. Architekturüberlegungen

- Odoo-Modul als eigenständige App
- Eine zentrale Datenquelle
- Zugriff von anderen Modulen auf Display-Daten
- Generisches, wiederverwendbares Modul
- Trennung:
  - Backend-Logik (Model)
  - API/Controller
  - View-Konfiguration

---

## 7. Nächste Schritte

- Docker Compose Setup erstellen
- Odoo lokal starten
- Minimalen Endpoint implementieren
- Test-Verbindung mit Gerät herstellen
- Requirements kategorisieren (Risikoanalyse)

---

## 8. Nächster Termin

**16.03.2026 – 09:00 bis 10:00 Uhr**

---

## 9. Offene Punkte

- Eigene Datenbank oder bestehende Odoo DB verwenden?
- Gibt es Code-Vorgaben (Formatierung / Struktur)?
- Exakte Odoo-Version bestätigen (v19?)
- Enterprise oder Community Edition?

---