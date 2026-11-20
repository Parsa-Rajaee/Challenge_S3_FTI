"""Retrieve and cache actual Brazilian public-holiday events."""
import json
from pathlib import Path
from urllib.request import Request,urlopen
def acquire_holidays(years,destination:Path,offline=False):
    destination.mkdir(parents=True,exist_ok=True); events={}
    for year in sorted({int(x) for x in years}):
        path=destination/f'holidays_br_{year}.json'
        if not path.is_file():
            if offline: raise FileNotFoundError(f'Missing offline holiday cache: {path}')
            with urlopen(Request(f'https://date.nager.at/api/v3/PublicHolidays/{year}/BR',headers={'User-Agent':'FTI-capstone/1'}),timeout=25) as response:
                payload=json.load(response)
            if not isinstance(payload,list): raise ValueError('Unexpected API response')
            path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        payload=json.loads(path.read_text(encoding='utf-8'))
        for event in payload:
            date=event['date']
            if not date.startswith(f'{year}-'): raise ValueError('Holiday year mismatch')
            events[date]=(date,event.get('localName') or event['name'],'Nager.Date')
    return list(events.values())
