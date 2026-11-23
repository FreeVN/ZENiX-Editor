# app/lib — vendor-bibliotheek (niet in deze repo)

De RingBus Tool van Rf-Technologies levert `configuration-*.jar` en
`jaxb-api.jar`. Die bestanden zijn auteursrechtelijk beschermd: ze zitten **niet**
in deze repo en **niet** in de exe.

De app zoekt ze in deze volgorde:

1. `RINGBUSTOOL_HOME` → `<home>/ringbustool/modules/lib` (en `ext/`);
2. de standaardinstallatie van de RingBus Tool;
3. deze map (`app/lib/`) — enkel om lokaal te ontwikkelen: zet de jars hier neer.

`app/lib/*.jar` staat in `.gitignore`.
