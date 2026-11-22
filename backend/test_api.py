"""Smoke test of the whole report lifecycle. Run: python -m pytest -q  (or python test_api.py)"""
import os, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SEED_CREW"] = "1"
os.environ["MENDMAP_AI"] = "off"  # never call the Claude API from tests
from fastapi.testclient import TestClient
from app.main import app

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
PRISHTINA = {"latitude": 42.6605, "longitude": 21.1612}  # next to a demo school


def reg(c, body):
    """Sign up the way the app does: ask for a code, then register with it (demo mode returns the code)."""
    sent = c.post("/auth/otp/send", json={"email": body["email"]})
    if sent.status_code != 200:
        return sent  # e.g. 409: the email already has an account
    sent = sent.json()
    return c.post("/auth/register", json={**body, "code": sent.get("demo_code")})


def test_lifecycle():
    with TestClient(app) as c:
        cats = c.get("/categories").json()
        assert [x["icon"] for x in cats] == ["pothole", "streetlight", "dumping", "other", "accessibility"]
        a = reg(c, {"name": "Ann", "email": "ann@x.io", "password": "secret1"}).json()
        b = reg(c, {"name": "Bob", "email": "bob@x.io", "password": "secret1"}).json()
        ha = {"Authorization": f"Bearer {a['token']}"}
        hb = {"Authorization": f"Bearer {b['token']}"}
        assert reg(c, {"name": "A", "email": "ANN@x.io", "password": "secret1"}).status_code == 409
        assert c.post("/auth/login", json={"email": "ann@x.io", "password": "bad"}).status_code == 401

        # AI check answers "not available" without credentials instead of failing.
        chk = c.post("/ai/check-photo", headers=ha, files={"photo": ("p.png", PNG, "image/png")})
        assert chk.status_code == 200 and chk.json()["available"] is False

        # Bob's home is next door, so he is "near" Ann's report.
        assert c.put("/me/home", headers=hb, json=PRISHTINA).json()["home_lat"] == PRISHTINA["latitude"]

        r = c.post("/reports", headers=ha, data={"category_id": 1, **PRISHTINA, "severity": 4, "description": "Big hole"},
                   files={"photo": ("p.png", PNG, "image/png"), "voice": ("note.m4a", b"fake-audio", "audio/m4a")})
        assert r.status_code == 201, r.text
        rep = r.json()
        assert rep["status"] == "reported" and rep["photo_url"].startswith("/uploads/")
        assert rep["voice_url"].endswith(".m4a") and rep["severity"] == 4
        assert rep["neighbourhood"] == "Qendra" and "near_school" in rep["priority_reasons"] and rep["priority"] >= 55
        assert c.get(rep["photo_url"]).status_code == 200
        assert c.post("/reports", data={"category_id": 1, "latitude": 1, "longitude": 1},
                      files={"photo": ("p.png", PNG, "image/png")}).status_code == 401
        no_photo = c.post("/reports", headers=ha, data={"category_id": 1, **PRISHTINA})
        assert no_photo.status_code == 400 and "photo" in no_photo.json()["detail"].lower()

        near = c.get("/reports", params={"near": "42.6606,21.1613", "radius": 50, "status": "reported,in_progress"}).json()
        assert [x["id"] for x in near] == [rep["id"]] and near[0]["distance_m"] < 50
        assert c.get("/reports", params={"near": "42.7,21.1", "radius": 50}).json() == []
        assert [x["id"] for x in c.get("/me/nearby", headers=hb).json()] == [rep["id"]]
        assert c.get("/me/nearby", headers=ha).json() == []  # Ann has no home area

        assert c.post(f"/reports/{rep['id']}/confirm", headers=ha).status_code == 400
        assert c.post(f"/reports/{rep['id']}/confirm", headers=hb).json()["confirmations"] == 1
        assert c.post(f"/reports/{rep['id']}/confirm", headers=hb).status_code == 409

        _r = c.patch(f"/admin/reports/{rep['id']}/status", headers=ha, json={"status": "fixed"}); assert _r.status_code == 403, _r.text
        adm = c.post("/auth/login", json={"email": "admin@mendmap.local", "password": "admin123"}).json()
        hx = {"Authorization": f"Bearer {adm['token']}"}
        c.patch(f"/admin/reports/{rep['id']}/status", headers=hx, json={"status": "in_progress", "comment": "Crew sent"})

        # Crew mode: the job list, then "done" with an after photo.
        assert c.get("/crew/jobs", headers=ha).status_code == 403
        crew = c.post("/auth/login", json={"email": "crew@mendmap.local", "password": "crew123"}).json()
        hc = {"Authorization": f"Bearer {crew['token']}"}
        assert crew["user"]["role"] == "crew"
        jobs = c.get("/crew/jobs", headers=hc, params={"near": "42.66,21.16"}).json()
        assert [(j["id"], j["stop"]) for j in jobs] == [(rep["id"], 1)] and jobs[0]["leg_m"] > 0
        d = c.post(f"/crew/jobs/{rep['id']}/done", headers=hc, data={"comment": "Patched"},
                   files={"after_photo": ("a.png", PNG, "image/png")}).json()
        assert d["status"] == "fixed" and d["after_photo_url"].startswith("/uploads/") and d["priority"] == 0
        assert [u["new_status"] for u in d["updates"]] == ["reported", "in_progress", "fixed"]
        assert c.get("/crew/jobs", headers=hc).json() == []

        # Roles: crew log work in Jobs; they can't report, confirm, take neighbour jobs or earn citizen badges.
        st = c.get("/crew/stats", headers=hc).json()
        assert st["fixed_total"] == 1 and st["fixed_today"] == 1 and st["open_jobs"] == 0
        assert c.get("/crew/stats", headers=ha).status_code == 403
        assert c.post("/reports", headers=hc, data={"category_id": 1, **PRISHTINA},
                      files={"photo": ("p.png", PNG, "image/png")}).status_code == 403
        assert c.post(f"/reports/{rep['id']}/confirm", headers=hc).status_code == 403
        assert c.get("/me/badges", headers=hc).json() == []

        mine = c.get("/me/reports", headers=ha).json()
        assert mine[0]["status"] == "fixed" and len(mine[0]["updates"]) == 3
        s = c.get("/admin/stats", headers=hx).json()
        assert s["total"] == 1 and s["fixed"] == 1 and s["avg_days_to_fix"] is not None

        # Public transparency numbers and the before/after gallery need no sign-in.
        pub = c.get("/public/stats").json()
        assert pub["fix_rate"] == 1 and pub["neighbourhoods"][0]["name"] == "Qendra"
        assert [g["id"] for g in c.get("/public/gallery").json()] == [rep["id"]]

        got = {x["key"]: x["earned"] for x in c.get("/me/badges", headers=ha).json()}
        assert got["first_report"] and got["mended"] and not got["reporter_5"]
        assert c.put("/me/home", headers=hb, json={"latitude": None, "longitude": None}).json()["home_lat"] is None

        # Neighbour fixes: a resident of Qendra takes a dumping job, the city verifies it.
        assert "Kalabria" in c.get("/neighbourhoods").json()
        assert reg(c, {"name": "X", "email": "x@x.io", "password": "secret1",
                                              "neighbourhood": "Atlantis"}).status_code == 422
        q = reg(c, {"name": "Qendrim Lila", "email": "q@x.io", "password": "secret1",
                                           "neighbourhood": "Qendra"}).json()
        hq = {"Authorization": f"Bearer {q['token']}"}
        assert q["user"]["neighbourhood"] == "Qendra"
        k = reg(c, {"name": "Kim", "email": "k@x.io", "password": "secret1", "neighbourhood": "Kalabria"}).json()
        hk = {"Authorization": f"Bearer {k['token']}"}

        def dumping():
            return c.post("/reports", headers=ha, data={"category_id": 3, **PRISHTINA},
                          files={"photo": ("p.png", PNG, "image/png")}).json()

        job = dumping()
        assert job["neighbour_fixable"] is True
        assert job["id"] in [x["id"] for x in c.get("/me/fixer", headers=hk).json()["available"]]  # any area
        pothole = c.post("/reports", headers=ha, data={"category_id": 1, **PRISHTINA},
                         files={"photo": ("p.png", PNG, "image/png")}).json()
        assert c.post(f"/reports/{pothole['id']}/claim", headers=hq).status_code == 400  # crew only
        got = c.post(f"/reports/{job['id']}/claim", headers=hq).json()
        assert got["status"] == "in_progress" and got["claimed_by"] == q["user"]["id"] and got["claimed_by_name"] == "Qendrim"
        assert c.post(f"/reports/{job['id']}/claim", headers=hq).status_code == 409
        assert c.post(f"/reports/{job['id']}/unclaim", headers=hk).status_code == 409
        assert c.post(f"/reports/{job['id']}/unclaim", headers=hq).json()["status"] == "reported"
        c.post(f"/reports/{job['id']}/claim", headers=hq)
        assert [x["id"] for x in c.get("/me/fixer", headers=hq).json()["active"]] == [job["id"]]
        done = c.post(f"/reports/{job['id']}/neighbour-fixed", headers=hq,
                      files={"after_photo": ("a.png", PNG, "image/png")}).json()
        assert done["status"] == "fixed" and done["fix_status"] == "pending"
        assert c.post(f"/admin/reports/{job['id']}/verify-fix", headers=hq, json={"ok": True}).status_code == 403
        bad = c.post(f"/admin/reports/{job['id']}/verify-fix", headers=hx, json={"ok": False}).json()
        assert bad["status"] == "reported" and bad["claimed_by"] is None and bad["after_photo_url"] is None

        # 20 verified fixes = 20 fixer badges to spend on partner rewards.
        for i in range(20):
            jid = job["id"] if i == 0 else dumping()["id"]
            assert c.post(f"/reports/{jid}/claim", headers=hq).status_code == 200
            c.post(f"/reports/{jid}/neighbour-fixed", headers=hq, files={"after_photo": ("a.png", PNG, "image/png")})
            assert c.post(f"/admin/reports/{jid}/verify-fix", headers=hx, json={"ok": True}).json()["fix_status"] == "verified"
        f = c.get("/me/fixer", headers=hq).json()
        assert (f["verified"], f["balance"], f["spent"]) == (20, 20, 0)

        # Partner rewards: the admin adds them, a fixer spends badges and gets a voucher code.
        dinner = {"partner": "Zhuzuff Kitchen", "title": "Free dinner for 2", "emoji": "🍽️", "cost": 15, "stock": 1}
        assert c.post("/admin/partners", headers=hq, json=dinner).status_code == 403
        d = c.post("/admin/partners", headers=hx, json=dinner).json()
        coffee = c.post("/admin/partners", headers=hx, json={"partner": "Kafe", "title": "2 coffees", "cost": 10}).json()
        w = c.get("/rewards", headers=hq).json()
        assert w["balance"] == 20 and {d["id"], coffee["id"]} <= {r["id"] for r in w["rewards"]}
        v = c.post(f"/rewards/{d['id']}/claim", headers=hq)
        assert v.status_code == 201 and v.json()["code"].startswith("MM-") and v.json()["cost"] == 15
        assert c.post(f"/rewards/{coffee['id']}/claim", headers=hq).json()["detail"] == "Not enough badges for this reward yet"
        f = c.get("/me/fixer", headers=hq).json()
        assert (f["balance"], f["spent"], f["next_reward"]["id"]) == (5, 15, coffee["id"])
        assert d["id"] not in [r["id"] for r in c.get("/rewards", headers=hq).json()["rewards"]]  # stock 1: sold out
        assert c.post(f"/rewards/{d['id']}/claim", headers=hk).json()["detail"] == "This reward is sold out"
        assert c.post(f"/rewards/{coffee['id']}/claim", headers=hx).status_code == 403  # residents only
        vouchers = c.get("/admin/reward-claims", headers=hx).json()
        assert vouchers[0]["user_email"] and not vouchers[0]["used"]
        assert c.post(f"/admin/reward-claims/{vouchers[0]['id']}/used", headers=hx).json()["used"] is True
        assert c.get("/rewards", headers=hq).json()["claims"][0]["used"] is True
        assert c.delete(f"/admin/partners/{d['id']}", headers=hx).status_code == 204  # has a voucher: hidden, kept
        assert [x["active"] for x in c.get("/admin/partners", headers=hx).json() if x["id"] == d["id"]] == [False]
        assert c.delete(f"/admin/partners/{coffee['id']}", headers=hx).status_code == 204
        assert coffee["id"] not in [x["id"] for x in c.get("/admin/partners", headers=hx).json()]
        f = c.get("/me/fixer", headers=hq).json()
        assert (f["level"], f["next_level_at"]) == ("legend", None)

        # Open jobs in my area, a deadline on taken jobs, and release after 48 hours.
        late = dumping()
        assert late["id"] in [x["id"] for x in c.get("/me/fixer", headers=hq).json()["available"]]
        assert late["id"] in [x["id"] for x in c.get("/me/fixer", headers=hk).json()["available"]]
        taken = c.post(f"/reports/{late['id']}/claim", headers=hq).json()
        assert taken["claim_deadline"]
        from app.db import SessionLocal
        from app.models import Report as R
        import app.main as m
        with SessionLocal() as db:
            row = db.get(R, late["id"])
            row.claimed_at = row.claimed_at - m.timedelta(hours=49)
            db.commit()
        back = c.get(f"/reports/{late['id']}").json()
        assert back["status"] == "reported" and back["claimed_by"] is None and back["claim_deadline"] is None
        assert c.put("/me/neighbourhood", headers=hk, json={"neighbourhood": "Ulpiana"}).json()["neighbourhood"] == "Ulpiana"


        # One-time codes and demo Google/Apple sign-in.
        assert c.post("/auth/register", json={"name": "Z", "email": "z@x.io", "password": "secret1"}).json()["detail"] == "Verify your email first"
        sent = c.post("/auth/otp/send", json={"email": "Z@x.io"}).json()
        assert sent["sent"] and len(sent["demo_code"]) == 6 and sent["expires_in"] == 600
        assert c.post("/auth/otp/send", json={"email": "z@x.io"}).status_code == 429  # too soon
        wrong = "000000" if sent["demo_code"] != "000000" else "111111"
        assert c.post("/auth/register", json={"name": "Z", "email": "z@x.io", "password": "secret1", "code": wrong}).json()["detail"] == "Wrong code"
        z = c.post("/auth/register", json={"name": "Z", "email": "z@x.io", "password": "secret1", "code": sent["demo_code"]})
        assert z.status_code == 201 and z.json()["is_new"]
        assert c.post("/auth/otp/send", json={"email": "z@x.io"}).status_code == 409  # has an account now
        g = c.post("/auth/otp/send", json={"email": "gina@gmail.com", "purpose": "social"}).json()["demo_code"]
        bad = c.post("/auth/social", json={"provider": "google", "name": "Gina", "email": "gina@gmail.com", "code": "999999" if g != "999999" else "888888"})
        assert bad.status_code == 400
        first = c.post("/auth/social", json={"provider": "google", "name": "Gina", "email": "gina@gmail.com", "code": g, "neighbourhood": "Kalabria"}).json()
        assert first["is_new"] and first["user"]["neighbourhood"] == "Kalabria"
        assert c.post("/auth/social", json={"provider": "google", "name": "Gina", "email": "gina@gmail.com", "code": g}).status_code == 400  # used
        import app.main as m
        from app.models import OtpCode
        from app.db import SessionLocal
        with SessionLocal() as db:  # let the resend wait pass
            for row in db.query(OtpCode).filter(OtpCode.email == "gina@gmail.com"):
                row.created_at = row.created_at - m.timedelta(seconds=60)
            db.commit()
        sent2 = c.post("/auth/otp/send", json={"email": "gina@gmail.com", "purpose": "social"}).json()
        assert sent2["existing"] is True
        g2 = sent2["demo_code"]
        again = c.post("/auth/social", json={"provider": "apple", "name": "Gina", "email": "gina@gmail.com", "code": g2}).json()
        assert again["is_new"] is False and again["user"]["id"] == first["user"]["id"]

        # Levels, open jobs list, top fixers, and the 48-hour claim limit.
        from app.insights import level
        assert level(0) == ("starter", 1) and level(5) == ("fixer", 10) and level(25) == ("legend", None)
        tops = c.get("/public/fixers").json()
        assert tops and tops[0]["badges"] >= tops[-1]["badges"] and "level" in tops[0]

        assert c.put("/me/push-token", headers=ha, json={"push_token": "ExponentPushToken[x]"}).status_code == 204
        assert "MendMap" in c.get("/admin/").text


