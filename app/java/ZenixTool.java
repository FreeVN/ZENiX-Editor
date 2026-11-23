import com.euroicc.ringbus.config.Configuration;
import com.euroicc.ringbus.config.Element;
import com.euroicc.ringbus.config.Ring;
import com.euroicc.ringbus.config.Zone;
import com.euroicc.ringbus.config.Alarm;
import com.euroicc.ringbus.config.AlarmValuePair;
import com.euroicc.ringbus.config.Gateway;
import com.euroicc.ringbus.config.types.DeviceTypes;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

/**
 * ZENiX offline project tool.
 *
 *   dump  <project.rbtproject> <out.json> <keyfile>
 *   apply <project.rbtproject> <edits.tsv> <out.rbtproject> <keyfile>
 *
 * .rbtproject = AES-256-GCM(zip) ; key = IV = 32 bytes (hex in keyfile).
 * Inside the zip: <name>.rbproject (Java-serialized Configuration) + project.properties + fb/.
 */
public class ZenixTool {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) { usage(); System.exit(2); }
        String cmd = args[0];
        if ("dump".equals(cmd)) {
            File cfg = new File(args[1]);
            Configuration c = Configuration.load(cfg);
            if (c == null) throw new IllegalStateException("Configuration.load gaf null");
            Files.write(Paths.get(args[2]), dump(c, projectName(cfg)).getBytes(StandardCharsets.UTF_8));
            System.out.println("OK dump -> " + args[2] + " elements=" + c.getElements().size()
                    + " rings=" + c.getRings().size() + " zones=" + c.getZones().size());
        } else if ("apply".equals(cmd)) {
            File cfg = new File(args[1]);
            Configuration c = Configuration.load(cfg);
            if (c == null) throw new IllegalStateException("Configuration.load gaf null");
            int changes = applyEdits(c, Paths.get(args[2]));
            if (!c.saveAs(cfg)) throw new IllegalStateException("saveAs mislukt");
            System.out.println("OK apply changes=" + changes + " -> " + cfg.getAbsolutePath());
        } else usage();
    }

    static void usage() {
        System.err.println("dump  <file.rbproject> <out.json>");
        System.err.println("apply <file.rbproject> <edits.tsv>      (schrijft hetzelfde bestand terug)");
    }

    // ---------- crypto ----------
    static byte[] readKey(String f) throws IOException {
        String s = new String(Files.readAllBytes(Paths.get(f)), StandardCharsets.US_ASCII).trim().replaceAll("\\s", "");
        if (s.startsWith("KEY=")) s = s.substring(4);
        if (s.length() != 64) throw new IllegalArgumentException("keyfile moet 64 hex-tekens zijn");
        return hexToBytes(s);
    }

    static byte[] decrypt(byte[] data, byte[] key) throws Exception {
        Cipher ci = Cipher.getInstance("AES/GCM/NoPadding");
        ci.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, key));
        return ci.doFinal(data);
    }

    static byte[] encrypt(byte[] data, byte[] key) throws Exception {
        Cipher ci = Cipher.getInstance("AES/GCM/NoPadding");
        ci.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, key));
        return ci.doFinal(data);
    }

    // ---------- zip ----------
    static Path unpack(byte[] zip) throws IOException {
        Path dir = Files.createTempDirectory("zenix");
        try (ZipInputStream zis = new ZipInputStream(new ByteArrayInputStream(zip))) {
            ZipEntry e;
            while ((e = zis.getNextEntry()) != null) {
                Path out = dir.resolve(e.getName()).normalize();
                if (!out.startsWith(dir)) throw new IOException("zip-slip: " + e.getName());
                if (e.isDirectory()) { Files.createDirectories(out); continue; }
                Files.createDirectories(out.getParent());
                Files.copy(zis, out, StandardCopyOption.REPLACE_EXISTING);
            }
        }
        return dir;
    }

    static byte[] repack(Path dir) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        List<Path> files = new ArrayList<>();
        Files.walk(dir).filter(Files::isRegularFile).forEach(files::add);
        Collections.sort(files);
        try (ZipOutputStream zos = new ZipOutputStream(bos)) {
            for (Path p : files) {
                String rel = dir.relativize(p).toString().replace('\\', '/');
                zos.putNextEntry(new ZipEntry(rel));
                zos.write(Files.readAllBytes(p));
                zos.closeEntry();
            }
        }
        return bos.toByteArray();
    }

    static File findConfig(Path dir) throws IOException {
        List<Path> hits = new ArrayList<>();
        Files.walk(dir).filter(p -> p.toString().toLowerCase().endsWith(".rbproject")).forEach(hits::add);
        if (hits.size() != 1) throw new IOException("verwachtte 1 .rbproject, vond " + hits.size());
        return hits.get(0).toFile();
    }

    static String projectName(File cfg) {
        Properties p = new Properties();
        try (InputStream in = Files.newInputStream(cfg.toPath().resolveSibling("project.properties"))) { p.load(in); }
        catch (Exception ignored) {}
        if (p.getProperty("name") != null) return p.getProperty("name");
        String n = cfg.getName();
        return n.endsWith(".rbproject") ? n.substring(0, n.length() - 10) : n;
    }

    // ---------- dump ----------
    static String dump(Configuration c, String projectName) {
        StringBuilder o = new StringBuilder();
        o.append("{\n  \"project\": ").append(q(projectName)).append(",\n");
        o.append("  \"rings\": [");
        List<Ring> rings = c.getRings();
        for (int i = 0; i < rings.size(); i++) {
            Ring r = rings.get(i);
            if (i > 0) o.append(",");
            o.append("\n    {");
            o.append("\"id\": ").append(r.getId());
            o.append(", \"name\": ").append(q(r.getName()));
            o.append(", \"host\": ").append(q(r.getHost()));
            o.append(", \"cpuType\": ").append(r.getCpuType());
            o.append(", \"bacnetInstanceId\": ").append(r.getInstanceId());
            o.append(", \"bacnetNetwork\": ").append(r.getNetworkNumber());
            o.append("}");
        }
        o.append("\n  ],\n  \"zones\": [");
        List<Zone> zones = c.getZones();
        for (int i = 0; i < zones.size(); i++) {
            Zone z = zones.get(i);
            if (i > 0) o.append(",");
            o.append("\n    {");
            o.append("\"id\": ").append(z.getId());
            o.append(", \"name\": ").append(q(z.getName()));
            o.append(", \"description\": ").append(q(z.getDescription()));
            o.append(", \"order\": ").append(z.getOrder() == null ? 0 : z.getOrder());
            o.append(", \"elements\": [");
            List<Element> zels = z.getElements();
            if (zels != null) for (int k = 0; k < zels.size(); k++) { if (k > 0) o.append(","); o.append(q(zels.get(k).getName())); }
            o.append("]}");
        }
        o.append("\n  ],\n  \"gateways\": [");
        List<Gateway> gws = c.getGateways();
        for (int i = 0; i < gws.size(); i++) {
            Gateway g = gws.get(i);
            if (i > 0) o.append(",");
            o.append("\n    {\"name\": ").append(q(g.getName()))
             .append(", \"ip\": ").append(q(g.getIP()))
             .append(", \"instanceId\": ").append(g.getInstanceId())
             .append(", \"description\": ").append(q(g.getDescription())).append("}");
        }
        o.append("\n  ],\n  \"alarms\": [");
        List<Alarm> alarms = c.getAlarms();
        if (alarms == null) alarms = new ArrayList<>();
        for (int i = 0; i < alarms.size(); i++) {
            Alarm a = alarms.get(i);
            if (i > 0) o.append(",");
            o.append("\n    {");
            // stabiele alarm-id = index in Configuration.getAlarms()
            o.append("\"id\": ").append(i);
            o.append(", \"name\": ").append(q(a.getName()));
            o.append(", \"description\": ").append(q(a.getDescription()));
            o.append(", \"ringId\": ").append(a.getRing() == null ? -1 : a.getRing().getId());
            o.append("}");
        }
        o.append("\n  ],\n  \"elements\": [");
        Map<String, List<Integer>> zoneMap = new HashMap<>();
        for (Zone z : zones) {
            List<Element> zels = z.getElements();
            if (zels == null) continue;
            for (Element ze : zels) zoneMap.computeIfAbsent(ze.getName(), k -> new ArrayList<>()).add(z.getId());
        }
        List<Element> els = c.getElements();
        for (int i = 0; i < els.size(); i++) {
            Element e = els.get(i);
            if (i > 0) o.append(",");
            o.append("\n    {");
            // stabiele id = positie in Configuration.getElements() (0-based)
            o.append("\"id\": ").append(i);
            o.append(", \"name\": ").append(q(e.getName()));
            o.append(", \"ringId\": ").append(e.getRingId());
            o.append(", \"ring\": ").append(q(e.getRing() == null ? "" : e.getRing().getName()));
            o.append(", \"unit\": ").append(e.getUnit());
            o.append(", \"unitId\": ").append(q(e.getUnitId()));
            o.append(", \"address\": ").append(e.getAddress());
            o.append(", \"addressOnUnit\": ").append(e.getAddressOnUnit());
            o.append(", \"indexInRing\": ").append(e.getIndexInRing());
            o.append(", \"type\": ").append(e.getType());
            o.append(", \"typeName\": ").append(q(safeType(e)));
            o.append(", \"deviceType\": ").append(e.getDeviceType());
            o.append(", \"deviceTypeName\": ").append(q(safeDeviceType(e)));
            o.append(", \"enabled\": ").append(boolField(e, "enabled"));
            o.append(", \"invert\": ").append(e.isInvert());
            o.append(", \"normalOpen\": ").append(e.isNormalOpen());
            o.append(", \"safe\": ").append(q(e.getSafe()));
            // ruwe opgeslagen waarde: getSafe() geeft null buiten FIO-DO, maar het veld is gezet
            o.append(", \"safeRaw\": ").append(q(stringField(e, "safe")));
            o.append(", \"controlMatrix\": ").append(matrixJson(e, alarms));
            o.append(", \"description\": ").append(q(e.getDescription()));
            o.append(", \"alarmFunction\": ").append(q(e.getAlarmFunction()));
            o.append(", \"fbMaster\": ").append(q(e.getFbFilenameMaster()));
            o.append(", \"fbConditional\": ").append(q(e.getFbFilenameConditional()));
            o.append(", \"openZones\": [");
            List<Integer> oz = e.getOpenZones();
            if (oz != null) for (int k = 0; k < oz.size(); k++) { if (k > 0) o.append(","); o.append(oz.get(k)); }
            o.append("], \"zones\": [");
            List<Integer> zids = zoneMap.get(e.getName());
            if (zids != null) for (int k = 0; k < zids.size(); k++) { if (k > 0) o.append(","); o.append(zids.get(k)); }
            o.append("]}");
        }
        o.append("\n  ]\n}\n");
        return o.toString();
    }

    static String safeType(Element e) { try { return e.getTypeAsString(); } catch (Throwable t) { return String.valueOf(e.getType()); } }
    static String safeDeviceType(Element e) { try { return e.getDeviceTypeAsString(); } catch (Throwable t) { return String.valueOf(e.getDeviceType()); } }

    static boolean boolField(Object o, String name) {
        try { Field f = o.getClass().getDeclaredField(name); f.setAccessible(true); return f.getBoolean(o); }
        catch (Throwable t) { return false; }
    }

    /** Ruwe waarde van een String-veld, ook als de getter die verbergt (bv. Element.safe). */
    static String stringField(Object o, String name) {
        try { Field f = o.getClass().getDeclaredField(name); f.setAccessible(true); return (String) f.get(o); }
        catch (Throwable t) { return null; }
    }

    /**
     * Controlematrix als één object per alarm, in de volgorde van
     * {@code Configuration.getAlarms()}: {@code {alarmId, waarde}} met
     * {@code -1} voor een ontbrekende of lege cel.
     */
    static String matrixJson(Element e, List<Alarm> alarms) {
        List<AlarmValuePair<Integer>> matrix = e.getControlMatrix();
        StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < alarms.size(); i++) {
            Alarm alarm = alarms.get(i);
            Integer value = null;
            if (matrix != null) {
                for (AlarmValuePair<Integer> pair : matrix) {
                    if (pair != null && pair.getAlarm() == alarm) { value = pair.getValue(); break; }
                }
            }
            if (i > 0) b.append(", ");
            b.append("{\"alarmId\": ").append(i).append(", \"waarde\": ")
             .append(value == null ? -1 : value).append("}");
        }
        return b.append("]").toString();
    }

    static String q(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder("\"");
        for (char ch : s.toCharArray()) {
            switch (ch) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (ch < 0x20) b.append(String.format("\\u%04x", (int) ch)); else b.append(ch);
            }
        }
        return b.append('"').toString();
    }

    // ---------- apply ----------
    /**
     * edits.tsv: één wijziging per regel, tab-gescheiden:
     *   <elementnaam>\t<veld>\t<waarde>
     * Velden: name, address, unit, unitId, indexInRing, type, deviceType, description,
     *         enabled, invert, normalOpen, safe, alarmFunction, zones, ring
     *
     * Structurele regels (ids = dump-'id' = index in Configuration.getElements() bij aanvang):
     *   @ringadd\t<naam>\t[<host>]
     *   @ringset\t<ringId>\t<veld>\t<waarde>            (velden: name, host)
     *   @zone\tnew\t<naam>\t[<beschrijving>]
     *   @zone\t<zoneId>\t<naam>\t[<beschrijving>]
     *   @zonedel\t<zoneId>
     *   @add\t<ringId>\t<unit>\t<address>\t<type>\t<deviceType>\t<unitId>\t<zoneIds-csv>\t[<naam>]
     *   @rename\t<id>\t<naam>
     *   @set\t<id>\t<veld>\t<waarde>
     *   @del\t<id>
     *   @order\t<ringId>\t<id,id,...>
     */
    static int applyEdits(Configuration c, Path tsv) throws IOException {
        List<String> lines = Files.readAllLines(tsv, StandardCharsets.UTF_8);
        // snapshot: alle ids worden tegen de begintoestand opgelost
        List<Element> snapshot = new ArrayList<>(c.getElements());
        Map<Integer, Element> byId = new LinkedHashMap<>();
        for (int i = 0; i < snapshot.size(); i++) byId.put(i, snapshot.get(i));

        int n = 0;
        n += applyRingAdds(c, lines);
        n += applyRingSets(c, lines);
        n += applyAlarmEdits(c, lines);
        n += applyZoneEdits(c, lines);
        n += applyZoneDeletes(c, lines);
        n += applyAdds(c, lines);
        n += applyFieldEdits(c, lines);
        n += applySetEdits(c, lines, byId);
        n += applyRenames(c, lines, byId);
        n += applyDeletes(c, lines, byId);
        n += applyOrders(c, lines, byId);
        renumberIndexes(c);
        return n;
    }

    static boolean isStructural(String line) {
        return line.startsWith("@ringadd\t") || line.startsWith("@ringset\t") || line.startsWith("@zone\t") || line.startsWith("@zonedel\t")
                || line.startsWith("@alarmrename\t") || line.startsWith("@alarmdesc\t") || line.startsWith("@alarmvalue\t")
                || line.startsWith("@add\t") || line.startsWith("@rename\t") || line.startsWith("@set\t")
                || line.startsWith("@del\t") || line.startsWith("@order\t");
    }

    static String[] cols(String line) { return line.split("\t", -1); }

    static int parseInt(String raw, String what) {
        try { return Integer.parseInt(raw.trim()); }
        catch (NumberFormatException ex) {
            throw new IllegalArgumentException(what + ": geen geheel getal: '" + raw + "'");
        }
    }

    static Ring findRingById(Configuration c, String raw) {
        int id = parseInt(raw, "@-regel ring-id");
        for (Ring r : c.getRings()) if (r.getId() == id) return r;
        throw new IllegalArgumentException("@-regel: onbekende ring-id " + id);
    }

    static Zone findZoneById(Configuration c, String raw) {
        int id = parseInt(raw, "@-regel zone-id");
        for (Zone z : c.getZones()) if (z.getId() == id) return z;
        throw new IllegalArgumentException("@-regel: onbekende zone-id " + id);
    }

    static Element liveElement(Configuration c, Map<Integer, Element> byId, String raw) {
        int id = parseInt(raw, "@-regel element-id");
        Element e = byId.get(id);
        if (e == null) throw new IllegalArgumentException("@-regel: onbekende element-id " + id);
        if (!identityContains(c.getElements(), e))
            throw new IllegalArgumentException("@-regel: element-id " + id + " bestaat niet meer");
        return e;
    }

    static boolean identityContains(List<Element> list, Element e) {
        for (Element x : list) if (x == e) return true;
        return false;
    }

    static int applyRingAdds(Configuration c, List<String> lines) {
        int n = 0;
        for (String line : lines) {
            if (!line.startsWith("@ringadd\t")) continue;
            String[] p = cols(line);
            if (p.length < 2 || p[1].trim().isEmpty())
                throw new IllegalArgumentException("@ringadd: ringnaam ontbreekt");
            String name = p[1].trim();
            for (Ring r : c.getRings())
                if (name.equals(r.getName()))
                    throw new IllegalArgumentException("@ringadd: ring bestaat al: " + name);
            int max = 0;
            for (Ring r : c.getRings()) max = Math.max(max, r.getId());
            Ring r = new Ring();
            r.setId(max + 1);
            r.setName(name);
            r.setHost(p.length > 2 && !p[2].trim().isEmpty() ? p[2].trim() : "localhost");
            // vendor-standaardwaarden voor een nieuwe ring; de Ringbus Tool blijft
            // de eindvalidator voor de exacte BACnet-regel.
            r.setCpuType(5);
            if (c.getRings().isEmpty()) {
                r.setInstanceId(10000);
                r.setNetworkNumber(536);
            } else {
                int maxInstance = Integer.MIN_VALUE, maxNetwork = Integer.MIN_VALUE;
                for (Ring other : c.getRings()) {
                    maxInstance = Math.max(maxInstance, other.getInstanceId());
                    maxNetwork = Math.max(maxNetwork, other.getNetworkNumber());
                }
                r.setInstanceId(maxInstance + 1000);
                r.setNetworkNumber(maxNetwork + 1);
            }
            c.getRings().add(r);
            System.out.println("RING toegevoegd: " + r.getId() + " " + name);
            n++;
        }
        return n;
    }

    /**
     * {@code @ringset <ringId> <veld> <waarde>}: wijzig naam of host van een
     * bestaande ring. Een onbekende ring-id of veld, een lege naam en een naam
     * die al door een andere ring gebruikt wordt zijn fouten.
     */
    static int applyRingSets(Configuration c, List<String> lines) {
        int n = 0;
        for (String line : lines) {
            if (!line.startsWith("@ringset\t")) continue;
            String[] p = cols(line);
            if (p.length < 4)
                throw new IllegalArgumentException("@ringset: verwacht ring-id, veld en waarde");
            Ring r = findRingById(c, p[1]);
            String field = p[2].trim();
            String value = p[3].trim();
            switch (field) {
                case "name":
                    if (value.isEmpty())
                        throw new IllegalArgumentException("@ringset: ringnaam ontbreekt");
                    for (Ring other : c.getRings())
                        if (other != r && value.equals(other.getName()))
                            throw new IllegalArgumentException("@ringset: ring bestaat al: " + value);
                    r.setName(value);
                    break;
                case "host":
                    if (value.isEmpty())
                        throw new IllegalArgumentException("@ringset: host ontbreekt");
                    r.setHost(value);
                    break;
                default:
                    throw new IllegalArgumentException("@ringset: onbekend veld: " + field);
            }
            n++;
        }
        return n;
    }

    /**
     * Alarmregels: {@code @alarmrename <alarmId> <naam>},
     * {@code @alarmdesc <alarmId> <tekst>} en
     * {@code @alarmvalue <elementId> <alarmId> <waarde>}.
     *
     * De alarm-id is de index in {@code Configuration.getAlarms()} (dezelfde id
     * als in de dump). Een onbekende id of een waarde die geen -1 en niet
     * {@code >= 0} is, is een fout. {@code @alarmvalue} houdt de matrix op de
     * lengte van de alarmenlijst via {@link Element#checkControlMatrix}.
     */
    static int applyAlarmEdits(Configuration c, List<String> lines) {
        List<Alarm> alarms = c.getAlarms();
        if (alarms == null) alarms = new ArrayList<>();
        int n = 0;
        for (String line : lines) {
            if (line.startsWith("@alarmrename\t")) {
                String[] p = cols(line);
                if (p.length < 3) throw new IllegalArgumentException("@alarmrename: verwacht alarm-id en naam");
                Alarm a = findAlarmById(alarms, p[1]);
                String name = p[2].trim();
                if (name.isEmpty()) throw new IllegalArgumentException("@alarmrename: naam ontbreekt");
                a.setName(name);
                n++;
            } else if (line.startsWith("@alarmdesc\t")) {
                String[] p = cols(line);
                if (p.length < 3) throw new IllegalArgumentException("@alarmdesc: verwacht alarm-id en omschrijving");
                Alarm a = findAlarmById(alarms, p[1]);
                a.setDescription(p[2].trim());
                n++;
            } else if (line.startsWith("@alarmvalue\t")) {
                String[] p = cols(line);
                if (p.length < 4) throw new IllegalArgumentException(
                        "@alarmvalue: verwacht element-id, alarm-id en waarde");
                Element e = findElementById(c, p[1]);
                Alarm a = findAlarmById(alarms, p[2]);
                int value = parseInt(p[3], "@alarmvalue waarde");
                if (value < -1) throw new IllegalArgumentException(
                        "@alarmvalue: waarde moet -1 of >= 0 zijn (kreeg " + value + ")");
                e.checkControlMatrix(alarms);
                List<AlarmValuePair<Integer>> matrix = e.getControlMatrix();
                AlarmValuePair<Integer> pair = null;
                if (matrix != null) {
                    for (AlarmValuePair<Integer> candidate : matrix) {
                        if (candidate != null && candidate.getAlarm() == a) { pair = candidate; break; }
                    }
                }
                if (pair == null) {
                    int index = alarms.indexOf(a);
                    if (matrix == null || index < 0 || index >= matrix.size())
                        throw new IllegalArgumentException(
                                "@alarmvalue: alarm " + a.getId() + " zit niet in de matrix van element-id " + p[1]);
                    e.setMatrixValue(index, value);
                } else {
                    pair.setValue(value);
                }
                n++;
            }
        }
        return n;
    }

    static Alarm findAlarmById(List<Alarm> alarms, String raw) {
        int id = parseInt(raw, "@-regel alarm-id");
        if (id < 0 || id >= alarms.size())
            throw new IllegalArgumentException("@-regel: onbekende alarm-id " + id);
        return alarms.get(id);
    }

    /** Element op id uit de begintoestand van de apply (index in getElements()). */
    static Element findElementById(Configuration c, String raw) {
        int id = parseInt(raw, "@-regel element-id");
        List<Element> elements = c.getElements();
        if (id < 0 || id >= elements.size())
            throw new IllegalArgumentException("@-regel: onbekende element-id " + id);
        return elements.get(id);
    }

    static int applyZoneEdits(Configuration c, List<String> lines) {
        int n = 0;
        for (String line : lines) {
            if (!line.startsWith("@zone\t")) continue;
            String[] p = cols(line);
            if (p.length < 3) continue;
            String id = p[1].trim(), name = p[2].trim();
            String desc = p.length > 3 ? p[3].trim() : "";
            if ("new".equals(id)) {
                boolean dup = false;
                for (Zone z : c.getZones()) if (name.equals(z.getName())) dup = true;
                if (dup) { System.err.println("SKIP zone bestaat al: " + name); continue; }
                int max = 0;
                for (Zone z : c.getZones()) max = Math.max(max, z.getId());
                Zone z = new Zone();
                z.setId(max + 1);
                z.setName(name);
                z.setDescription(desc.isEmpty() ? null : desc);
                z.setOrder(max + 1);
                z.setElements(new ArrayList<Element>());
                c.getZones().add(z);
                System.out.println("ZONE toegevoegd: " + z.getId() + " " + name);
                n++;
            } else {
                for (Zone z : c.getZones()) if (String.valueOf(z.getId()).equals(id)) {
                    z.setName(name);
                    z.setDescription(desc.isEmpty() ? null : desc);
                    n++;
                }
            }
        }
        return n;
    }

    static int applyZoneDeletes(Configuration c, List<String> lines) {
        int n = 0;
        for (String line : lines) {
            if (!line.startsWith("@zonedel\t")) continue;
            String[] p = cols(line);
            if (p.length < 2) throw new IllegalArgumentException("@zonedel: zone-id ontbreekt");
            Zone z = findZoneById(c, p[1]);
            int id = z.getId();
            c.getZones().removeIf(x -> x == z);
            for (Element e : c.getElements()) {
                List<Integer> oz = e.getOpenZones();
                if (oz != null) oz.removeIf(v -> v != null && v == id);
            }
            n++;
        }
        return n;
    }

    static int applyAdds(Configuration c, List<String> lines) {
        int n = 0;
        for (String line : lines) {
            if (!line.startsWith("@add\t")) continue;
            String[] p = cols(line);
            if (p.length < 8)
                throw new IllegalArgumentException("@add: verwacht ringId, unit, address, type, deviceType, unitId, zoneIds");
            Ring ring = findRingById(c, p[1]);
            int unit = parseInt(p[2], "@add unit");
            int address = parseInt(p[3], "@add address");
            int type = parseInt(p[4], "@add type");
            int deviceType = parseInt(p[5], "@add deviceType");
            String unitId = p[6].trim();
            String zonesCsv = p[7].trim();
            String name = p.length > 8 ? p[8].trim() : "";

            Element e = new Element();
            // samples: addressOnUnit = address - 1 voor DIN2/DOM2/FIRE (zie test_add_address_on_unit_convention)
            if (address < 1)
                throw new IllegalArgumentException("@add: address moet >= 1 zijn (kreeg " + address + ")");
            e.setRing(ring);
            e.setUnit(unit);
            e.setAddress(address);
            e.setAddressOnUnit(address - 1);
            e.setType(type);
            e.setDeviceType(deviceType);
            e.setUnitId(unitId);
            List<Alarm> alarms = c.getAlarms();
            e.createControlMatrix(alarms == null ? new ArrayList<Alarm>() : alarms);
            e.setAlarmFunction("AND");
            e.setSafe("stay");
            e.setNormalOpen(true);
            e.setName(name.isEmpty() ? vendorName(e, ring, unit, address, deviceType) : name);
            e.setIndexInRing(c.getElements().size() + 1); // definitief via renumberIndexes()
            c.getElements().add(e);

            if (!zonesCsv.isEmpty()) {
                for (String part : zonesCsv.split(",")) {
                    String zid = part.trim();
                    if (zid.isEmpty()) continue;
                    addToZone(c, e, zid);
                }
            }
            System.out.println("ELEMENT toegevoegd: " + e.getName());
            n++;
        }
        return n;
    }

    static String vendorName(Element e, Ring ring, int unit, int address, int deviceType) {
        String unitPart = DeviceTypes.isDioDevice(deviceType)
                ? String.format("%02d", unit) : String.valueOf(unit);
        return safeType(e) + "_" + ring.getName() + "_" + unitPart + "_" + address;
    }

    static void addToZone(Configuration c, Element e, String zid) {
        for (Zone z : c.getZones()) {
            if (String.valueOf(z.getId()).equals(zid) || z.getName().equals(zid)) {
                List<Element> zels = z.getElements();
                if (zels == null) { zels = new ArrayList<>(); z.setElements(zels); }
                boolean dup = false;
                for (Element x : zels)
                    if (x == e || (x.getName() != null && x.getName().equals(e.getName()))) dup = true;
                if (!dup) zels.add(e);
                return;
            }
        }
        throw new IllegalArgumentException("@add: onbekende zone " + zid);
    }

    static int applyFieldEdits(Configuration c, List<String> lines) {
        int n = 0;
        Map<String, Element> cache = new HashMap<>();
        // normaliseer: zone-lijsten moeten naar dezelfde objecten wijzen als c.getElements()
        Map<String, Element> canonical = new HashMap<>();
        for (Element el : c.getElements()) canonical.put(el.getName(), el);
        for (Zone z : c.getZones()) {
            List<Element> zels = z.getElements();
            if (zels == null) continue;
            List<Element> fixed = new ArrayList<>();
            for (Element ze : zels) {
                Element c1 = canonical.getOrDefault(ze.getName(), ze);
                if (!fixed.contains(c1)) fixed.add(c1);
            }
            z.setElements(fixed);
        }
        for (String line : lines) {
            if (line.isBlank() || line.startsWith("#") || isStructural(line)) continue;
            String[] p = cols(line);
            if (p.length < 3) continue;
            String name = p[0].trim(), field = p[1].trim(), val = p[2].trim();
            Element e = cache.get(name);
            if (e == null) { e = findElement(c, name); if (e != null) cache.put(name, e); }
            if (e == null) { System.err.println("SKIP onbekend element: " + name); continue; }
            if (!applyFieldValue(c, e, field, val)) {
                System.err.println("SKIP onbekend veld: " + field);
                continue;
            }
            n++;
        }
        return n;
    }

    /**
     * Zet één veld op een element. Wordt zowel door de naam-gebaseerde
     * veld-edits als door de id-gebaseerde {@code @set}-regels gebruikt, zodat
     * beide paden exact dezelfde setters en validatie volgen.
     *
     * @return false als het veld onbekend is (dan is er niets gewijzigd)
     */
    static boolean applyFieldValue(Configuration c, Element e, String field, String val) {
        switch (field) {
            case "name": e.setName(val); return true;
            case "address": e.setAddress(Integer.parseInt(val)); return true;
            case "addressOnUnit": e.setAddressOnUnit(Integer.parseInt(val)); return true;
            case "unit": e.setUnit(Integer.parseInt(val)); return true;
            case "unitId": e.setUnitId(val); return true;
            case "indexInRing": e.setIndexInRing(Integer.parseInt(val)); return true;
            case "type": e.setType(Integer.parseInt(val)); return true;
            case "deviceType": e.setDeviceType(Integer.parseInt(val)); return true;
            case "description": e.setDescription(val); return true;
            case "enabled": setBool(e, "enabled", Boolean.parseBoolean(val)); return true;
            case "invert": e.setInvert(Boolean.parseBoolean(val)); return true;
            case "normalOpen": e.setNormalOpen(Boolean.parseBoolean(val)); return true;
            case "safe": e.setSafe(val); return true;
            case "alarmFunction": e.setAlarmFunction(val); return true;
            case "zones": applyZones(c, e, val); return true;
            case "ring": applyRing(c, e, val); return true;
            default: return false;
        }
    }

    /**
     * Id-gebaseerde veld-edits: {@code @set <id> <veld> <waarde>}. De id is,
     * net als bij {@code @rename}/{@code @del}, de index in
     * {@code Configuration.getElements()} bij aanvang van de apply.
     */
    static int applySetEdits(Configuration c, List<String> lines, Map<Integer, Element> byId) {
        int n = 0;
        for (String line : lines) {
            if (!line.startsWith("@set\t")) continue;
            String[] p = cols(line);
            if (p.length < 4)
                throw new IllegalArgumentException("@set: verwacht id, veld en waarde");
            Element e = liveElement(c, byId, p[1]);
            String field = p[2].trim(), val = p[3].trim();
            if (!applyFieldValue(c, e, field, val))
                throw new IllegalArgumentException("@set: onbekend veld: " + field);
            n++;
        }
        return n;
    }

    static int applyRenames(Configuration c, List<String> lines, Map<Integer, Element> byId) {
        int n = 0;
        for (String line : lines) {
            if (!line.startsWith("@rename\t")) continue;
            String[] p = cols(line);
            if (p.length < 3) throw new IllegalArgumentException("@rename: verwacht id en naam");
            liveElement(c, byId, p[1]).setName(p[2].trim());
            n++;
        }
        return n;
    }

    static int applyDeletes(Configuration c, List<String> lines, Map<Integer, Element> byId) {
        int n = 0;
        for (String line : lines) {
            if (!line.startsWith("@del\t")) continue;
            String[] p = cols(line);
            if (p.length < 2) throw new IllegalArgumentException("@del: element-id ontbreekt");
            Element e = liveElement(c, byId, p[1]);
            c.getElements().removeIf(x -> x == e);
            for (Zone z : c.getZones()) {
                List<Element> zels = z.getElements();
                if (zels != null) zels.removeIf(x -> x == e);
            }
            n++;
        }
        return n;
    }

    static int applyOrders(Configuration c, List<String> lines, Map<Integer, Element> byId) {
        int n = 0;
        for (String line : lines) {
            if (!line.startsWith("@order\t")) continue;
            String[] p = cols(line);
            if (p.length < 3) throw new IllegalArgumentException("@order: verwacht ringId en id-lijst");
            Ring ring = findRingById(c, p[1]);
            List<Element> want = new ArrayList<>();
            Set<Element> seen = Collections.newSetFromMap(new IdentityHashMap<>());
            for (String part : p[2].split(",")) {
                String id = part.trim();
                if (id.isEmpty()) continue;
                Element e = liveElement(c, byId, id);
                if (e.getRingId() != ring.getId())
                    throw new IllegalArgumentException("@order: element-id " + id + " zit niet op ring " + ring.getId());
                if (!seen.add(e))
                    throw new IllegalArgumentException("@order: dubbel element-id " + id);
                want.add(e);
            }
            List<Element> current = new ArrayList<>();
            for (Element e : c.getElements()) if (e.getRingId() == ring.getId()) current.add(e);
            // ids verwijzen naar de snapshot; reeds verwijderde elementen mogen niet in de lijst staan
            Set<Element> snapshotSet = Collections.newSetFromMap(new IdentityHashMap<>());
            snapshotSet.addAll(byId.values());
            List<Element> required = new ArrayList<>();
            for (Element e : current) if (snapshotSet.contains(e)) required.add(e);
            if (required.size() != want.size() || !seen.containsAll(required))
                throw new IllegalArgumentException("@order: id-lijst dekt niet alle bestaande elementen van ring "
                        + ring.getId() + " (" + want.size() + " van " + required.size() + ")");
            // nieuw toegevoegde elementen (niet in snapshot) sluiten achteraan aan
            List<Element> ordered = new ArrayList<>(want);
            for (Element e : current) if (!snapshotSet.contains(e)) ordered.add(e);
            List<Element> reordered = new ArrayList<>(c.getElements());
            int k = 0;
            for (int i = 0; i < reordered.size(); i++)
                if (reordered.get(i).getRingId() == ring.getId()) reordered.set(i, ordered.get(k++));
            c.getElements().clear();
            c.getElements().addAll(reordered);
            n++;
        }
        return n;
    }

    /** Nummer per ring opnieuw 1..n in lijstvolgorde (zoals ElementsEditorTableModel.updateTableData()). */
    static void renumberIndexes(Configuration c) {
        Map<Integer, Integer> counters = new HashMap<>();
        for (Element e : c.getElements()) {
            int rid = e.getRingId();
            int next = counters.getOrDefault(rid, 0) + 1;
            counters.put(rid, next);
            e.setIndexInRing(next);
        }
    }

    static Element findElement(Configuration c, String name) {
        for (Element e : c.getElements()) if (name.equals(e.getName())) return e;
        return null;
    }

    static void setBool(Object o, String name, boolean v) {
        try { Field f = o.getClass().getDeclaredField(name); f.setAccessible(true); f.setBoolean(o, v); }
        catch (Throwable ignored) {}
    }

    static void applyRing(Configuration c, Element e, String ringName) {
        for (Ring r : c.getRings()) if (ringName.equals(r.getName())) { e.setRing(r); return; }
    }

    static void applyZones(Configuration c, Element e, String csv) {
        // Element.zones is transient; de echte opslag is Zone.elements.
        for (Zone z : c.getZones()) {
            List<Element> zels = z.getElements();
            if (zels == null) continue;
            zels.removeIf(x -> x.getName().equals(e.getName()));
        }
        if (csv.isBlank()) return;
        for (String part : csv.split(",")) {
            String id = part.trim();
            if (id.isEmpty()) continue;
            for (Zone z : c.getZones()) {
                if (String.valueOf(z.getId()).equals(id) || z.getName().equals(id)) {
                    List<Element> zels = z.getElements();
                    if (zels == null) { zels = new ArrayList<>(); z.setElements(zels); }
                    boolean dup = false;
                    for (Element x : zels) if (x.getName().equals(e.getName())) dup = true;
                    if (!dup) zels.add(e);
                }
            }
        }
    }

    static byte[] hexToBytes(String s) {
        byte[] out = new byte[s.length() / 2];
        for (int i = 0; i < out.length; i++) out[i] = (byte) Integer.parseInt(s.substring(i * 2, i * 2 + 2), 16);
        return out;
    }
}
