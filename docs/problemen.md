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

## Nog steeds niets?

Open het resultaat in de **Ringbus Tool**. Als die het bestand wél aanvaardt,
zit het probleem in de editor: bewaar het bestand en de melding, dan is het
reproduceerbaar.