SAFE = [True]  # what the fake model says about neighbour safety


def test_gemini_stubbed():
    """Gemini photo check and voice transcription, with a fake client (no network, no key needed)."""
    import io, types as pytypes
    from PIL import Image
    from app import ai

    calls = []
    prompts = []

    class FakeModels:
        async def generate_content(self, model, contents, config=None):
            mime = contents[0].inline_data.mime_type
            calls.append((model, mime))
            prompts.append(contents[-1] if isinstance(contents[-1], str) else "")
            if mime.startswith("image/"):
                text = ('{"is_street_problem": true, "category": "dumping", "severity": 9, "reason": "Rubbish on the pavement.",'
                        ' "neighbour_safe": ' + ("true" if SAFE[0] else "false") + ', "safety_reason": "Bags and gloves are enough.",'
                        ' "description": "A pile of rubbish bags on the pavement.",'
                        ' "blur_boxes": [{"kind": "face", "box": [100, 100, 600, 500]}, {"kind": "plate", "box": [5, 5, 1, 1]}]}')
            else:
                text = "  Ka mbeturina para shkollës.  "
            return pytypes.SimpleNamespace(text=text)

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "gray").save(buf, "JPEG")
    jpg = buf.getvalue()
    old = {k: os.environ.get(k) for k in ("MENDMAP_AI", "GEMINI_API_KEY")}
    os.environ.update(MENDMAP_AI="on", GEMINI_API_KEY="test-key")
    ai._gemini = pytypes.SimpleNamespace(aio=pytypes.SimpleNamespace(models=FakeModels()))
    try:
        with TestClient(app) as c:
            assert c.get("/ai/status").json() == {"provider": "gemini", "photo_check": True, "transcription": True}
            tok = reg(c, {"name": "Gem", "email": "gem@x.io", "password": "secret1"}).json()["token"]
            h = {"Authorization": f"Bearer {tok}"}
            chk = c.post("/ai/check-photo", headers=h, files={"photo": ("p.jpg", jpg, "image/jpeg")}).json()
            assert chk["available"] and chk["category"] == "dumping" and chk["severity"] == 5  # clamped
            r = c.post("/reports", headers=h, data={"category_id": 3, **PRISHTINA},
                       files={"photo": ("p.jpg", jpg, "image/jpeg"), "voice": ("v.m4a", b"fake-audio", "audio/m4a")}).json()
            got = c.get(f"/reports/{r['id']}").json()
            assert got["voice_text"] == "Ka mbeturina para shkollës."
            # The server ran its own AI check: verdict stored, severity filled in, job open to neighbours.
            assert got["ai_category"] == "dumping" and got["ai_neighbour_safe"] is True and got["severity"] == 5
            assert got["neighbour_fixable"] is True
            # The AI describes the photo (used as the description when the citizen wrote none)...
            assert got["ai_description"] == got["description"] == "A pile of rubbish bags on the pavement."
            # ...and the face is blurred in the stored photo (the broken plate box is dropped).
            assert got["blurred"] == 1
            from pathlib import Path
            stored = (Path(__file__).parent / "uploads" / Path(got["photo_url"]).name).read_bytes()
            assert stored != jpg
            # The app asks for the description in the user's language.
            c.post("/ai/check-photo", headers=h, data={"lang": "sq"}, files={"photo": ("p.jpg", jpg, "image/jpeg")})
            assert "Write it in Albanian" in prompts[-1]
            # AI says unsafe: even a "safe" category can't be taken.
            SAFE[0] = False
            jpg2 = jpg + b"\0"  # different bytes, so no cached answer
            r2 = c.post("/reports", headers=h, data={"category_id": 3, **PRISHTINA},
                        files={"photo": ("p.jpg", jpg2, "image/jpeg")}).json()
            got2 = c.get(f"/reports/{r2['id']}").json()
            assert got2["ai_neighbour_safe"] is False and got2["neighbour_fixable"] is False
            assert c.post(f"/reports/{r2['id']}/claim", headers=h).json()["detail"] == "The AI check says this isn't safe for neighbours"
            # Same photo again: answered from the cache, no new model call.
            n = len(calls)
            c.post("/ai/check-photo", headers=h, files={"photo": ("p.jpg", jpg2, "image/jpeg")})
            assert len(calls) == n
            assert ("gemini-3.8-flash", "audio/mp4") in calls
    finally:
        ai._gemini = None
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_rating():
    """The reporter confirms a fix, or says it isn't fixed: then it's back on the map and a neighbour loses the badge."""
    with TestClient(app) as c:
        adm = c.post("/auth/login", json={"email": "admin@mendmap.local", "password": "admin123"}).json()
        ha = {"Authorization": f"Bearer {adm['token']}"}
        hr = {"Authorization": f"Bearer {reg(c, {'name': 'Rina', 'email': 'rina@x.io', 'password': 'secret1', 'neighbourhood': 'Kalabria'}).json()['token']}"}
        hn = {"Authorization": f"Bearer {reg(c, {'name': 'Nol', 'email': 'nol@x.io', 'password': 'secret1', 'neighbourhood': 'Kalabria'}).json()['token']}"}
        r = c.post("/reports", headers=hr, data={"category_id": 3, **PRISHTINA}, files={"photo": ("p.png", PNG, "image/png")}).json()
        assert c.post(f"/reports/{r['id']}/rate", headers=hr, json={"ok": True}).json()["detail"] == "You can rate it once it's fixed"
        # A neighbour fixes it and the city accepts: a badge.
        assert c.post(f"/reports/{r['id']}/claim", headers=hn).status_code == 200
        after = c.post(f"/reports/{r['id']}/neighbour-fixed", headers=hn,
                       files={"after_photo": ("a.png", PNG, "image/png")})
        assert after.status_code == 200, after.text
        c.post(f"/admin/reports/{r['id']}/verify-fix", headers=ha, json={"ok": True})
        assert c.get("/me/fixer", headers=hn).json()["verified"] == 1
        assert c.post(f"/reports/{r['id']}/rate", headers=hn, json={"ok": False}).status_code == 403
        # The reporter says it isn't fixed: reopened, badge gone, job open again.
        bad = c.post(f"/reports/{r['id']}/rate", headers=hr, json={"ok": False, "comment": "Still there"}).json()
        assert (bad["status"], bad["reopened"], bad["claimed_by"], bad["fix_status"]) == ("reported", 1, None, None)
        assert "Still there" in bad["updates"][-1]["comment"]
        assert c.get("/me/fixer", headers=hn).json()["verified"] == 0
        # Fixed again by the city, and this time the reporter confirms it.
        c.patch(f"/admin/reports/{r['id']}/status", headers=ha, json={"status": "fixed"})
        good = c.post(f"/reports/{r['id']}/rate", headers=hr, json={"ok": True}).json()
        assert good["rating"] == 1 and good["status"] == "fixed"
        assert c.post(f"/reports/{r['id']}/rate", headers=hr, json={"ok": True}).status_code == 409


