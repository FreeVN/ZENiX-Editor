# ZENiX Ringbus Editor

!!! info "Versie"
    Deze handleiding hoort bij **ZENiX Ringbus Editor 1.0.0**. De code staat in de
    privé-repo `FreeVN/zenix-ringbus-tool`, tag `editor-v1.0.0`.

De Ringbus Editor is een **offline web-UI** voor ZENiX-projectbestanden
(`.rbtproject`, Rf-Technologies brandkleppen). Je opent een project in je browser
en bewerkt het in een tabel — geen installatie van de Ringbus Tool nodig om
honderd kleppen te hernoemen, zones toe te wijzen of adressen na te lopen.

## Wat kan er

- **Elementen** — naam, omschrijving, zone, ring, adres, unit-id, cpuType.
- **Zones** — aanmaken, hernoemen, verwijderen (volgorde automatisch).
- **Ringen** — naam, host, toevoegen; nieuwe ringen krijgen de vendor-defaults.
- **Alarmen** — naam en omschrijving bewerken.
- **Controlematrix** — per element en per alarm de waarde (`-1` = geen reactie).
- **Zoeken, ongedaan maken, herladen** — zonder de pagina te verversen.

## Wat het níet doet

- Het maakt of verwijdert **geen alarmen** (een alarm vereist een
  functie-expressie; dat blijft werk voor de Ringbus Tool).
- Het **deployt niets** naar de ZENiX-controller. De Ringbus Tool van
  Rf-Technologies blijft de eindvalidator: open het resultaat daar en laad het
  pas daarna in de installatie.
- Het **wijzigt het bronbestand nooit**. Je krijgt altijd een nieuw bestand.

## Ringbus Editor of Bridge?

| | ZENiX Ringbus Editor | ZENiX Bridge |
|---|---|---|
| Vorm | web-UI (Python-service) | desktop-app, CLI, Docker |
| Bewerken in | de browser, in een tabel | Excel of Google Sheets |
| Groot project (1000+ elementen) | vlot, met zoeken en filter | vlot, met de vertrouwde spreadsheet |
| Bestand | `python3 app/web/server.py` | [handleiding](https://freevn.github.io/ZENiX-Bridge/) |

Beide schrijven enkel de gewijzigde velden terug; de rest van het project blijft
byte-voor-byte wat het was.
