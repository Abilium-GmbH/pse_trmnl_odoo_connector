# Meeting-Protokoll — 10.03.2026

**Datum:** 10.03.2026  
**Uhrzeit:** 10:15 - 11:15  
**Ort/Medium:** ExWi, vor dem B6

**Sitzungsleitung:** Leïla Ayinkamiye  
**Protokoll:** Timur Umut Turgul

## Teilnehmende
- Leïla Ayinkamiye
- Sascha Friedli
- Timur Umut Turgul

## Entschuldigt
- Claudio Berger

## Traktanden
1. Stories
2. Arbeitsplan
3. Arbeitsverteilung für Deliverables
4. Konventionen
5. Verbindung Odoo zu TRMNL

## 1. Stories
Der Kunde wollte bei unserem ersten Treffen vom Handbuch abweichend vorgehen. Daher liegen die Projekt-Requirements zurzeit nicht als Stories vor. Wir beschliessen, diese selbst in Stories zu überführen. Hierfür sind alle Teammitglieder zuständig.

## 2. Arbeitsplan
Im Repository war nicht klar, was wir als Arbeitsplan nutzen. Wir beschliessen, den Arbeitsplan mit Git-Issues und Git-Projects umzusetzen. Leïla übernimmt das Erstellen des hierfür nötigen Git-Projects. Timur passt das README.md entsprechend an.

## 3. Arbeitsverteilung für Deliverables
### Leïla:
- Erstellt das Testkonzept

### Sascha:
- Erstellt die Risikoanalyse
- Erstellt stellvertretend für Claudio den Statusbericht

### Timur:
- Lädt die compose.yaml-Datei und die weiteren dazugehörigen Daten hoch
- Schreibt eine Anleitung für die Nutzung der Datei

## 4. Konventionen
Wir haben folgende Konventionen für die Einheitlichkeit beschlossen:

- Git-Commit-Nachrichten werden auf Englisch verfasst
- Im Source-Code verwenden wir englische Bezeichnungen für Variablen und Funktionen
- Wir verwenden englische Bezeichnungen für Dateinamen im Repository
- Das README.md wird vorerst auf Deutsch gehalten. Eventuell werden wir es später auf Englisch übersetzen

## 5. Verbindung Odoo zu TRMNL
Wir beschliessen einen hybriden Ansatz zu verfolgen: Die Kommunikation soll primär über Webhooks erfolgen, während Polling als Fallback-Strategie dient. Da Polling einfacher zu implementieren ist, setzen wir zunächst diese Variante um und ergänzen Webhooks in späteren Iterationen.
