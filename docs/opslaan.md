# Opslaan

Klik op **Opslaan**. De editor:

1. leest het bestand zoals het nu op schijf staat;
2. past **enkel de gewijzigde velden** toe;
3. leest het resultaat opnieuw in en vergelijkt het met wat je dacht op te slaan;
4. toont de staat zoals hij nu écht in het bestand staat.

Je krijgt daarna een downloadlink voor `<naam> - aangepast.rbtproject`.

## Het bronbestand blijft ongemoeid

De editor schrijft nooit naar het bestand dat je opende. Het origineel blijft
byte-voor-byte identiek — handig als referentie of als je iets wilt terugdraaien.

## Wat er geweigerd wordt

Een opslag wordt **geweigerd** (met een duidelijke melding) als:

- een **gewijzigde** naam de vendor-regels schendt, of dubbel is;
- je een ringhost leegmaakt;
- je een alarm aan een andere ring probeert te hangen.

Bestaande fouten in het bronbestand blokkeren niet: die blijven als
waarschuwing staan tot je ze zelf aanpast.

## Daarna

Open het nieuwe bestand in de **Ringbus Tool** en controleer het daar. De editor
is een snelle werkbank, niet de eindvalidator: pas de Ringbus Tool beslist of het
project geldig is en naar de ZENiX-controller mag.
