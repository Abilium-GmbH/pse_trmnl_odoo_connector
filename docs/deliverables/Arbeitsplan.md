# Arbeitsplan

Der Arbeitsplan wird im **GitHub Project  
[Odoo IoT für Digital Signage](https://github.com/users/KamiyeL/projects/2)** verwaltet.

Das GitHub Project dient als zentraler **Task- und Fortschrittstracker** für das Team.

Alle **Tasks, Verantwortlichkeiten, Deadlines und Status** werden direkt im GitHub Project geführt.  
Dieses Dokument beschreibt lediglich **die Struktur und den Workflow des Arbeitsplans**.

---

## Nutzung von GitHub Projects

Alle Aufgaben werden als **GitHub Issues** erfasst und im Project organisiert.

Das Project ist in mehrere Bereiche unterteilt:

**Current Iteration**  
Tasks, die im aktuellen Sprint bearbeitet werden.  
Über die Such- bzw. Filterleiste des Boards kann nach der jeweiligen **Iteration** gefiltert werden, sodass schnell sichtbar wird, welche Aufgaben zur aktuellen Iteration gehören.

**Next Iteration**  
Aufgaben, die bereits geplant sind, aber erst in der nächsten Iteration umgesetzt werden.

**Backlog**  
Enthält alle geplanten Tasks, die noch keiner Iteration zugeordnet sind.

**Roadmap**  
Langfristig geplante Aufgaben oder grössere Features, die im späteren Projektverlauf umgesetzt werden sollen.

**In Review**  
Tasks, für die bereits ein Pull Request erstellt wurde und die sich aktuell im Code Review befinden.

**My Items**  
Zeigt alle Issues und Tasks an, die einer bestimmten Person zugewiesen sind.


---

## Pflege des Arbeitsplans

- Aufgaben werden als **GitHub Issues** erstellt.
- Jedes Issue erhält eine **Aufwandsschätzung (Story Points / Estimate)**.
- Eine verantwortliche Person wird über **Issue Assignment** festgelegt.
- Die Zuordnung zu einer Iteration erfolgt während der **Team-Meetings (Iteration Planning)**.
- Tasks werden dabei aus dem **Backlog in die aktuelle Iteration übernommen**.
- Der Fortschritt eines Tasks wird über den **Status im Project Board** verfolgt.
- Das GitHub Project wird während der Iterationen **laufend aktualisiert**.

### Status im GitHub Project

Der Fortschritt eines Tasks wird über folgende Status abgebildet:

- **Backlog** — Aufgabe erfasst, noch nicht gestartet  
- **In progress** — Aufgabe wird aktuell bearbeitet  
- **In review** — Pull Request erstellt, Code Review läuft  
- **Done** — Task abgeschlossen und in `main` gemerged  

---

## Aufwandsschätzung

Der Aufwand für Tasks wird mit **Story Points** geschätzt.  
Story Points stellen eine **relative Schätzung von Aufwand und Komplexität** dar und berücksichtigen Implementierungsaufwand, technische Schwierigkeit sowie Unsicherheiten.

Zur Orientierung verwenden wir eine **Fibonacci-Skala**:

| Story Points | Bedeutung |
|---|---|
| 1 | sehr kleine Aufgabe (~15–60 Minuten) |
| 2 | kleine Aufgabe (~2–4 Stunden) |
| 3 | mittlere Aufgabe (~4–8 Stunden) |
| 5 | komplexe Aufgabe (~1–2 Tage) |
| 8+ | sehr komplex → sollte in kleinere Tasks aufgeteilt werden |

Die Schätzung erfolgt gemeinsam im Team während des **Iteration Planning**.


---

### Git-Workflow (inkl. Review & Tests)

0. **Repository einmalig klonen (neuer Rechner)**
    ```bash
    git clone <repository-url>
    cd <repository-name>
    ```
1. **Branch von `main` erstellen**
   ```bash
   git checkout main
   git pull
   git checkout -b feature/<issue-id>-kurze-beschreibung
    ```

2. **Änderungen prüfen**
   ```bash
   git status
    ```
3. **Gewünschte Änderungen stagen (git add . vermeiden)**
    ```bash
    git add path/to/file.py
    ```
4. **Committen**
   ```bash
    git commit -m "<ISSUE-ID>: kurze Nachricht"
    ```

5. **Push auf Remote**
    ```bash
    git push -u origin feature/<issue-id>-kurze-beschreibung
    ```

6. **Pull Request eröffnen**

    - Task im GitHub Project auf In review setzen

7. **Code Review**

    - Die implementierende Person wählt eine **Person für das Code Review** aus.

    - Der Pull Request wird entweder **approved** oder es wird **Feedback gegeben**, das anschließend eingearbeitet wird.

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
    ```
 