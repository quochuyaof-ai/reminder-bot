import json, os, urllib.request, datetime

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]
ALL_DAYS  = "mon,tue,wed,thu,fri,sat,sun"
DAY_NAMES = ["mon","tue","wed","thu","fri","sat","sun"]

now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
H, M = now.hour, now.minute
day  = DAY_NAMES[now.weekday()]

with open("reminders.json", encoding="utf-8") as f:
    reminders = json.load(f)

fired = 0
for r in reminders:
    if r.get("paused"):
        continue
    if r["hour"] != H:
        continue
    if not (r["minute"] <= M < r["minute"] + 5):
        continue
    days = r.get("days", ALL_DAYS)
    if day not in days.split(","):
        continue
    data = json.dumps({"chat_id": CHAT_ID, "text": r["text"]}).encode()
    req  = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=data, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req)
    print(f"Sent: {r['hour']:02d}:{r['minute']:02d} — {r['text']}")
    fired += 1

print(f"Done: {H:02d}:{M:02d} {day} | {len(reminders)} reminders | {fired} fired")