def test_mjeshtrit():
    """Skilled volunteers: proof checked by the AI (stubbed), city review, skilled jobs, "ask a mjeshtër"."""
    from app import ai, main as m
    from app.db import SessionLocal
    from app.models import Report

    verdicts = {}

    async def fake_proof(data, mime, name, skills, lang="en"):
        v = verdicts.get(name, "unavailable")
        if v == "unavailable":
            return {"available": False}
        return {"available": True, "is_document": v != "not_a_document", "doc_type": "trade_certificate",
                "name_on_doc": name, "name_matches": True, "issuer": "Shkolla Profesionale", "skills_shown": ["plumbing"],
                "looks_genuine": v == "legit", "verdict": v, "confidence": 90, "reason": f"{v} doc", "reason_user": f"{v} doc"}

    real = ai.check_proof
    ai.check_proof = fake_proof
    try:
        with TestClient(app) as c:
            adm = c.post("/auth/login", json={"email": "admin@mendmap.local", "password": "admin123"}).json()
            hx = {"Authorization": f"Bearer {adm['token']}"}

            def user(name, email):
                return {"Authorization": f"Bearer {reg(c, {'name': name, 'email': email, 'password': 'secret1', 'neighbourhood': 'Kalabria'}).json()['token']}"}

            def apply(h, skills="plumbing,painting", days="sunday,holidays"):
                return c.post("/mjeshtrit/apply", headers=h, data={"skills": skills, "days": days, "bio": "Plumber"},
                              files={"proof": ("cert.jpg", PNG, "image/png")})

            # A genuine document: approved by the AI, but only for the skill the document shows.
            verdicts["Pal Plumber"] = "legit"
            hp = user("Pal Plumber", "pal@x.io")
            me = apply(hp).json()
            assert (me["status"], me["verified_by"], me["verified_skills"], me["days"]) == ("approved", "ai", ["plumbing"], ["holidays", "sunday"])
            u = c.get("/me", headers=hp).json()
            assert u["mjeshter_status"] == "approved" and u["mjeshter_skills"] == ["plumbing"]
            assert apply(hp).status_code == 200  # a new genuine document is fine

            # A fake one: rejected with the AI's reason; they can try again.
            verdicts["Fan Fake"] = "fake"
            hf = user("Fan Fake", "fan@x.io")
            bad = apply(hf).json()
            assert bad["status"] == "rejected" and bad["ai_reason_user"] == "fake doc"
            assert c.get("/me", headers=hf).json()["mjeshter_skills"] == []

            # AI busy: waits for the city. The document is private to admins.
            hw = user("Wes Wait", "wes@x.io")
            w = apply(hw, skills="painting").json()
            assert w["status"] == "pending" and w["ai_verdict"] == "unavailable"
            rows = c.get("/admin/mjeshtrit", headers=hx).json()
            assert rows[0]["user_email"] == "wes@x.io"  # waiting ones first
            assert c.get(f"/admin/mjeshtrit/{rows[0]['id']}/proof", headers=hx).status_code == 200
            assert c.get(f"/admin/mjeshtrit/{rows[0]['id']}/proof", headers=hw).status_code == 403
            ok = c.post(f"/admin/mjeshtrit/{rows[0]['id']}/approve", headers=hx).json()
            assert ok["status"] == "approved" and ok["verified_by"] == "admin" and ok["verified_skills"] == ["painting"]
            assert apply(hw, skills="nonsense").json()["detail"] == "Pick at least one skill"

            # The public list: verified only, filter by skill and day.
            names = [x["name"] for x in c.get("/mjeshtrit", headers=hf).json()]
            assert "Pal P." in names and "Wes W." in names and "Fan F." not in names
            assert [x["name"] for x in c.get("/mjeshtrit?skill=plumbing", headers=hf).json()] == ["Pal P."]
            assert c.get("/mjeshtrit?day=saturday", headers=hf).json() == []
            assert c.put("/mjeshtrit/me", headers=hp, json={"days": ["saturday"], "bio": "Weekends"}).json()["days"] == ["saturday"]

            # A skilled job (the AI says: not for ordinary neighbours, but a plumber can do it).
            hr = user("Rexha Reporter", "rexha@x.io")
            r = c.post("/reports", headers=hr, data={"category_id": 4, **PRISHTINA}, files={"photo": ("p.png", PNG, "image/png")}).json()
            with SessionLocal() as db:
                rep = db.get(Report, r["id"])
                rep.ai_is_problem, rep.ai_neighbour_safe, rep.ai_skilled_ok, rep.ai_skill_needed = 1, 0, 1, "plumbing"
                db.commit()
            got = c.get(f"/reports/{r['id']}").json()
            assert got["skill_needed"] == "plumbing" and got["neighbour_fixable"] is False
            assert c.post(f"/reports/{r['id']}/claim", headers=hr).json()["detail"] == "This job needs a verified mjeshtër"
            assert c.post(f"/reports/{r['id']}/claim", headers=hw).json()["detail"] == "You don't have the skill this job needs"
            assert r["id"] in [x["id"] for x in c.get("/me/fixer", headers=hp).json()["available"]]
            assert r["id"] not in [x["id"] for x in c.get("/me/fixer", headers=hw).json()["available"]]
            # "Ask a mjeshtër": once an hour.
            assert c.post(f"/reports/{r['id']}/ask-mjeshter", headers=hr).json()["notified"] == 1
            assert c.post(f"/reports/{r['id']}/ask-mjeshter", headers=hr).status_code == 429
            took = c.post(f"/reports/{r['id']}/claim", headers=hp).json()
            assert took["status"] == "in_progress" and took["updates"][-1]["comment"] == "A mjeshtër is fixing this."

            assert c.delete("/mjeshtrit/me", headers=hw).status_code == 204
            assert c.get("/me", headers=hw).json()["mjeshter_status"] is None
    finally:
        ai.check_proof = real


