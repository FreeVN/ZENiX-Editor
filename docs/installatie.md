# Installeren

De editor is een Python-service. Er is geen build-stap en geen internetverbinding
nodig tijdens het gebruik: alle bestanden (HTML, CSS, JS) zitten in de repo.

## Op Windows (exe) — aanbevolen

Download `ZENiXEditor.exe` uit de
[release](https://github.com/FreeVN/ZENiX-Editor/releases) en dubbelklik erop.
De editor start en opent je browser op <http://127.0.0.1:8800/>. Stoppen met
Ctrl+C of door het venster te sluiten.

- Geen installatie, geen Java op je systeem: de JRE zit in de exe.
- **De RingBus Tool moet geïnstalleerd zijn.** De vendor-bibliotheek
  (`configuration-*.jar`) zit niet in de exe en wordt bij het starten uit die
  installatie geladen. Staat de RingBus Tool ergens anders, zet dan
  `RINGBUSTOOL_HOME` naar die map.
- Je projectsleutel hoort in `keys.txt` naast de exe.
- Opties: `--port`, `--host`, `--no-browser`, `--selftest`.

## Op een Linux-toestel

```bash
git clone https://github.com/FreeVN/ZENiX-Editor.git
cd ZENiX-Editor
python3 -m pip install -r app/web/requirements.txt
python3 app/web/server.py --port 8800
```

Open <http://localhost:8800>.

## Vanaf een ander toestel in het netwerk

Standaard luistert de server enkel op `127.0.0.1`. Gebruik `--host 0.0.0.0` om
hem vanaf je laptop of tablet te openen:

```bash
python3 app/web/server.py --host 0.0.0.0 --port 8800
```

Open dan `http://<ip-van-de-server>:8800`.

!!! warning "Geen authenticatie"
    De editor heeft **geen login**. Zet hem alleen op een vertrouwd netwerk, of
    achter een reverse proxy met authenticatie. Iedereen die de poort bereikt,
    kan projecten openen en opslaan.

## Als systeemservice (systemd)

`/etc/systemd/system/zenix-editor.service`:

```ini
[Unit]
Description=ZENiX Ringbus Editor (lokale web-UI voor .rbtproject)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/zenix-editor
Environment=PYTHONPATH=/opt/zenix-editor/app
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 /opt/zenix-editor/app/web/server.py --host 0.0.0.0 --port 8800
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now zenix-editor
systemctl status zenix-editor
```

## De projectsleutel

Een `.rbtproject` is versleuteld (AES-256-GCM). De editor heeft de projectsleutel
nodig en zoekt die in deze volgorde:

1. de omgevingsvariabele `ZENIX_KEY` (hex, 32 bytes);
2. `keys.txt` naast de repo-root;
3. `.secrets/project.key` in de repo.

Zonder sleutel krijg je bij het openen een duidelijke foutmelding — de editor
raadt niets en probeert geen dongle.
