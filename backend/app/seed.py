"""Creates the categories and a first admin account, and optionally the Prishtina demo data.

Env:
  ADMIN_EMAIL / ADMIN_PASSWORD  first admin (default admin@mendmap.local / admin123, change it!)
  SEED_DEMO=1                   add the Prishtina demo reports when the database has none

Replace all reports with a fresh Prishtina demo set (demo databases only!):
  python -m app.seed --reset-demo
"""
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select

from .auth import hash_password, verify_password
from .db import Base, SessionLocal, engine
from .demo_images import make_after_photo, make_photo
from .models import Category, Confirmation, Report, StatusUpdate, User, migrate, now, PartnerReward, Mjeshter

UPLOADS = Path(__file__).resolve().parent.parent / "uploads"

CATEGORIES = [
    ("Pothole", "pothole"),
    ("Streetlight", "streetlight"),
    ("Illegal dumping", "dumping"),
    ("Other", "other"),
    ("Accessibility", "accessibility"),
]

# Field crew account for the crew mode in the app (change the password outside demos).
CREW = ("Crew Prishtina", "crew@mendmap.local", "crew123")
# Arta's home area, so "near you" has something to show in the demo.
ARTA_HOME = (42.6612, 21.1622)

# Demo citizens. citizen@mendmap.local / citizen123 is the one to sign in with in the app.
CITIZENS = [
    ("Arta Krasniqi", "citizen@mendmap.local", "citizen123"),
    ("Driton Berisha", "driton@mendmap.local", "citizen123"),
    ("Blerina Gashi", "blerina@mendmap.local", "citizen123"),
    ("Ilir Hoxha", "ilir@mendmap.local", "citizen123"),
]

