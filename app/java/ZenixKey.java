import Aladdin.Hasp;
import java.nio.file.*;
import java.util.*;

/**
 * Leest de projectsleutels uit de aangesloten HASP-dongle.
 *
 *   java -cp ... ZenixKey [project.rbtproject]
 *
 * Zonder project: alle kandidaten als KEY=<hex>.
 * Met project: enkel de sleutel die het bestand effectief opent.
 */
public class ZenixKey {
    static final String VENDOR = "hI2BD1hOIdbfqjT9IzWC4+f/4n38ydk6QP5zRAxGuJy+l20UUuXY9rvshQkut9H7bECi5FVNIxcuRkpV0H4FbGuTiD9pgVj7WYWmnxLKIawNopo0yjOA14AOflSodI/u4xCMaFlmR0dXp0s9XscMr3B/1aTiBaHdpJQqiC0Ks+CVV6K5yvqvdU9hmb5m017km4opnTWgBCSzXunNwzfp/oi0egfTQIR2juxJi+5RHtP4AniVVXcUt6rw4Uk9VzIyxbcoaS6hYs/hFe8U3HzqSkPXyRTBAC1YD0ecAAMEa9SaFilq13m64nrmvdyMrKDrwFPSs0rGPse9iZIj+EX/lLS8o6KxZR+03COdLrPwbQ2ByJeUoXp2R0UUYw4B1Ls6+t1eJvDefQxrNBqQPsLpWcdmN5OtB7cxJmmM6J1cGWCG+plV9RKXtOSeicAhKBmSbIDRhU0SQzuDzD4ZS5FeRlkqU0FEp0pWILH8DNS32YbwC1g5bcO0NGRx4hswj4JmhGBYVqoUGywKUXgPAPjYVz9nJ1e67MdZMl2srmmzPjzIxC+HVOxwe9VK/DaDZVYJSbNzJJsi5Yzb61iktD/711/GDGDbEfhv5A36ur9QPYebNQFDbi+tYuJlPP4m4KhJYEmIBEeQ57vxmfFqTYphnm4ua1Rn9HLPl7g806cq8+wQWeOXtbcJnu/Pt/Xv2j5jU4yweGQ0H6RwpIuW37u7mJlo4sCE4O777NqCTOaEGcgglOtKay8/+IvPSIFykX/8I0Pb2SjenmkWlDMszBkhfF5hr5cNVM52z5tXCdkI5FY1mfVUCj7NdaJs4SQYovzfiN1fu+y0Zt5+NnDtAn4CFO3xKJpax4o0ikPwiB2yImy2laj4bhiyeYFCzZHvnu2gdl1fvWYCUX967m/39Kb06cEEQVNKZFgFtT7Qi+8B2QyLWNV39eA8WESTgcMqqeAkOvRC4iW+pJd/WC41ZBRjrQ==";

    static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    public static void main(String[] a) {
        try {
            String proj = null;
            for (String s : a) if (s.toLowerCase().endsWith(".rbtproject")) proj = s;

            Hasp hasp = new Hasp(1L);
            boolean ok = hasp.login(VENDOR);
            if (!ok) {
                System.out.println("ERROR=login " + hasp.getLastError());
                return;
            }
            List<byte[]> keys = new ArrayList<byte[]>();
            for (long fid : new long[]{65524L, 65525L}) {
                int size;
                try { size = hasp.getSize(fid); } catch (Throwable t) { size = -1; }
                if (size <= 0) continue;
                byte[] b = new byte[(size / 32) * 32];
                if (!hasp.read(fid, 0, b.length, b)) continue;
                for (int i = 0; i + 32 <= b.length; i += 32) {
                    byte[] k = Arrays.copyOfRange(b, i, i + 32);
                    boolean zero = true;
                    for (byte x : k) if (x != 0) { zero = false; break; }
                    if (!zero) keys.add(k);
                }
            }
            hasp.logout();
            System.out.println("CANDIDATES=" + keys.size());

            byte[] ct = proj == null ? null : Files.readAllBytes(Paths.get(proj));
            for (byte[] k : keys) {
                if (ct == null) { System.out.println("KEY=" + hex(k)); continue; }
                try {
                    javax.crypto.Cipher c = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding");
                    c.init(javax.crypto.Cipher.DECRYPT_MODE,
                           new javax.crypto.spec.SecretKeySpec(k, "AES"),
                           new javax.crypto.spec.GCMParameterSpec(128, k));
                    c.doFinal(ct);
                    System.out.println("KEY=" + hex(k));
                } catch (Exception e) {
                    System.out.println("MISS=" + hex(k).substring(0, 8));
                }
            }
        } catch (Throwable t) {
            System.out.println("ERROR=" + t);
        }
    }
}
