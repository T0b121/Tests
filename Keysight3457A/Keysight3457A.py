import pyvisa
import time

class HP3457A:
    """
    Eine Klasse zur Steuerung des HP 3457A Multimeters über PyVISA.
    Berücksichtigt die HPML-Syntax (kein SCPI) und State-Management.
    """

    def __init__(self, resource_name):
        """
        Initialisiert die Klasse mit der VISA-Ressourcenadresse.
        Baut noch keine Verbindung auf.
        
        :param resource_name: String, z.B. 'GPIB0::22::INSTR' oder 'ASRL1::INSTR'
        """
        self.resource_name = resource_name
        self.inst = None
        self.rm = None
        self.is_connected = False

    def connect(self, timeout=5000):
        """
        Verbindet zum Gerät und setzt Basis-Parameter.
        
        :param timeout: Timeout in Millisekunden (Standard: 5000ms)
        """
        try:
            self.rm = pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(self.resource_name)
            
            # Konfiguration der Kommunikation
            self.inst.timeout = timeout
            
            # WICHTIG für HP 3457A: EOL (End of Line) Konfiguration
            # Das Gerät erwartet meist \n oder \r\n. PyVISA fügt dies automatisch an write an.
            self.inst.read_termination = '\n'
            self.inst.write_termination = '\n'
            
            # Reset des Geräts, um in einen definierten Zustand zu kommen
            # 'PRESET' ist der HPML Befehl für Reset
            self.inst.write("PRESET")
            time.sleep(1.0) # Kurze Pause nach Reset
            
            # Setze das Gerät sofort in 'TRIG HOLD'.
            # Das verhindert, dass das Gerät sofort anfängt zu messen und den Buffer füllt.
            # So können wir sicher ID? oder NPLC? abfragen.
            self.stop_measurement()
            
            self.is_connected = True
            print(f"Verbunden mit {self.resource_name}")
            
        except Exception as e:
            print(f"Fehler beim Verbinden: {e}")
            self.is_connected = False
            raise

    def disconnect(self):
        """
        Trennt die Verbindung sauber und gibt Ressourcen frei.
        """
        if self.inst:
            try:
                # Optional: Gerät in lokalen Modus versetzen
                self.inst.write("LOCAL")
            except:
                pass
            self.inst.close()
        
        if self.rm:
            self.rm.close()
            
        self.is_connected = False
        print("Verbindung getrennt.")

    def read_id(self):
        """
        Liest die Identifikation des Geräts aus.
        Nutzt 'ID?' statt '*IDN?'.
        """
        if not self.is_connected:
            raise Exception("Gerät nicht verbunden")
        
        # Sicherstellen, dass wir nicht gerade wild messen (Buffer leeren)
        self.inst.clear()
        
        # Befehl senden und Antwort lesen
        response = self.inst.query("ID?")
        return response.strip()

    def setup_measurement(self, mode, range_val="AUTO"):
        """
        Konfiguriert, WAS gemessen werden soll.
        
        :param mode: 'DCV', 'ACV', 'DCI', 'ACI', 'OHM' (2-wire), 'OHMF' (4-wire)
        :param range_val: 'AUTO' oder ein numerischer Wert (z.B. 3, 30, 300)
        """
        if not self.is_connected:
            raise Exception("Gerät nicht verbunden")
            
        valid_modes = ['DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'OHMF', 'FREQ', 'PER']
        mode = mode.upper()
        
        if mode not in valid_modes:
            raise ValueError(f"Unbekannter Modus: {mode}. Erlaubt: {valid_modes}")
            
        # Befehl zusammensetzen: z.B. "DCV AUTO" oder "OHM 1000"
        cmd = f"{mode} {range_val}"
        self.inst.write(cmd)
        print(f"Messmodus gesetzt: {cmd}")

    def set_nplc(self, plc):
        """
        Setzt die Integrationszeit in Power Line Cycles (NPLC).
        Bestimmt Genauigkeit vs. Geschwindigkeit.
        
        :param plc: Wert (z.B. 0.0005, 1, 10, 100)
        """
        if not self.is_connected:
            raise Exception("Gerät nicht verbunden")
        
        # Sicherstellen, dass wir im Konfigurationsmodus sind (nicht messen)
        self.stop_measurement()
        
        self.inst.write(f"NPLC {plc}")

    def get_nplc(self):
        """
        Liest den aktuell gesetzten NPLC Wert aus.
        """
        if not self.is_connected:
            raise Exception("Gerät nicht verbunden")
            
        # Wir müssen sicherstellen, dass das Gerät nicht misst, sonst
        # bekommen wir evtl. einen Messwert statt der NPLC Antwort.
        self.stop_measurement()
        
        val = self.inst.query("NPLC?")
        return float(val)

    def start_measurement(self):
        """
        Startet den kontinuierlichen Messmodus (Free Run).
        Vorsicht: Das Gerät sendet nun Daten, wenn man liest.
        Andere Befehle (wie ID?) können fehlschlagen, wenn man dies nicht stoppt.
        """
        # 'TRIG AUTO' lässt das DMM so schnell wie möglich messen
        self.inst.write("TRIG AUTO")

    def stop_measurement(self):
        """
        Stoppt die Messung (Trigger Hold).
        Notwendig, um Konfigurationen zu ändern oder IDs zu lesen.
        """
        # 'TRIG HOLD' pausiert die Messung
        self.inst.write("TRIG HOLD")

    def read_single_value(self):
        """
        Führt EINE Messung durch und gibt den Wert zurück.
        Dies ist die sicherste Methode für kontrollierte Datenerfassung.
        """
        if not self.is_connected:
            raise Exception("Gerät nicht verbunden")

        # Strategie:
        # 1. Sicherstellen, dass Trigger auf HOLD ist (kein Datenmüll)
        # 2. 'TRIG SGL' senden (löst EINE Messung aus)
        # 3. Ergebnis lesen
        
        # Hinweis: Wenn wir schon im TRIG AUTO sind, lesen wir einfach den nächsten Wert.
        # Aber um robust zu sein, erzwingen wir hier einen kontrollierten Trigger.
        
        # self.inst.write("TRIG SGL") # Löst Messung aus und schiebt in Buffer
        # val = self.inst.read()      # Liest Buffer
        
        # Alternativ und oft einfacher in PyVISA: query
        # Das 3457A hat keinen expliziten "READ?" Befehl wie SCPI.
        # Aber wir können SGL Trigger nutzen und dann lesen.
        
        self.inst.write("TRIG SGL")
        value_str = self.inst.read()
        return float(value_str)


# --------------------------------------------------------------------------
# TEST BEREICH
# --------------------------------------------------------------------------
if __name__ == "__main__":
    # BITTE ANPASSEN: Hier die korrekte VISA Resource ID eintragen!
    # Für GPIB meist: 'GPIB0::22::INSTR' (wobei 22 die Adresse ist)
    # Für Seriell über VISA Adapter: 'ASRL1::INSTR'
    VISA_ADDRESS = 'GPIB0::22::INSTR' 
    
    # Mocking für Testzwecke, falls kein Gerät angeschlossen ist,
    # würde dies fehlschlagen. Daher Try/Except Block für Demo.
    
    print("--- Start HP 3457A Test ---")
    
    dmm = HP3457A(VISA_ADDRESS)
    
    try:
        # 1. Verbinden
        print(f"Verbinde zu {VISA_ADDRESS}...")
        dmm.connect(timeout=10000) # Etwas mehr Timeout für Init
        
        # 2. ID Auslesen
        dev_id = dmm.read_id()
        print(f"Geräte ID: {dev_id}")
        
        # 3. DC Spannung konfigurieren
        print("Konfiguriere DC Voltage...")
        dmm.setup_measurement("DCV", range_val="AUTO")
        
        # 4. NPLC setzen und prüfen
        print("Setze NPLC auf 10...")
        dmm.set_nplc(10)
        current_nplc = dmm.get_nplc()
        print(f"Gelesenes NPLC: {current_nplc}")
        
        # 5. Messung durchführen (Einzelmessungen)
        print("Starte 3 Einzelmessungen (Trigger Single)...")
        for i in range(3):
            val = dmm.read_single_value()
            print(f"Messwert {i+1}: {val} V")
            time.sleep(0.5)
            
        # 6. Ohmmessung Test
        print("Wechsle zu 2-Wire Ohm...")
        dmm.setup_measurement("OHM")
        
        # Schnellere Messung für Ohm
        dmm.set_nplc(1) 
        
        val_ohm = dmm.read_single_value()
        print(f"Widerstand: {val_ohm} Ohm")
        
    except pyvisa.errors.VisaIOError as e:
        print("\nACHTUNG: VISA Fehler aufgetreten.")
        print("Ist das Gerät angeschlossen und die Adresse korrekt?")
        print(f"Detailfehler: {e}")
    except Exception as e:
        print(f"\nEin allgemeiner Fehler ist aufgetreten: {e}")
    finally:
        # Immer sauber trennen
        print("Trenne Verbindung...")
        dmm.disconnect()
        print("--- Test Ende ---")