# Prishtina, Kosovo. Each report: (category icon, lat, lng, description, status, days ago,
# confirmations, reporter index, city comments for in_progress / fixed).
PRISHTINA = [
    ("pothole", 42.65950, 21.16250, "Gropë e thellë në korsinë e djathtë të Rrugës Agim Ramadani, afër semaforit. Makinat po e shmangin në mënyrë të rrezikshme.",
     "in_progress", 6, 9, 0, ("Ekipi i mirëmbajtjes është caktuar për të enjten.", None)),
    ("pothole", 42.65100, 21.14900, "Asfalti i çarë pranë vendkalimit për këmbësorë në Bulevardin Bill Klinton. Pas shiut mbushet me ujë.",
     "reported", 2, 4, 1, (None, None)),
    ("pothole", 42.65050, 21.16950, "Disa gropa njëra pas tjetrës në hyrje të lagjes Ulpiana. Biçikletat nuk mund të kalojnë.",
     "fixed", 21, 6, 2, ("Rruga u inspektua, riparimi planifikohet këtë javë.", "Gropat u mbushën dhe asfalti u rregullua.")),
    ("pothole", 42.64700, 21.15550, "Deep pothole on the main road through Dardania, next to the bus stop. Buses swerve around it.",
     "reported", 1, 7, 3, (None, None)),
    ("pothole", 42.66300, 21.15900, "Pllakat e trotuarit të ngritura dhe një gropë në Rrugën UÇK. Rrezik rrëzimi për këmbësorët.",
     "reported", 4, 2, 0, (None, None)),
    ("streetlight", 42.66200, 21.16200, "Ndriçimi publik nuk punon prej një jave në Bulevardin Nëna Terezë, pjesa afër Teatrit Kombëtar. Shumë errësirë natën.",
     "in_progress", 8, 11, 1, ("Elektricistët e komunës do ta ndërrojnë llambën.", None)),
    ("streetlight", 42.66750, 21.16450, "Dy shtylla ndriçimi të fikura në Parkun e Qytetit, te shtegu kryesor.",
     "fixed", 15, 5, 2, ("U dërgua ekipi.", "Llambat u ndërruan, ndriçimi punon.")),
    ("streetlight", 42.65450, 21.17900, "Streetlight flickering all night in Bregu i Diellit, block near the school.",
     "reported", 3, 3, 3, (None, None)),
    ("streetlight", 42.67050, 21.14950, "Kapaku i llambës është thyer dhe xhamat kanë rënë në trotuar në Arbëri (Dragodan).",
     "reported", 1, 1, 0, (None, None)),
    ("dumping", 42.67050, 21.18500, "Mbeturina ndërtimore dhe qese plehrash të hedhura buzë rrugës për në Gërmi.",
     "reported", 5, 12, 1, (None, None)),
    ("dumping", 42.64150, 21.15000, "Mobilie të vjetra dhe qese të hedhura pas ndërtesave në Kalabri.",
     "in_progress", 9, 6, 2, ("Kompania e pastrimit është njoftuar.", None)),
    ("dumping", 42.65800, 21.15850, "Plehra të grumbulluara pranë kontejnerëve në Rrugën Fehmi Agani, nuk janë marrë prej ditësh.",
     "fixed", 12, 8, 3, ("Pastrimi u planifikua.", "Zona u pastrua nga ekipi i pastrimit.")),
    ("dumping", 42.66350, 21.17200, "Illegal dumping of tyres and rubble behind the shops in Mati 1.",
     "reported", 2, 2, 0, (None, None)),
    ("other", 42.66100, 21.16000, "Mungon kapaku i pusetës në Rrugën Garibaldi. Dikush ka vendosur një kon, por është shumë e rrezikshme.",
     "in_progress", 3, 14, 0, ("Ekipi i ujësjellësit do ta vendosë kapakun e ri sot.", None)),
    ("other", 42.66250, 21.16400, "Ulësja në sheshin Zahir Pajaziti është e thyer, një dërrasë ka rënë.",
     "fixed", 18, 3, 1, ("U regjistrua.", "Ulësja u riparua.")),
    ("other", 42.65900, 21.15750, "Shenja e trafikut e përkulur pas një aksidenti në Rrugën Rexhep Luci, nuk shihet nga shoferët.",
     "reported", 2, 4, 2, (None, None)),
    ("accessibility", 42.66080, 21.16150, "Një makinë është parkuar mbi rampën për karrocat te vendkalimi në Rrugën Luan Haradinaj. Personat me karrige me rrota nuk kalojnë dot.",
     "reported", 1, 6, 1, (None, None)),
    ("accessibility", 42.64820, 21.15420, "Broken wheelchair ramp at the crossing next to the school in Dardania: the slab is cracked and there is a step.",
     "in_progress", 5, 8, 3, ("Ekipi do ta rindërtojë rampën këtë javë.", None)),
    ("accessibility", 42.65180, 21.17080, "Mungon rampa te trotuari pranë shkollës në Ulpianë. Prindërit me karroca duhet të zbresin në rrugë.",
     "fixed", 14, 5, 2, ("U planifikua rampa e re.", "Rampa u ndërtua dhe u vendosën shtylla që makinat të mos parkojnë.")),
]

# AI-style severity for each demo report (1-5), in the same order as PRISHTINA.
SEVERITY = [4, 3, 3, 4, 3, 4, 2, 2, 3, 3, 3, 2, 3, 5, 1, 3, 4, 4, 3]


# Demo mjeshtrit (skilled volunteers), already verified by the city: name, email, skills, days, area, bio.
MJESHTRIT = [
    ("Arben Krasniqi", "arben@mendmap.local", "plumbing,building", "saturday,sunday", "Kalabria",
     "Plumber for 15 years. Happy to fix drains and paving on Sundays."),
    ("Blerta Hoxha", "blerta@mendmap.local", "painting,carpentry", "sunday,holidays", "Dardania",
     "Painter and carpenter. Benches, fences, playgrounds."),
    ("Dritan Berisha", "dritan@mendmap.local", "welding,gardening", "weekday_evenings,sunday", "Ulpiana",
     "Welder. I can fix railings, gates and bike racks."),
]


