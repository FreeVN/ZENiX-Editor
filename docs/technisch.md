# Hoe het werkt

De editor is een dunne laag bovenop dezelfde gereedschappen als ZENiX Bridge.

```text
browser  ──HTTP──▶  FastAPI (app/web/server.py)
                        │
                        ├─ editor.py      sessies, validatie, diff, twee-pass opslaan
                        ├─ model_service  lezen/schrijven van een .rbtproject
                        └─ Java-helper    ZenixTool dump/apply (vendor-klassen)
                                            │
                                            ▼
                                     .rbtproject (AES-256-GCM + zip + Java-serialized Configuration)
```

## Dump en apply

- **Dump** — de Java-helper leest de `Configuration` en geeft JSON: elementen met
  een **stabiele id** (de index in de vendor-lijst), ringen, zones, alarmen en de
  controlematrix.
- **Apply** — de helper past een lijst operaties toe (`@add`, `@del`, `@rename`,
  `@order`, `@zonedel`, `@ringadd`, `@ringset`, `@alarmrename`, `@alarmdesc`,
  `@alarmvalue`, …), hernummert de indexen en schrijft het bestand.

Volgorde is geen detail: zones → toevoegen → veldedits → hernoemen → verwijderen
→ volgorde → hernummeren. Anders verschuiven ids tijdens het toepassen.

## Twee-pass opslaan

Bij het opslaan past de editor de wijzigingen toe tegen de **huidige** staat van
het bestand, leest het resultaat opnieuw en vergelijkt veld per veld. Zo komt een
stille afwijking (een veld dat de vendor normaliseert, bijvoorbeeld een lege
ringhost naar `localhost`) meteen boven.

## Beveiliging

- Het bronbestand wordt nooit beschreven; de uitvoer gaat naar een nieuw bestand
  via een tijdelijk bestand + atomaire rename.
- Symlinks of hardlinks naar het bronbestand worden geweigerd.
- De projectsleutel komt uit de omgeving of een lokaal bestand en komt nooit in
  een log of in de browser terecht.
