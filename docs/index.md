# ZENiX Ringbus Editor

!!! info "Versie"
    Deze handleiding hoort bij **ZENiX Ringbus Editor 1.1.1**. De bron staat in
    deze repo; de exe hangt aan de
    [releases-pagina](https://github.com/FreeVN/ZENiX-Editor/releases).

!!! tip "Downloaden"
    **Windows-exe**: [ZENiXEditor.exe](https://github.com/FreeVN/ZENiX-Editor/releases)
    — dubbelklikken, browser opent. De RingBus Tool moet geïnstalleerd zijn
    (vendor-bibliotheek); de rest zit in de exe. Zie [Installeren](installatie.md).

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

De editor bewerkt het project **rechtstreeks in de browser**. Wil je liever in
Excel werken, dan is **ZENiX Bridge** het juiste product: dat converteert
`.rbtproject` ⇄ Excel. Dat is een **aparte tool** met een eigen repo
(<https://github.com/FreeVN/ZENiX-Bridge>) en een eigen exe (`ZENiXBridge.exe`) —
zie de [Bridge-handleiding](https://freevn.github.io/ZENiX-Bridge/).

De editor schrijft enkel de gewijzigde velden terug; de rest van het project
blijft byte-voor-byte wat het was.