def seed_mjeshtrit(db) -> int:
    added = 0
    for name, email, skills, days, area, bio in MJESHTRIT:
        u = _citizen(db, name, email, "mjeshter123")
        u.neighbourhood = u.neighbourhood or area
        if not db.scalar(select(Mjeshter).where(Mjeshter.user_id == u.id)):
            db.add(Mjeshter(user_id=u.id, skills=skills, verified_skills=skills, days=days, neighbourhood=area, bio=bio,
                            status="approved", verified_by="admin", ai_verdict="legit"))
            added += 1
    db.commit()
    return added


# Demo partner rewards. Admins add, edit and hide real ones in the dashboard.
PARTNERS = [
    ("Kafe Lagjja", "2 free coffees", "Show the code at the counter.", "☕", 5, None),
    ("Kino Qyteti", "2 cinema tickets", "Any film, any day. Show the code at the ticket desk.", "🎬", 10, 30),
    ("Zhuzuff Kitchen", "Free dinner for 2", "Two main dishes and drinks. Book a table and show the code.", "🍽️", 20, 10),
]


def seed() -> None:
    with SessionLocal() as db:
        have = set(db.scalars(select(Category.icon)))
        db.add_all(Category(name=n, icon=i) for n, i in CATEGORIES if i not in have)  # also adds new ones later

        admin_email = os.getenv("ADMIN_EMAIL", "admin@mendmap.local")
        if not db.scalar(select(User).where(User.email == admin_email)):
            db.add(User(
                name="City Admin",
                email=admin_email,
                password_hash=hash_password(os.getenv("ADMIN_PASSWORD") or "admin123"),
                role="admin",
            ))
        if os.getenv("SEED_DEMO") == "1" or os.getenv("SEED_CREW") == "1":
            _crew(db)
        if os.getenv("SEED_DEMO") == "1":
            _citizen(db, *CITIZENS[0])  # the demo resident, also when the database already has reports
        db.commit()
        admin = db.scalar(select(User).where(User.email == admin_email))
        if os.getenv("SEED_DEMO") != "1" and admin and verify_password("admin123", admin.password_hash):
            logging.getLogger("mendmap").warning(
                "The admin %s still has the default password admin123. Change it before real people use MendMap.",
                admin_email)

        if os.getenv("SEED_DEMO") == "1" and not db.scalar(select(Report).limit(1)):
            seed_prishtina(db)
        if os.getenv("SEED_DEMO") == "1" and not db.scalar(select(Mjeshter).limit(1)):
            seed_mjeshtrit(db)
        if os.getenv("SEED_DEMO") == "1" and not db.scalar(select(PartnerReward).limit(1)):
            db.add_all(PartnerReward(partner=p, title=t, details=d, emoji=e, cost=c, stock=n) for p, t, d, e, c, n in PARTNERS)
            db.commit()


# One-tap demo sign-in (login screen and city dashboard), only while SEED_DEMO=1.
# role, what it shows, email, password. An account is only listed while it still has this password.
DEMO_ACCOUNTS = [
    ("admin", "City admin: dashboard, status changes, rewards", "admin@mendmap.local", "admin123"),
    ("crew", "Field crew: jobs route, after photos", CREW[1], CREW[2]),
    ("citizen", "Resident: report, map, fix & earn", CITIZENS[0][1], CITIZENS[0][2]),
    ("mjeshter", "Mjeshtër: verified skilled volunteer", MJESHTRIT[0][1], "mjeshter123"),
]


def demo_accounts(db) -> list[dict]:
    if os.getenv("SEED_DEMO") != "1":
        return []
    out = []
    for role, about, email, password in DEMO_ACCOUNTS:
        u = db.scalar(select(User).where(User.email == email))
        if u and verify_password(password, u.password_hash):
            out.append({"role": role, "about": about, "name": u.name, "email": email, "password": password})
    return out