def test_translate():
    """English + the country's language: unknown languages are refused, placeholders must survive, results are cached."""
    import tempfile as _tf
    from pathlib import Path as _P
    from app import languages
    assert languages._ok("{n} badges", "{n} distintivi") and not languages._ok("{n} badges", "distintivi")
    calls = []

    async def fake_batch(lang, texts):
        calls.append(len(texts))
        return {t: f"[{lang}] {t}" for t in texts if "skip" not in t}

    real, real_cache = languages._batch, languages.CACHE
    languages._batch, languages.CACHE = fake_batch, _P(_tf.mkdtemp())
    old = os.environ.get("MENDMAP_AI")
    os.environ.update(MENDMAP_AI="on", GEMINI_API_KEY="test-key")
    try:
        with TestClient(app) as c:
            assert c.post("/i18n/translate", json={"lang": "xx", "strings": ["Hi"]}).status_code == 400
            assert c.post("/i18n/translate", json={"lang": "sq", "strings": ["Hi"]}).status_code == 400  # hand-made already
            r = c.post("/i18n/translate", json={"lang": "nl", "strings": ["Sign in", "{n} badges", "skip me"]}).json()
            assert r["translations"] == {"Sign in": "[nl] Sign in", "{n} badges": "[nl] {n} badges"} and r["missing"] == 1
            n = len(calls)
            r = c.post("/i18n/translate", json={"lang": "nl", "strings": ["Sign in"]}).json()
            assert r["translations"]["Sign in"] == "[nl] Sign in" and len(calls) == n  # from the cache
    finally:
        languages._batch, languages.CACHE = real, real_cache
        os.environ.pop("GEMINI_API_KEY", None)
        if old is None:
            os.environ.pop("MENDMAP_AI", None)
        else:
            os.environ["MENDMAP_AI"] = old


