# tools/demo_data.py
# Fills a folder with realistic sample data (dictation history, usage stats,
# notes, dictionary words) so the app's windows can be shown or screenshotted
# without anyone's real dictations. Point the app at it with APPDATA (Windows)
# or HOME (macOS):
#
#     python tools/demo_data.py C:\temp\demo
#     set APPDATA=C:\temp\demo && whisper-local --hub

import datetime
import json
import random
import sys
from pathlib import Path

SAMPLES = (
    ("Slack", "Sounds good, I'll have the draft over to you before lunch tomorrow."),
    ("Outlook", "Hi Priya, thanks for the quick turnaround. The revised numbers look right to me. "
                "Could you send the final deck to the leadership team by Friday?"),
    ("Code", "Refactor the retry loop so it backs off exponentially and gives up after five attempts."),
    ("Chrome", "best hiking trails near Asheville with waterfalls"),
    ("Notion", "Meeting notes: launch moves to the 14th, design review on Tuesday, "
               "and Sam owns the onboarding copy."),
    ("Slack", "Can we push standup to 10:15? I'm finishing a customer call."),
    ("Word", "The results suggest that the new onboarding flow reduced drop-off by nearly a third."),
    ("Teams", "Happy to help. Let me know if anything else comes up."),
    ("Outlook", "Following up on our conversation last week about the Q3 roadmap."),
    ("Code", "Add a unit test for the empty-input case."),
)


def main(folder: str):
    root = Path(folder) / 'whisperkey'
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    transcripts, stats = [], []
    for day_back in range(20, -1, -1):
        if day_back in (9, 10, 16):
            continue   # a few days off, so streaks are believable
        for _ in range(rng.randint(3, 9)):
            app, text = rng.choice(SAMPLES)
            when = now - datetime.timedelta(days=day_back, hours=rng.randint(0, 9), minutes=rng.randint(0, 59))
            if when > now:
                when = now - datetime.timedelta(minutes=rng.randint(1, 50))
            seconds = round(len(text) / 15.0, 1)
            transcripts.append({'timestamp': when.isoformat(timespec='seconds'), 'text': text,
                                'app': app.lower() + '.exe', 'duration_s': seconds, 'chars': len(text)})
            stats.append({'ts': when.isoformat(timespec='seconds'), 'chars': len(text),
                          'duration_s': seconds, 'app': app.lower() + '.exe'})
    transcripts.sort(key=lambda e: e['timestamp'])
    stats.sort(key=lambda e: e['ts'])
    (root / 'transcripts.jsonl').write_text('\n'.join(json.dumps(e) for e in transcripts) + '\n', encoding='utf-8')
    (root / 'stats.jsonl').write_text('\n'.join(json.dumps(e) for e in stats) + '\n', encoding='utf-8')
    (root / 'first_run_complete.txt').write_text('ok', encoding='utf-8')
    (root / 'user_settings.yaml').write_text(
        "whisper:\n  hotwords: [Priya, Asheville, Kubernetes, Notion]\n"
        "postprocess:\n  replacements:\n    - from: cooper netties\n      to: Kubernetes\n"
        "  snippets:\n    - trigger: my email\n      expansion: alex@example.com\n"
        "    - trigger: my sign off\n      expansion: \"Best,\\nAlex\"\n"
        "update_check:\n  enabled: false\n", encoding='utf-8')
    notes = root / 'notes'
    notes.mkdir(exist_ok=True)
    (notes / '20261101-090000-000000.md').write_text(
        "Launch checklist\n\n- Final copy review with Sam\n- Record the demo video\n"
        "- Email beta testers on Thursday\n", encoding='utf-8')
    (notes / '20261103-140000-000000.md').write_text(
        "Blog post ideas\n\nWhy I stopped typing first drafts. Speaking is three times faster, "
        "and the cleanup pass catches the ums.\n", encoding='utf-8')
    print(f"Demo data written to {root}")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'demo-data')
