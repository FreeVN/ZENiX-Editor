# Namen

De editor gebruikt **dezelfde regels als de Ringbus Tool**, niet een eigen
variant. Anders zou je een bestand opslaan dat de vendor-tool daarna weigert.

## Verboden tekens

Element-, ring-, zone- en alarmnamen mogen deze tekens niet bevatten:

```text
( ) . , ! | & <spatie> <CR> <LF> <TAB> < > ? * - + / \ = " % $ # : ; ^ ' [ ] { }
```

Ook de vijf streepvarianten `‐ ‑ – — ―` zijn verboden. `_` en letters/cijfers
mogen wel.

!!! note "Zones zijn de uitzondering"
    Alleen **zonenamen** mogen een spatie bevatten. Dat is een afwijking in de
    vendor-tool zelf, en de editor volgt die.

Spaties aan het begin of einde worden **niet** stilletjes weggeknipt: je krijgt
een foutmelding met het teken erbij. Zo zie je meteen wat er mis is.

## Uniek, over alle soorten heen

Elementen, hulpelementen en alarmen delen **één** namenlijst. Ringnamen mogen
daar niet mee botsen. Twee elementen met dezelfde naam kan dus niet, en een ring
die hetzelfde heet als een element ook niet.

## Gereserveerd

`bae_1` … `bae_1024` en `open_1` … `open_1024` zijn voorbehouden door de
vendor-tool. Die namen worden geweigerd.

## Foutmeldingen

| Melding | Betekenis |
|---|---|
| `EMPTY` | de naam is leeg |
| `INVALID_CHAR` | er staat een verboden teken in (het teken staat in de melding) |
| `TAKEN_NAME` | de naam bestaat al, of botst met een ring/hulpelement |

Een **bestaande** fout in een bronbestand blokkeert het opslaan niet: je krijgt
een waarschuwing en kan het project gewoon opslaan. Pas wanneer je dat veld zelf
aanpast, geldt de harde controle.