def test_fraud():
    """Fake photos and reused photos are flagged; neighbour fixes are checked before vs after."""
    import io, json as _json, random, types as pytypes
    from PIL import Image
    from fastapi.testclient import TestClient
    from app import ai
    from app.main import app

    KIND = ["real_photo"]
    FIX = [{"same_place": True, "problem_gone": True, "after_is_real_photo": True, "confidence": 92, "reason": "Rubbish is gone."}]

    class FakeModels:
        async def generate_content(self, model, contents, config):
            if len(contents) == 3:  # before, after, prompt: the fix check
                return pytypes.SimpleNamespace(text=_json.dumps(FIX[0]))
            return pytypes.SimpleNamespace(text=_json.dumps({
                "is_street_problem": True, "category": "dumping", "severity": 3, "reason": "Rubbish.",
                "neighbour_safe": True, "safety_reason": "Gloves are enough.",
                "photo_kind": KIND[0], "kind_reason": "Looks like a drawing." if KIND[0] != "real_photo" else "Phone photo."}))

    def photo(seed):
        rnd = random.Random(seed)
        img = Image.new("RGB", (64, 48))
        img.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(64 * 48)])
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        return buf.getvalue()

    old = {k: os.environ.get(k) for k in ("MENDMAP_AI", "GEMINI_API_KEY")}
    os.environ.update(MENDMAP_AI="on", GEMINI_API_KEY="test-key")
    ai._gemini = pytypes.SimpleNamespace(aio=pytypes.SimpleNamespace(models=FakeModels()))
    ai._cache.clear()
    try:
        with TestClient(app) as c:
            h = {"Authorization": f"Bearer {reg(c, {'name': 'Rita', 'email': 'rita@x.io', 'password': 'secret1'}).json()['token']}"}
            hn = {"Authorization": f"Bearer {reg(c, {'name': 'Nora', 'email': 'nora@x.io', 'password': 'secret1'}).json()['token']}"}
            ha = {"Authorization": f"Bearer {c.post('/auth/login', json={'email': 'admin@mendmap.local', 'password': 'admin123'}).json()['token']}"}

            def send(img, hdr=h):
                return c.post("/reports", headers=hdr, data={"category_id": 3, **PRISHTINA},
                              files={"photo": ("p.jpg", img, "image/jpeg")}).json()

            # A drawing is flagged and can't become a neighbour job.
            KIND[0] = "drawing"
            fake = c.get(f"/reports/{send(photo(1))['id']}").json()
            assert fake["flagged"] and "fake_photo" in fake["ai_flags"] and fake["ai_photo_kind"] == "drawing"
            assert fake["neighbour_fixable"] is False
            assert c.post(f"/ai/check-photo", headers=h, files={"photo": ("p.jpg", photo(1), "image/jpeg")}).json()["photo_kind"] == "drawing"
            # An official clears it.
            cleared = c.post(f"/admin/reports/{fake['id']}/clear-flag", headers=ha).json()
            assert cleared["flagged"] is False and cleared["flag_cleared"] is True

            # The same photo sent again (recompressed) is flagged as reused.
            KIND[0] = "real_photo"
            first = send(photo(2))
            buf = io.BytesIO()
            Image.open(io.BytesIO(photo(2))).save(buf, "JPEG", quality=60)
            again = c.get(f"/reports/{send(buf.getvalue(), hn)['id']}").json()
            assert "reused_photo" in again["ai_flags"] and again["reused_from"] == first["id"] and again["flagged"]

            # Neighbour fix: the report photo sent back is refused, a genuine fix is accepted by the AI.
            job = c.get(f"/reports/{send(photo(3))['id']}").json()
            assert job["neighbour_fixable"]
            assert c.post(f"/reports/{job['id']}/claim", headers=hn).status_code == 200
            same = c.post(f"/reports/{job['id']}/neighbour-fixed", headers=hn, files={"after_photo": ("a.jpg", photo(3), "image/jpeg")})
            assert same.status_code == 400 and "photo from the report" in same.json()["detail"]
            reused = c.post(f"/reports/{job['id']}/neighbour-fixed", headers=hn, files={"after_photo": ("a.jpg", photo(2), "image/jpeg")})
            assert reused.status_code == 400 and "already used" in reused.json()["detail"]
            c.post(f"/reports/{job['id']}/neighbour-fixed", headers=hn, files={"after_photo": ("a.jpg", photo(4), "image/jpeg")})
            ok = c.get(f"/reports/{job['id']}").json()
            assert ok["fix_ai"] == "auto_verified" and ok["fix_status"] == "verified"
            # An official can undo the AI's acceptance.
            undone = c.post(f"/admin/reports/{job['id']}/verify-fix", headers=ha, json={"ok": False}).json()
            assert undone["status"] == "reported" and undone["fix_ai"] is None

            # A fix photo of a different place waits for an official, with the AI's reason.
            FIX[0] = {**FIX[0], "same_place": False, "reason": "Different street."}
            job2 = c.get(f"/reports/{send(photo(5))['id']}").json()
            c.post(f"/reports/{job2['id']}/claim", headers=hn)
            c.post(f"/reports/{job2['id']}/neighbour-fixed", headers=hn, files={"after_photo": ("a.jpg", photo(6), "image/jpeg")})
            doubt = c.get(f"/reports/{job2['id']}").json()
            assert doubt["fix_ai"] == "different_place" and doubt["fix_status"] == "pending" and doubt["fix_ai_reason"] == "Different street."

            # Check everything: queues AI for reports not checked yet.
            assert "queued" in c.post("/admin/ai/review-all", headers=ha).json()
    finally:
        ai._gemini = None
        ai._cache.clear()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_gemini_hedge():
    """A slow model doesn't hold things up: the next one is asked too and the first answer wins."""
    import asyncio, time as _t, types as pytypes
    from app import ai

    class Slow:
        async def generate_content(self, model, contents, config):
            await asyncio.sleep(5 if model == "slow" else 0.05)
            return pytypes.SimpleNamespace(text=model)

    old = (ai._gemini, ai.GEMINI_HEDGE_S, ai._gemini_models)
    ai._gemini = pytypes.SimpleNamespace(aio=pytypes.SimpleNamespace(models=Slow()))
    ai.GEMINI_HEDGE_S = 0.2
    ai._gemini_models = lambda: ["slow", "fast"]
    try:
        t0 = _t.monotonic()
        res = asyncio.run(ai._gemini_generate([], None, "test"))
        assert res.text == "fast" and _t.monotonic() - t0 < 1.5
    finally:
        ai._gemini, ai.GEMINI_HEDGE_S, ai._gemini_models = old
        ai._busy_until.clear()


