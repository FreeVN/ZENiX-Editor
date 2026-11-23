import com.euroicc.ringbus.config.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;

/**
 * Genereert een testproject met twee alarmen en drie elementen.
 *
 * Wordt door tests/alarm_fixture.py tijdens de test gecompileerd en uitgevoerd;
 * het bestand staat niet als binair project in de repository. Als basis dient
 * een bestaand sample (dat zelf nul alarmen heeft); de vendor-API
 * (Configuration/Ring/Alarm/Element) maakt de alarmen en de matrix aan.
 *
 * Alarm en Element worden via sun.misc.Unsafe zonder constructor gemaakt: de
 * vendor-constructor van Alarm initialiseert een functie-parser waarvoor
 * java-cup nodig is, een dependency die niet bij de meegeleverde
 * configuration-jar zit en functioneel buiten scope is. Alle gebruikte velden
 * worden expliciet gezet.
 *
 *   java AlarmFixture <config.rbproject>
 */
public class AlarmFixture {

    static Object newWithoutCtor(Class<?> cls) throws Exception {
        Field f = Class.forName("sun.misc.Unsafe").getDeclaredField("theUnsafe");
        f.setAccessible(true);
        Object unsafe = f.get(null);
        Method m = unsafe.getClass().getMethod("allocateInstance", Class.class);
        return m.invoke(unsafe, cls);
    }

    public static void main(String[] args) throws Exception {
        Configuration c = Configuration.load(new File(args[0]));
        if (c == null) throw new IllegalStateException("Configuration.load gaf null");
        if (c.getRings() == null || c.getRings().isEmpty())
            throw new IllegalStateException("sample heeft geen ring");

        Ring ring = c.getRings().get(0);
        List<Alarm> alarms = new ArrayList<Alarm>();
        String[][] spec = {{"alarm_rook", "rookmelding"}, {"alarm_brand", "brandmelding"}};
        for (int i = 0; i < spec.length; i++) {
            Alarm a = (Alarm) newWithoutCtor(Alarm.class);
            a.setId(i + 1);
            a.setName(spec[i][0]);
            a.setDescription(spec[i][1]);
            a.setRing(ring);
            alarms.add(a);
        }
        c.setAlarms(alarms);

        List<Element> keep = new ArrayList<Element>();
        for (int i = 0; i < 3 && i < c.getElements().size(); i++) {
            Element e = c.getElements().get(i);
            e.createControlMatrix(alarms);
            keep.add(e);
        }
        c.setElements(keep);
        // De fixture is bedoeld voor alarm- en matrixtests; zoneverwijzingen
        // naar verwijderde elementen zouden alleen ruis geven.
        c.setZones(new ArrayList<Zone>());

        if (!c.saveAs(new File(args[0])))
            throw new IllegalStateException("saveAs mislukt");
        System.out.println("OK fixture alarms=" + alarms.size() + " elements=" + keep.size());
    }
}
