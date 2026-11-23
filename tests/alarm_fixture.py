"""Genereer tijdens de test een ``.rbtproject`` met alarmen en een matrix.

De fixture bestaat uit twee alarmen en drie elementen. Er staat geen binair
projectbestand in de repo: dit bestand bouwt het per test in ``tmp_path`` uit
het bestaande sample met de vendor-``Configuration`` (via
``tests/fixtures/AlarmFixture.java``), en verpakt het resultaat weer als
``.rbtproject`` met dezelfde projectsleutel als het sample.
"""
import os
import shutil
import subprocess

import core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "Duizendpoot", "Duizendpoot.rbtproject")
FIXTURE_JAVA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fixtures", "AlarmFixture.java")
CONFIG_JAR = os.path.join(ROOT, "app", "lib", "configuration-1.4.1.jar")
JAXB_JAR = os.path.join(ROOT, "app", "lib", "jaxb-api.jar")


def _classpath(*parts):
    return os.pathsep.join(str(p) for p in parts)


def build_alarm_project(target_dir):
    """Bouw een ``.rbtproject`` met 2 alarmen en 3 elementen; geeft het pad."""
    javac = shutil.which("javac")
    java = shutil.which("java")
    if not javac or not java:
        import pytest
        pytest.skip("javac/java ontbreken; de fixture-generator heeft een JDK nodig")

    work = os.path.join(str(target_dir), "fixture-work")
    classes = os.path.join(str(target_dir), "fixture-classes")
    os.makedirs(work, exist_ok=True)
    os.makedirs(classes, exist_ok=True)

    compile_result = subprocess.run(
        [javac, "--release", "17", "-cp", _classpath(CONFIG_JAR, JAXB_JAR),
         "-d", classes, FIXTURE_JAVA],
        capture_output=True, text=True)
    if compile_result.returncode != 0:
        raise RuntimeError("AlarmFixture compilen mislukt: " + compile_result.stderr)

    key, blob, _data = core.open_project(SAMPLE)
    core._unzip(blob, work)
    cfg = core._find_cfg(work)

    run = subprocess.run(
        [java, "-cp", _classpath(classes, CONFIG_JAR, JAXB_JAR), "AlarmFixture", cfg],
        capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError("AlarmFixture uitvoeren mislukt: "
                           + (run.stderr or run.stdout))

    out = os.path.join(str(target_dir), "AlarmFixture.rbtproject")
    with open(out, "wb") as f:
        f.write(core.AESGCM(key).encrypt(key, core._rezip(work), None))
    return out