def test_chat():
    """Community chat: rooms, send/poll, AI moderation, reporting and deleting."""
    from app import ai as _ai
    with TestClient(app) as c:
        u1 = reg(c, {"name": "Chat One", "email": "chat1@x.io", "password": "secret1"}).json()
        u2 = reg(c, {"name": "Chat Two", "email": "chat2@x.io", "password": "secret1"}).json()
        h1, h2 = ({"Authorization": f"Bearer {u['token']}"} for u in (u1, u2))
        admin = c.post("/auth/login", json={"email": "admin@mendmap.local", "password": "admin123"}).json()
        ha = {"Authorization": f"Bearer {admin['token']}"}
        assert c.get("/chat/rooms").status_code == 401
        c.put("/me/neighbourhood", headers=h1, json={"neighbourhood": "Ulpiana"})
        rooms = c.get("/chat/rooms", headers=h1).json()
        assert rooms[0]["id"] == "city" and rooms[1]["id"] == "Ulpiana" and rooms[1]["mine"]
        assert c.get("/chat/rooms/Nowhere/messages", headers=h1).status_code == 404

        m1 = c.post("/chat/rooms/city/messages", headers=h1, json={"text": "  Hello   neighbours "})
        assert m1.status_code == 201 and m1.json()["text"] == "Hello neighbours" and m1.json()["mine"]
        m1 = m1.json()
        rep = c.get("/reports").json()[0]
        m2 = c.post("/chat/rooms/city/messages", headers=h2, json={"text": "Look at this", "report_id": rep["id"]}).json()
        assert m2["report"]["id"] == rep["id"] and m2["report"]["title"]
        assert c.post("/chat/rooms/city/messages", headers=h2, json={"text": "x", "report_id": 999999}).status_code == 404
        # Polling: only newer messages; seen from the other side "mine" is false.
        new = c.get(f"/chat/rooms/city/messages?after={m1['id']}", headers=h1).json()
        assert [m["id"] for m in new] == [m2["id"]] and not new[0]["mine"]
        assert [m["id"] for m in c.get("/chat/rooms/city/messages", headers=h1).json()][-2:] == [m1["id"], m2["id"]]
        assert c.get("/chat/rooms", headers=h1).json()[0]["last_id"] == m2["id"]

        # AI moderation: a blocked message is refused with the AI's reason; no AI answer = allowed.
        real = _ai.moderate_chat

        async def strict(text, lang="en"):
            return {"ok": "idiot" not in text, "reason": "Please be kind."}
        _ai.moderate_chat = strict
        try:
            bad = c.post("/chat/rooms/city/messages", headers=h1, json={"text": "you idiot"})
            assert bad.status_code == 422 and bad.json()["detail"] == "Please be kind."
        finally:
            _ai.moderate_chat = real

        # Rate limit: 5 messages in 30 s.
        for i in range(4):  # plus the first one = 5
            assert c.post("/chat/rooms/Ulpiana/messages", headers=h1, json={"text": f"m{i}"}).status_code == 201
        assert c.post("/chat/rooms/Ulpiana/messages", headers=h1, json={"text": "too many"}).status_code == 429

        # Reporting: not your own; counted once per person; staff hide at once.
        assert c.post(f"/chat/messages/{m1['id']}/flag", headers=h1).status_code == 400
        f = c.post(f"/chat/messages/{m1['id']}/flag", headers=h2).json()
        assert f == {"flags": 1, "hidden": False}
        assert c.post(f"/chat/messages/{m1['id']}/flag", headers=h2).json()["flags"] == 1
        assert c.post(f"/chat/messages/{m1['id']}/flag", headers=ha).json()["hidden"] is True
        assert c.get(f"/chat/rooms/city/hidden?after={m1['id']}", headers=h1).json() == [m1["id"]]
        assert m1["id"] not in [m["id"] for m in c.get("/chat/rooms/city/messages", headers=h2).json()]

        # Deleting: only your own (or an admin).
        assert c.delete(f"/chat/messages/{m2['id']}", headers=h1).status_code == 403
        assert c.delete(f"/chat/messages/{m2['id']}", headers=h2).status_code == 204
        assert c.delete(f"/chat/messages/{m2['id']}", headers=h2).status_code == 404


def test_street_search():
    """Street suggestions: needs sign-in, cached, duplicates merged; the address is kept on the report."""
    from app import geo, schemas as sc
    calls = []

    async def fake_photon(client, q):
        calls.append(q)
        P = lambda n, d: sc.Place(name=n, detail=d, kind="street", latitude=42.66, longitude=21.16)
        return [P("Agim Ramadani", "Dodona"), P("Agim Ramadani", "Dodona"), P("Agim Ramadani", "Ulpiana")]

    real = geo._photon
    geo._photon, geo._cache = fake_photon, {}
    try:
        with TestClient(app) as c:
            u = reg(c, {"name": "Geo", "email": "geo@x.io", "password": "secret1"}).json()
            h = {"Authorization": f"Bearer {u['token']}"}
            assert c.get("/geo/search?q=agim").status_code == 401
            assert c.get("/geo/search?q=a", headers=h).status_code == 422
            r = c.get("/geo/search?q=Agim  Ramadani", headers=h).json()
            assert [(x["name"], x["detail"]) for x in r] == [("Agim Ramadani", "Dodona"), ("Agim Ramadani", "Ulpiana")]
            c.get("/geo/search?q=agim ramadani", headers=h)
            assert calls == ["agim ramadani"]  # second search came from the cache
            cat = c.get("/categories").json()[0]["id"]
            rep = c.post("/reports", headers=h, data={"category_id": cat, "latitude": 42.66, "longitude": 21.16,
                                                      "address": " Agim Ramadani "},
                         files={"photo": ("p.png", PNG, "image/png")}).json()
            assert rep["address"] == "Agim Ramadani"
            assert c.get(f"/reports/{rep['id']}").json()["address"] == "Agim Ramadani"
    finally:
        geo._photon, geo._cache = real, {}


