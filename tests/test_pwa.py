import os, tempfile, sys
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["AUTH_DISABLED"] = "1"
os.environ["SYNC_INTERVAL_MIN"] = "0"
os.environ["CHILD_NAME"] = "Lucie"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as c:
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and "manifest+json" in m.headers["content-type"]
    j = m.json()
    assert j["display"] == "standalone" and j["start_url"] == "/" and "Lucie" in j["name"]
    for i in j["icons"]:
        assert c.get(i["src"]).status_code == 200, i
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"] and "fetch" in sw.text
    h = c.get("/").text
    assert 'rel="manifest"' in h and "serviceWorker.register" in h and "apple-touch-icon" in h
print("ok PWA")
