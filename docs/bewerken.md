# Bewerken

## Elementen

Klik in een cel en typ. De wijziging wordt meteen in het geheugen bijgehouden;
pas bij *Opslaan* gaat er iets naar een bestand.

- **Naam** — volgt de vendor-regels, zie [Namen](namen.md).
- **Zone** — kies uit de bestaande zones of laat leeg.
- **Adres / unit-id** — de Ringbus Tool leidt `indexInRing` af uit de volgorde;
  de editor toont die afgeleide waarde maar laat je ze niet rechtstreeks zetten.
- **cpuType** — van de ring geërfd; enkel te wijzigen bij de ring.

## Volgorde en bulk

- **Drag & drop** binnen een ring herschikt de elementen; de Ringbus Tool
  hernummert daarna automatisch.
- **Bulk hernoemen** kan met het zoekveld om de selectie te beperken.

## Zones en ringen

- **Zone toevoegen/verwijderen** — de volgorde wordt automatisch hernummerd.
- **Ring hernoemen of een host wijzigen** — de host mag niet leeg zijn; een lege
  host geeft een foutmelding in plaats van een half opgeslagen ring.
- **Ring toevoegen** — krijgt de vendor-defaults (cpuType 5) en een lege host die
  je zelf invult.

## Ongedaan maken

`Ctrl+Z` / `Ctrl+Y` (of de knoppen) werken op de volledige werkkopie in de
browser. Na *Opslaan* blijft de geschiedenis staan: je kan verder werken en
opnieuw opslaan; elke opslag vertrekt van het bestand zoals het op schijf staat.