def test_community():
    """Clean-up days, adopted streets, fixed-badly, top 10, summary, announcements, chat moderation and translation."""
    import asyncio as _aio
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from app import ai as _ai, community as _cm
    with TestClient(app) as c:
        def user(name, email, area=None):
            u = reg(c, {"name": name, "email": email, "password": "secret1"}).json()
            h = {"Authorization": f"Bearer {u['token']}"}
            if area:
                c.put("/me/neighbourhood", headers=h, json={"neighbourhood": area})
            return u, h
        org, ho = user("Ora Org", "org@x.io", "Arbëria")
        g1, h1 = user("Gent One", "g1@x.io", "Arbëria")
        g2, h2 = user("Gita Two", "g2@x.io", "Arbëria")
        g3, h3 = user("Gaby Three", "g3@x.io")
        adm = c.post("/auth/login", json={"email": "admin@mendmap.local", "password": "admin123"}).json()
        ha = {"Authorization": f"Bearer {adm['token']}"}

        # ---- clean-up days ----
        soon = (_dt.now(_tz.utc) + _td(hours=10)).isoformat()
        body = {"room": "Arbëria", "title": "Clean the park", "starts_at": soon, "place": "Parku i Arbërisë"}
        assert c.post("/events", headers=ho, json={**body, "starts_at": (_dt.now(_tz.utc) - _td(hours=1)).isoformat()}).status_code == 422
        assert c.post("/events", headers=ho, json={**body, "room": "Nowhere"}).status_code == 404
        e = c.post("/events", headers=ho, json=body)
        assert e.status_code == 201, e.text
        e = e.json()
        assert e["going"] == 1 and e["mine"] and e["people"][0]["name"] == "Ora Org"
        # It shows up in the room's chat as a clean-up card.
        msg = [m for m in c.get("/chat/rooms/Arbëria/messages", headers=h1).json() if m["kind"] == "event"][-1]
        assert msg["event"]["id"] == e["id"] and msg["event"]["going"] == 1 and not msg["event"]["me_going"]
        for h in (h1, h2, h3):
            assert c.post(f"/events/{e['id']}/rsvp", headers=h).json()["me_going"]
        assert c.get(f"/events/{e['id']}", headers=h1).json()["people"] == []  # only the organiser sees the list
        assert c.get("/events?room=Arbëria", headers=h1).json()[0]["going"] == 4
        assert c.delete(f"/events/{e['id']}/rsvp", headers=ho).status_code == 409  # organiser cancels instead
        # Day-before reminder: once.
        assert _aio.run(_cm.send_reminders()) >= 1 and _aio.run(_cm.send_reminders()) == 0
        # Attendance only after it started, only by the organiser.
        assert c.post(f"/events/{e['id']}/attendance", headers=ho, json={"user_ids": [g1["user"]["id"]]}).status_code == 409
        from app.db import SessionLocal
        from app.models import CleanupEvent
        with SessionLocal() as db:
            db.get(CleanupEvent, e["id"]).starts_at -= _td(hours=12)
            db.commit()
        before = c.get("/me/fixer", headers=h1).json()["balance"]
        assert c.post(f"/events/{e['id']}/attendance", headers=h1, json={"user_ids": []}).status_code == 403
        ids = [g1["user"]["id"], g2["user"]["id"], g3["user"]["id"]]
        done = c.post(f"/events/{e['id']}/attendance", headers=ho, json={"user_ids": ids}).json()
        assert done["done"] and sum(p["attended"] for p in done["people"]) == 3
        assert c.get("/me/fixer", headers=h1).json()["balance"] == before + 1  # a badge for coming
        assert c.get("/me/fixer", headers=ho).json()["balance"] >= 1  # organiser: 3 people came
        # Cancelling (a new one).
        e2 = c.post("/events", headers=ho, json=body).json()
        assert c.delete(f"/events/{e2['id']}", headers=h1).status_code == 403
        assert c.delete(f"/events/{e2['id']}", headers=ho).json()["cancelled"] is True
        assert c.post(f"/events/{e2['id']}/rsvp", headers=h1).status_code == 409

        # ---- adopt a street ----
        assert _cm.street_key("Rr. Agim Ramadani 12, Dodona") == _cm.street_key("agim ramadani") == "agim ramadani"
        a = c.post("/adoptions", headers=h2, json={"street": "Rruga Garibaldi", "sponsor": "Shkolla Faik Konica"})
        assert a.status_code == 201 and a.json()["open"] == 0
        assert c.post("/adoptions", headers=h2, json={"street": "garibaldi"}).status_code == 409
        cat = c.get("/categories").json()[0]["id"]
        spot = {"category_id": cat, "latitude": 42.6702, "longitude": 21.1497, "address": "Garibaldi 5"}
        r1 = c.post("/reports", headers=h1, data=spot, files={"photo": ("p.png", PNG, "image/png")}).json()
        assert r1["repeat_of"] is None
        assert c.get(f"/reports/{r1['id']}").json()["adopted_by"] == ["Shkolla Faik Konica"]
        assert c.get("/adoptions/me", headers=h2).json()[0]["open"] == 1
        aid = c.get("/adoptions/me", headers=h2).json()[0]["id"]
        assert c.delete(f"/adoptions/{aid}", headers=h1).status_code == 404
        assert c.delete(f"/adoptions/{aid}", headers=h2).status_code == 204

        # ---- top 10: confirmed open problems ----
        c.post(f"/reports/{r1['id']}/confirm", headers=h2)
        top = c.get("/public/top").json()
        assert top[0]["id"] == r1["id"] and top[0]["confirmations"] == 1

        # ---- fixed badly: fixed, then reported again at the same spot ----
        fx = c.patch(f"/admin/reports/{r1['id']}/status", headers=ha, json={"status": "fixed", "comment": "Done"})
        assert fx.status_code == 200, fx.text
        r2 = c.post("/reports", headers=h3, data=spot, files={"photo": ("p.png", PNG, "image/png")}).json()
        assert r2["repeat_of"] == r1["id"]
        board = {n["name"]: n for n in c.get("/public/stats").json()["neighbourhoods"]}
        assert board["Arbëria"]["came_back"] >= 1 and board["Arbëria"]["avg_fix_days"] is not None

        # ---- weekly summary (no AI in tests: numbers only) ----
        assert c.get("/admin/summary", headers=h1).status_code == 403
        sm = c.get("/admin/summary?days=7", headers=ha).json()
        assert sm["text"] is None and sm["new"] >= 2 and sm["came_back"] >= 1 and sm["top_streets"][0][0] == "Garibaldi 5"
        assert c.post("/admin/summary/email", headers=ha).status_code == 400  # no SMTP in tests

        # ---- announcements + moderation + translation ----
        ann = c.post("/admin/announcements", headers=ha, json={"rooms": ["Arbëria", "city"], "text": "Water cut 9-12"})
        assert ann.status_code == 201 and len(ann.json()) == 2
        assert c.post("/admin/announcements", headers=h1, json={"rooms": ["city"], "text": "x"}).status_code == 403
        last = c.get("/chat/rooms/city/messages", headers=h1).json()[-1]
        assert last["kind"] == "announcement" and last["badge"] == "city"
        m = c.post("/chat/rooms/Arbëria/messages", headers=h1, json={"text": "Mirëdita fqinjë"}).json()
        c.post(f"/chat/messages/{m['id']}/flag", headers=h2)
        flagged = c.get("/admin/chat", headers=ha).json()
        assert any(x["id"] == m["id"] and x["flags"] == 1 for x in flagged)
        assert c.post(f"/admin/chat/{m['id']}/hide", headers=ha).json()["hidden"] is True
        restored = c.post(f"/admin/chat/{m['id']}/restore", headers=ha).json()
        assert restored["hidden"] is False and restored["flags"] == 0
        assert c.post(f"/chat/messages/{m['id']}/translate", headers=h3, json={"lang": "en"}).status_code == 503  # no AI
        calls = []

        async def fake_tr(text, lang):
            calls.append(lang)
            return "Good day neighbours"
        real = _ai.translate_text
        _ai.translate_text = fake_tr
        try:
            for _ in range(2):
                t = c.post(f"/chat/messages/{m['id']}/translate", headers=h3, json={"lang": "en"}).json()
                assert t["text"] == "Good day neighbours"
            assert calls == ["en"]  # translated once, then kept
            assert c.post(f"/chat/messages/{m['id']}/translate", headers=h3, json={"lang": "xx"}).status_code == 400
        finally:
            _ai.translate_text = real


