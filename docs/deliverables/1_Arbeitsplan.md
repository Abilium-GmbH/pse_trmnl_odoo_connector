## Arbeitsplan

Basierend auf der Detailplanung der Stories (siehe Abschnitt 2.1 im PSE Handbuch) führt jede Gruppe einen **laufend aktualisierten Arbeitsplan** und macht diesen im Repository verfügbar.

Im Arbeitsplan werden **alle Tasks** mit **Verantwortlichkeiten** und **Abhängigkeiten** dargestellt. Dazu gehören nicht nur Programmieraufgaben, sondern auch: Planung, Design, Know-how-Aufbau, Testen, Dokumentation sowie Präsentationen (Vorbereitung & Durchführung).

### Format (Vorschlag)

Der Arbeitsplan wird als Tabelle geführt (z. B. in `docs/1_Arbeitsplan.md`).

| ID  | Task                       | Verantwortlich | Deadline   | Aufwand (PT) | Abhängigkeiten | Status       |
|-----|----------------------------|----------------|------------|--------------|----------------|--------------|
| T1  | Repo & Umgebung einrichten | Claudio        | 2026-02-21 | 1.0          | -              | done         |
| T2  | Odoo Modul Skeleton        | Timur          | 2026-02-24 | 2.0          | T1             | in progress  |

### Pflegehinweis

- Tasks werden als **GitHub Issues** erfasst (Projekt: **Odoo IoT für Digital Signage**).
- In `docs/1_Arbeitsplan.md` werden die Tasks als Tabelle geführt und (falls vorhanden) mit **Issue-Link** referenziert.
- Der **Master Tracker** aktualisiert diese Datei **mindestens wöchentlich**.
- Bei Verzögerungen: **Ursache kurz dokumentieren** und **neue Deadline setzen**.

---

### Git / Workflow

#### Status im GitHub Project
Jeder Task/Issue wird im GitHub Project geführt und hat genau einen Status:
- **Backlog** — erfasst, noch nicht gestartet
- **In progress** — in Bearbeitung
- **In review** — Pull Request offen, Review läuft
- **Done** — gemerged und abgeschlossen

#### Issue- & Task-Handling
- Jede Story/Task erhält eine **ID** (GitHub Issue-Nummer oder internes Schema wie `T1`, `STORY-12`).
- Referenzen werden im Arbeitsplan konsistent geführt (z. B. `#123` für GitHub Issue).

#### Vorgehen (Scrum)
- Jede Iteration entspricht einem **Sprint**.
- Im **Planning Game** mit dem Kunden werden Stories/Tasks priorisiert und vom Team geschätzt.
- Schätzung erfolgt in **Fibonacci-Story-Points** (Komplexität/Aufwand/Unsicherheit). Richtwerte:
  - **1 Punkt:** sehr klein (~15–60 Minuten)
  - **2 Punkte:** klein–mittel (~2–4 Stunden)
  - **3 Punkte:** mittel (~4–8 Stunden)
  - **5 Punkte:** gross/komplex (~8–16 Stunden)
  - **8+ Punkte:** sehr komplex/risikobehaftet → **muss** in kleinere Tasks zerlegt werden
- Kurze **wöchentliche Abstimmung** im Team (Blocker, Prioritäten, wer woran arbeitet).
- **Review/Demo** am Iterationsende.

#### Git-Workflow (inkl. Review & Tests)
1. **Branch von `main` erstellen**
   ```bash
   git checkout main
   git pull
   git checkout -b feature/<issue-id>-kurze-beschreibung
2. **Änderungen prüfen**
   ```bash
   git status
3. **Gewünschte Änderungen stagen (git add . vermeiden)**
       ```bash
     git add path/to/file.py 
4. **Committen**
   ```bash
    git commit -m "<ISSUE-ID>: kurze Nachricht"
5. **Push auf Remote**
    ```bash
    git push -u origin feature/<issue-id>-kurze-beschreibung

6. **Pull Request eröffnen**

    - Issue verlinken (z. B. Closes #123)

    - Task im GitHub Project auf In review setzen

7. **Code Review**

    - Implementierende Person wählt einen **Code Reviewer*in** aus.

    - Reviewer gibt Approve oder Feedback/Changes requested.

    - Feedback wird eingearbeitet (weitere Commits im selben Branch).

8. **Tests**

    - Falls Tests vorhanden: lokal und/oder via CI laufen lassen.

    - Vor Merge müssen alle relevanten Checks grün sein (z. B. pytest).

9. **Merge in main**

    - Nach Approval + grüner CI wird der PR gemerged (gemäss Repo-Policy).

    - Task/Issue im GitHub Project auf Done setzen.

10. **Nach Merge**
   ```bash
git checkout main
git pull