#!/usr/bin/env python3
import sys
import subprocess


def main():
    # Messaggio per il Control Center
    tag = "steamos-diy"
    msg = "[JUPITER-SHIM] Richiesta BIOS Jupiter intercettata. Reporting: OK (Simulato)"

    # Invio al logger di sistema
    # Equivale a: echo "..." | logger -t steamos-diy
    subprocess.run(["logger", "-t", tag, msg], check=False)

    # Uscita con successo (0) per Steam
    sys.exit(0)


if __name__ == "__main__":
    main()
  
