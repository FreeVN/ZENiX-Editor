# Als het niet werkt

| Melding | Oorzaak | Oplossing |
|---|---|---|
| `Geen sleutel gevonden` | nergens een projectsleutel | `ZENIX_KEY` zetten, of `keys.txt` / `.secrets/project.key` aanmaken |
| `Kon het bestand niet ontsleutelen` | verkeerde sleutel of geen `.rbtproject` | juiste projectsleutel gebruiken; controleer de bestandsextensie |
| `Bestandsupload vereist de 'python-multipart'-dependency` | dependency ontbreekt bij een multipart-upload | `pip install -r app/web/requirements.txt`, of open via een pad |
| `[Errno 98] Address already in use` | poort 8800 is bezet | andere poort (`--port 8801`) of de service herstarten |
| `uvicorn ontbreekt` | dependencies niet geïnstalleerd | `python3 -m pip install -r app/web/requirements.txt` |
| `invalid_names` bij opslaan | een gewijzigde naam schendt de vendor-regels | de melding noemt het veld, de waarde en het teken |
| Lege tabel na openen | het project heeft geen elementen, of het verkeerde bestand | statusbalk controleren; opnieuw openen |
| Editor start niet of gedraagt zich vreemd in windowed mode | de exe heeft geen console; fouten zijn enkel in het logbestand zichtbaar | bekijk `%LOCALAPPDATA%\ZENiXEditor\editor.log` (zie hieronder) |

## Editor start niet (Windows-exe)

De Windows-exe is gebouwd met `--windowed`: er is geen consolevenster, dus
foutmeldingen verschijnen nergens op het scherm. De editor schrijft alle uitvoer
naar:

    %LOCALAPPDATA%\ZENiXEditor\editor.log

Bestaat `%LOCALAPPDATA%` niet of is de map niet beschrijfbaar, dan gebruikt de
editor `~/.ZENiXEditor/editor.log` en in het uiterste geval het
systeem-`null`-apparaat. Staat er niets in het logbestand, controleer dan of de
poort al bezet is (`--port 8801`) en of de RingBus Tool-installatie bereikbaar
is (of `RINGBUSTOOL_HOME`).

## Nog steeds niets?

Open het resultaat in de **Ringbus Tool**. Als die het bestand wél aanvaardt,
zit het probleem in de editor: bewaar het bestand en de melding, dan is het
reproduceerbaar.