def test_bookings():
    """Paid jobs: photo -> quote -> pay (demo, then Stripe stubbed) with a 10% commission -> done."""
    import asyncio, hashlib, hmac, json, time
    from app import bookings as bk
    from app.db import SessionLocal
    from app.models import Mjeshter, User
    from sqlalchemy import select

    with TestClient(app) as c:
        def user(name, email):
            return {"Authorization": f"Bearer {reg(c, {'name': name, 'email': email, 'password': 'secret1'}).json()['token']}"}
        hc, hw, hx = user("Vera Customer", "vera@b.io"), user("Gent Worker", "gent@b.io"), user("Nosy Neighbour", "nosy@b.io")
        with SessionLocal() as db:
            w = db.scalar(select(User).where(User.email == "gent@b.io"))
            m = Mjeshter(user_id=w.id, skills="plumbing", verified_skills="plumbing", status="approved", verified_by="admin")
            db.add(m); db.commit(); mid, wid = m.id, w.id

        # Ask for a price with a photo; the photo is private to the two of them.
        r = c.post("/bookings", headers=hc, data={"mjeshter_id": mid, "description": "Leaking pipe under the sink"},
                   files={"photo": ("p.png", PNG, "image/png")})
        assert r.status_code == 201, r.text
        b = r.json()
        assert b["status"] == "requested" and b["has_photo"] and b["as_role"] == "customer" and b["skill"] == "plumbing"
        assert c.post("/bookings", headers=hw, data={"mjeshter_id": mid, "description": "Book myself"},
                      files={"photo": ("p.png", PNG, "image/png")}).status_code == 400
        assert c.get(f"/bookings/{b['id']}/photo", headers=hw).status_code == 200
        assert c.get(f"/bookings/{b['id']}/photo", headers=hx).status_code == 404
        assert c.get(f"/bookings/{b['id']}", headers=hx).status_code == 404
        assert [x["id"] for x in c.get("/bookings", headers=hw, params={"as": "worker"}).json()] == [b["id"]]

        # Only the mjeshtër quotes, within limits.
        assert c.post(f"/bookings/{b['id']}/quote", headers=hc, json={"fee": 40}).status_code == 403
        assert c.post(f"/bookings/{b['id']}/quote", headers=hw, json={"fee": 1}).status_code == 400
        q = c.post(f"/bookings/{b['id']}/quote", headers=hw, json={"fee": 40, "note": "New pipe included"}).json()
        assert q["status"] == "quoted" and q["fee_cents"] == 4000 and q["commission_cents"] == 400 and q["worker_gets_cents"] == 3600

        # No Stripe keys and no demo mode: paying is switched off.
        os.environ.pop("STRIPE_SECRET_KEY", None); os.environ.pop("STRIPE_PUBLISHABLE_KEY", None)
        os.environ["MENDMAP_DEMO_PAYMENTS"] = "off"
        assert c.post(f"/bookings/{b['id']}/pay", headers=hc).status_code == 503
        # Demo mode: no money moves, the booking is marked paid.
        os.environ["MENDMAP_DEMO_PAYMENTS"] = "on"
        pay = c.post(f"/bookings/{b['id']}/pay", headers=hc).json()
        assert pay["mode"] == "demo" and pay["amount_cents"] == 4000 and pay["commission_cents"] == 400
        assert c.post(f"/bookings/{b['id']}/pay", headers=hw).status_code == 403
        paid = c.post(f"/bookings/{b['id']}/confirm-payment", headers=hc).json()
        assert paid["status"] == "paid" and paid["commission_cents"] == 400
        assert c.post(f"/bookings/{b['id']}/cancel", headers=hc).status_code == 409
        assert c.post(f"/bookings/{b['id']}/done", headers=hw).json()["status"] == "done"
        os.environ["MENDMAP_DEMO_PAYMENTS"] = "off"

        # Stripe (stubbed): the quote needs payouts, the payment sends 90% to the mjeshtër.
        calls = []
        acct = {"ready": False}

        async def fake_stripe(method, path, data=None, idem=None):
            calls.append((method, path, data))
            if path == "/accounts":
                return {"id": "acct_test"}
            if path.startswith("/accounts/"):
                return {"charges_enabled": acct["ready"], "payouts_enabled": acct["ready"]}
            if path == "/account_links":
                return {"url": "https://connect.stripe.test/onboard"}
            if method == "POST" and path == "/payment_intents":
                return {"id": "pi_test", "client_secret": "pi_test_secret", "amount": data["amount"], "status": "requires_payment_method"}
            if path == "/payment_intents/pi_test":
                return {"id": "pi_test", "amount": 2550, "status": "succeeded", "metadata": {"booking_id": str(b2["id"])}}
            raise AssertionError(path)

        real = bk.stripe_call
        bk.stripe_call = fake_stripe
        os.environ["STRIPE_SECRET_KEY"], os.environ["STRIPE_PUBLISHABLE_KEY"] = "sk_test_x", "pk_test_x"
        try:
            b2 = c.post("/bookings", headers=hc, data={"mjeshter_id": mid, "description": "Paint the fence"},
                        files={"photo": ("p.png", PNG, "image/png")}).json()
            assert c.post(f"/bookings/{b2['id']}/quote", headers=hw, json={"fee": 25.5}).status_code == 409  # no payouts yet
            assert c.post("/payouts/onboard", headers=hc).status_code == 403  # not a mjeshtër
            assert c.post("/payouts/onboard", headers=hw).json()["url"].startswith("https://connect.stripe.test")
            assert c.get("/payouts/me", headers=hw).json() == {"configured": True, "demo": False, "started": True, "ready": False, "commission_rate": 0.1}
            acct["ready"] = True
            assert c.get("/payouts/me", headers=hw).json()["ready"] is True
            assert c.post(f"/bookings/{b2['id']}/quote", headers=hw, json={"fee": 25.5}).json()["fee_cents"] == 2550
            pay = c.post(f"/bookings/{b2['id']}/pay", headers=hc).json()
            assert pay["mode"] == "stripe" and pay["client_secret"] == "pi_test_secret" and pay["publishable_key"] == "pk_test_x"
            pi = next(d for m_, p_, d in calls if p_ == "/payment_intents")
            assert pi["amount"] == 2550 and pi["application_fee_amount"] == 255 and pi["transfer_data"] == {"destination": "acct_test"}
            done = c.post(f"/bookings/{b2['id']}/confirm-payment", headers=hc).json()
            assert done["status"] == "paid" and done["commission_cents"] == 255 and done["worker_gets_cents"] == 2295
        finally:
            bk.stripe_call = real
            os.environ.pop("STRIPE_SECRET_KEY"); os.environ.pop("STRIPE_PUBLISHABLE_KEY")

        # Webhook signatures are checked.
        secret, payload = "whsec_x", json.dumps({"type": "ping"}).encode()
        ts = int(time.time())
        sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
        assert bk._signed(payload, f"t={ts},v1={sig}", secret)
        assert not bk._signed(payload, f"t={ts},v1={'0' * 64}", secret)
        assert not bk._signed(payload, f"t={ts - 999},v1={sig}", secret)


if __name__ == "__main__":
    test_lifecycle(); test_gemini_stubbed(); test_rating(); test_mjeshtrit(); test_translate(); test_chat(); test_street_search(); test_community(); test_fraud(); test_gemini_hedge(); test_bookings(); print("OK")
