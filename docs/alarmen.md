# Alarmen en de controlematrix

Een project kan **alarmen** bevatten (rook, brand, …) en per element een
**controlematrix**: wat doet dat element als een bepaald alarm afgaat.

## Alarmen

De lijst toont per alarm het id, de ring, de naam en de omschrijving. Naam en
omschrijving zijn inline bewerkbaar. De volgorde en het aantal alarmen liggen
vast: **alarmen toevoegen of verwijderen doet de editor niet** — daarvoor is een
functie-expressie nodig, en dat blijft werk voor de Ringbus Tool.

## De matrix

De matrix heeft **een rij per element** en **een kolom per alarm**. Een cel bevat:

- `-1` — geen reactie (de standaardwaarde);
- `0` of hoger — de reactiewaarde die de installatie gebruikt.

De knop **Rij op -1** zet een hele rij terug op "geen reactie" — handig als je
een element uit de koppeling wilt halen.

!!! info "Lengte blijft kloppen"
    De matrix heeft altijd evenveel waarden als er alarmen zijn. Voegt iemand in
    de Ringbus Tool een alarm toe, dan vult de editor de ontbrekende waarden aan
    met `-1` in plaats van de matrix te laten verschuiven.
