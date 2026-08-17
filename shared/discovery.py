import socket
import threading
import time
import logging
import urllib.request
import json
from typing import List, Optional

logger = logging.getLogger("rafiki.discovery")

DISCOVERY_PORT = 12345
DISCOVER_MSG = b"RAFIKI_BRAIN_DISCOVER"
BEACON_PREFIX = "RAFIKI_BRAIN_BEACON:"

def get_local_ips() -> List[str]:
    ips = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary = s.getsockname()[0]
        if primary not in ips and not primary.startswith("127."):
            ips.append(primary)
        s.close()
    except Exception:
        pass
    return list(set(ips))

def start_udp_discovery_responder(http_port: int):
    """Démarre le serveur de découverte UDP sur le PC cerveau (diffuse des beacons et répond aux requêtes)."""
    def responder_loop():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", DISCOVERY_PORT))
        except Exception as e:
            logger.warning(f"Impossible d'écouter sur le port UDP {DISCOVERY_PORT} : {e}")
            return
            
        logger.info(f"Serveur de découverte UDP démarré sur le port {DISCOVERY_PORT}")
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if data == DISCOVER_MSG:
                    ips = get_local_ips()
                    urls = [f"http://{ip}:{http_port}" for ip in ips]
                    response_str = f"RAFIKI_BRAIN_URLS:{','.join(urls)}"
                    sock.sendto(response_str.encode("utf-8"), addr)
            except Exception as e:
                logger.debug(f"Erreur dans le répondeur UDP : {e}")
                time.sleep(1)

    def beacon_loop():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        target = ("255.255.255.255", DISCOVERY_PORT)
        
        while True:
            try:
                ips = get_local_ips()
                urls = [f"http://{ip}:{http_port}" for ip in ips]
                beacon_msg = f"{BEACON_PREFIX}{','.join(urls)}".encode("utf-8")
                sock.sendto(beacon_msg, target)
            except Exception:
                pass
            time.sleep(4)

    t1 = threading.Thread(target=responder_loop, daemon=True)
    t2 = threading.Thread(target=beacon_loop, daemon=True)
    t1.start()
    t2.start()

def test_http_url(url: str) -> bool:
    """Valide qu'un URL de cerveau est bien un orchestrateur Rafiki actif."""
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "ok":
                    return True
    except Exception:
        pass
    return False

def discover_brain_url(timeout_seconds: float = 6.0) -> Optional[str]:
    """Envoie un broadcast de découverte UDP et écoute les réponses ou les beacons pour trouver le PC."""
    logger.info("Recherche automatique du cerveau Rafiki (UDP auto-discovery)...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1.0)
    
    try:
        sock.bind(("0.0.0.0", 0))
    except Exception:
        pass

    candidates = set()
    start_time = time.time()
    
    try:
        sock.sendto(DISCOVER_MSG, ("255.255.255.255", DISCOVERY_PORT))
    except Exception as e:
        logger.warning(f"Échec de l'envoi du broadcast de découverte : {e}")

    while time.time() - start_time < timeout_seconds:
        for candidate in list(candidates):
            if test_http_url(candidate):
                logger.info(f"Cerveau Rafiki trouvé et validé à : {candidate}")
                sock.close()
                return candidate
            else:
                candidates.remove(candidate)

        try:
            data, addr = sock.recvfrom(4096)
            msg = data.decode("utf-8", errors="ignore").strip()
            
            urls = []
            if msg.startswith("RAFIKI_BRAIN_URLS:"):
                urls = msg.replace("RAFIKI_BRAIN_URLS:", "").split(",")
            elif msg.startswith(BEACON_PREFIX):
                urls = msg.replace(BEACON_PREFIX, "").split(",")
                
            for url in urls:
                url = url.strip()
                if url:
                    candidates.add(url)
        except socket.timeout:
            try:
                sock.sendto(DISCOVER_MSG, ("255.255.255.255", DISCOVERY_PORT))
            except Exception:
                pass
        except Exception:
            pass

    sock.close()
    logger.warning("Auto-découverte expiré. Aucun cerveau Rafiki trouvé sur le réseau local.")
    return None
