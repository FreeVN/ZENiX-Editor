# Een project openen

Er zijn twee manieren:

1. **Bestand kiezen** — klik op *Bestand kiezen* en selecteer een `.rbtproject`.
2. **Openen via pad** — typ een pad onder `samples/` en klik *Openen via pad*.

Na het openen zie je bovenaan de statusbalk: aantal elementen, zones en ringen,
en of er iets niet opgeslagen is.

## Wat je meteen ziet

- **Elementen** — één rij per element, met de vendor-naam, omschrijving, zone,
  ring, adres en unit-id.
- **Zones** en **Ringen** — aparte tabellen; wijzigingen daar werken meteen door
  in de elementenlijst.
- **Alarmen** en **Controlematrix** — enkel als het project alarmen heeft.

## Waarschuwingen

Bovenaan verschijnen gele waarschuwingen, bijvoorbeeld:

- *dubbel adres* — twee elementen staan op hetzelfde adres binnen een ring;
- *naam wijkt af van de vendor-conventie* — de naam volgt het patroon
  `di_<ring>_<unit>_<n>` niet.

Waarschuwingen **blokkeren het opslaan niet**. Ze zijn er om te zien wat de
Ringbus Tool straks ook zal melden.