def _citizen(db, name: str, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(name=name, email=email, password_hash=hash_password(password))
        db.add(user)
        db.flush()
    else:
        user.name = name
    return user


def _crew(db) -> User:
    name, email, password = CREW
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(name=name, email=email, password_hash=hash_password(password), role="crew")
        db.add(user)
        db.flush()
    return user


def seed_prishtina(db) -> int:
    cats = {c.icon: c for c in db.scalars(select(Category))}
    admin = db.scalar(select(User).where(User.role == "admin"))
    crew = _crew(db)
    people = [_citizen(db, *c) for c in CITIZENS]
    people[0].home_lat, people[0].home_lng = ARTA_HOME
    # Where each demo citizen lives: they can take neighbour-fix jobs there.
    for person, area in zip(people, ("Qendra", "Dardania", "Ulpiana", "Kalabria")):
        person.neighbourhood = area

    reports = []
    for i, (icon, lat, lng, desc, status, days, confirms, who, (c1, c2)) in enumerate(PRISHTINA):
        created = now() - timedelta(days=days, hours=3 + i)
        report = Report(
            user_id=people[who].id, category_id=cats[icon].id, description=desc,
            photo_url=make_photo(icon, 100 + i, UPLOADS),
            after_photo_url=make_after_photo(icon, 100 + i, UPLOADS) if status == "fixed" else None,
            severity=SEVERITY[i],
            latitude=lat, longitude=lng, status=status, confirmations=confirms,
            created_at=created, updated_at=created,
        )
        report.updates.append(StatusUpdate(new_status="reported", comment="Report submitted", created_at=created))
        t = created
        if status in ("in_progress", "fixed"):
            t = min(created + timedelta(days=max(0.3, days * 0.25)), now() - timedelta(hours=2))
            report.updates.append(StatusUpdate(admin_id=admin.id, old_status="reported", new_status="in_progress",
                                               comment=c1, created_at=t))
        if status == "fixed":
            t = min(t + timedelta(days=max(0.5, days * 0.4)), now() - timedelta(hours=1))
            report.updates.append(StatusUpdate(admin_id=crew.id, old_status="in_progress", new_status="fixed",
                                               comment=c2, created_at=t))
        report.updated_at = t
        db.add(report)
        reports.append(report)
    db.flush()
    # Neighbour fixes: Arta (Qendra) cleaned up fixed jobs in her area. The newest one waits for
    # the city's check, so the admin panel's "Neighbour fixes" tab has something to show.
    from .insights import NEIGHBOUR_FIXABLE, neighbourhood
    done = [r for r in reports if r.status == "fixed" and PRISHTINA[reports.index(r)][0] in NEIGHBOUR_FIXABLE
            and neighbourhood(r.latitude, r.longitude) == people[0].neighbourhood]
    for n, r in enumerate(done):
        r.claimer = people[0]
        r.claimed_at = r.created_at
        r.fix_status = "pending" if n == 0 else "verified"
        r.updates[-1].comment = "Fixed by a neighbour. Cleared it with friends from the street."
    # Arta pressed "I see this too" on two reports by neighbours (counts toward a badge).
    for r in (reports[5], reports[9]):
        db.add(Confirmation(report_id=r.id, user_id=people[0].id))
    db.commit()
    return len(PRISHTINA)


def reset_demo() -> None:
    """Deletes every report and loads the Prishtina demo set. Only for demo databases."""
    Base.metadata.create_all(engine)
    migrate(engine)
    seed()
    with SessionLocal() as db:
        db.execute(delete(Confirmation))
        db.execute(delete(StatusUpdate))
        db.execute(delete(Report))
        db.commit()
        for old in UPLOADS.glob("demo-*.jpg"):
            old.unlink()
        _crew(db)
        n = seed_prishtina(db)
    print(f"Loaded {n} Prishtina demo reports with photos.")


if __name__ == "__main__":
    if "--reset-demo" in sys.argv:
        reset_demo()
    else:
        print(__doc__)
