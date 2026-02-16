#!/usr/bin/env python3
import sys
import subprocess


def main():
    # 1. Configurazione Tag e Messaggi
    tag = "steamos-diy"
    msg1 = "[UPDATE-SHIM] Intercettata richiesta OTA da Steam."
    msg2 = "[UPDATE-SHIM] Reporting status: UP TO DATE (Forced Exit 7)."

    # 2. Logging verso il Journal (Control Center)
    # Usiamo subprocess per parlare con logger come faceva lo script bash
    subprocess.run(["logger", "-t", tag, msg1], check=False)
    subprocess.run(["logger", "-t", tag, msg2], check=False)

    # 3. Exit Code 7 (Il "segreto" per dire a Steam che non ci sono update)
    sys.exit(7)


if __name__ == "__main__":
    main()
  
