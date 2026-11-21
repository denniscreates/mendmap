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

        # 20 verified fixes = 20 fixer badges = one 10 euro reward.
        for i in range(20):
            jid = job["id"] if i == 0 else dumping()["id"]
            assert c.post(f"/reports/{jid}/claim", headers=hq).status_code == 200
            c.post(f"/reports/{jid}/neighbour-fixed", headers=hq, files={"after_photo": ("a.png", PNG, "image/png")})
            assert c.post(f"/admin/reports/{jid}/verify-fix", headers=hx, json={"ok": True}).json()["fix_status"] == "verified"
        f = c.get("/me/fixer", headers=hq).json()
        assert (f["verified"], f["rewards_earned"], f["rewards_paid"], f["reward_eur"]) == (20, 1, 0, 10)
        owed = c.get("/admin/rewards", headers=hx).json()
        assert owed[0]["user_id"] == q["user"]["id"] and owed[0]["owed_eur"] == 10
        assert c.post(f"/admin/rewards/{q['user']['id']}/paid", headers=hx).json()["owed_eur"] == 0
        assert c.get("/me/fixer", headers=hq).json()["rewards_paid"] == 1
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

    class FakeModels:
        async def generate_content(self, model, contents, config=None):
            mime = contents[0].inline_data.mime_type
            calls.append((model, mime))
            if mime.startswith("image/"):
                text = ('{"is_street_problem": true, "category": "dumping", "severity": 9, "reason": "Rubbish on the pavement.",'
                        ' "neighbour_safe": ' + ("true" if SAFE[0] else "false") + ', "safety_reason": "Bags and gloves are enough."}')
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


if __name__ == "__main__":
    test_lifecycle(); test_gemini_stubbed(); test_fraud(); test_gemini_hedge(); print("OK")
