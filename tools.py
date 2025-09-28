import logging
from livekit.agents import function_tool, RunContext
import requests
from langchain_community.tools import DuckDuckGoSearchRun
import json
from datetime import datetime, date, timedelta
from pathlib import Path

@function_tool()
async def get_weather(
    context: RunContext,  # type: ignore
    city: str) -> str:
    """
    Get the current weather for a given city.
    """
    try:
        response = requests.get(
            f"https://wttr.in/{city}?format=3")
        if response.status_code == 200:
            logging.info(f"Weather for {city}: {response.text.strip()}")
            return response.text.strip()   
        else:
            logging.error(f"Failed to get weather for {city}: {response.status_code}")
            return f"Could not retrieve weather for {city}."
    except Exception as e:
        logging.error(f"Error retrieving weather for {city}: {e}")
        return f"An error occurred while retrieving weather for {city}." 

@function_tool()
async def search_web(
    context: RunContext,  # type: ignore
    query: str) -> str:
    """
    Search the web using DuckDuckGo.
    """
    try:
        results = DuckDuckGoSearchRun().run(tool_input=query)
        logging.info(f"Search results for '{query}': {results}")
        return results
    except Exception as e:
        logging.error(f"Error searching the web for '{query}': {e}")
        return f"An error occurred while searching the web for '{query}'."


# ==========================
# Medicine Checklist Tools
# ==========================

DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "medicines.json"

def _load_db() -> dict:
    try:
        if not DATA_FILE.exists():
            return {"medicines": []}
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"medicines": []}

def _save_db(db: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def _normalize_time_str(t: str) -> str:
    t = t.strip().lower()
    fmts = ["%H:%M", "%I:%M %p", "%I %p"]
    for fmt in fmts:
        try:
            d = datetime.strptime(t, fmt)
            return d.strftime("%H:%M")
        except ValueError:
            continue
    if t.isdigit():
        h = int(t)
        if 0 <= h <= 23:
            return f"{h:02d}:00"
    raise ValueError(f"Invalid time format: {t}")

def _today_str() -> str:
    return date.today().isoformat()

@function_tool()
async def add_medicine(
    context: RunContext,  # type: ignore
    name: str,
    times: str,
    dosage: str = "",
    notes: str = "",
) -> str:
    """
    Add or update a medicine with one or more times per day.
    - name: Medicine name (e.g., "Metformin")
    - times: Comma-separated times like "8 am, 20:30" or "08:00, 14:00"
    - dosage: Optional dosage text (e.g., "500 mg")
    - notes: Optional notes (e.g., "after food")
    """
    try:
        parsed_times = []
        for t in times.split(','):
            if t.strip():
                parsed_times.append(_normalize_time_str(t))
        parsed_times = sorted(set(parsed_times))
        if not parsed_times:
            return "No valid times provided."

        db = _load_db()
        meds = db.get("medicines", [])
        existing = next((m for m in meds if m["name"].lower() == name.lower()), None)
        if existing:
            existing["times"] = parsed_times
            existing["dosage"] = dosage
            existing["notes"] = notes
        else:
            meds.append({
                "name": name,
                "times": parsed_times,
                "dosage": dosage,
                "notes": notes,
                "taken_log": {},
            })
        db["medicines"] = meds
        _save_db(db)
        return f"Added/updated medicine '{name}' at {', '.join(parsed_times)}."
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        logging.error(f"add_medicine error: {e}")
        return "Failed to add medicine due to an internal error."

@function_tool()
async def list_medicines(
    context: RunContext,  # type: ignore
) -> str:
    """
    List all medicines with times, dosage, and notes.
    """
    db = _load_db()
    meds = db.get("medicines", [])
    if not meds:
        return "No medicines found."
    lines = []
    for m in meds:
        line = f"- {m['name']}: times {', '.join(m['times'])}"
        if m.get("dosage"):
            line += f", dosage {m['dosage']}"
        if m.get("notes"):
            line += f", notes {m['notes']}"
        lines.append(line)
    return "\n".join(lines)

@function_tool()
async def remove_medicine(
    context: RunContext,  # type: ignore
    name: str,
) -> str:
    """
    Remove a medicine by name.
    """
    db = _load_db()
    meds = db.get("medicines", [])
    new_meds = [m for m in meds if m["name"].lower() != name.lower()]
    if len(new_meds) == len(meds):
        return f"Medicine '{name}' not found."
    db["medicines"] = new_meds
    _save_db(db)
    return f"Removed medicine '{name}'."

@function_tool()
async def mark_medicine_taken(
    context: RunContext,  # type: ignore
    name: str,
) -> str:
    """
    Mark a medicine as taken for today (records timestamp).
    """
    db = _load_db()
    meds = db.get("medicines", [])
    m = next((m for m in meds if m["name"].lower() == name.lower()), None)
    if not m:
        return f"Medicine '{name}' not found."
    today = _today_str()
    now_str = datetime.now().strftime("%H:%M")
    taken_log = m.get("taken_log", {})
    taken_today = taken_log.get(today, [])
    taken_today.append(now_str)
    taken_log[today] = taken_today
    m["taken_log"] = taken_log
    _save_db(db)
    return f"Marked '{name}' as taken at {now_str} today."

@function_tool()
async def next_medicine_due(
    context: RunContext,  # type: ignore
) -> str:
    """
    Show the next due medicine time for today (or tomorrow if none left today).
    """
    db = _load_db()
    meds = db.get("medicines", [])
    now = datetime.now()
    today = date.today()
    upcoming = []
    for m in meds:
        for t in m.get("times", []):
            try:
                hh, mm = map(int, t.split(":"))
                dt = datetime.combine(today, datetime.min.time()).replace(hour=hh, minute=mm)
                if dt >= now:
                    upcoming.append((dt, m["name"], t))
            except Exception:
                continue
    if not upcoming:
        tomorrow = today + timedelta(days=1)
        earliest = None
        for m in meds:
            for t in m.get("times", []):
                try:
                    hh, mm = map(int, t.split(":"))
                    dt = datetime.combine(tomorrow, datetime.min.time()).replace(hour=hh, minute=mm)
                    if earliest is None or dt < earliest[0]:
                        earliest = (dt, m["name"], t)
                except Exception:
                    continue
        if earliest:
            when_str = earliest[0].strftime("%Y-%m-%d %H:%M")
            return f"Next due: {earliest[1]} at {when_str}"
        return "No upcoming medicines found."
    upcoming.sort(key=lambda x: x[0])
    first = upcoming[0]
    when_str = first[0].strftime("%Y-%m-%d %H:%M")
    return f"Next due: {first[1]} at {when_str}"
