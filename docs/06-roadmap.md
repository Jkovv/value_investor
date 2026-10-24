# 06. Roadmap

## Deeper history outside the US

Yahoo gives every market four to five years. Official XBRL sources can add depth market by market,
feeding the same facts table:

| Source | Covers | History | Needs |
|---|---|---|---|
| filings.xbrl.org (ESEF) | EU/EEA regulated markets + UK, including Warsaw | from FY2020, annual | nothing |
| EDINET API v2 | Japan | ~10 years | a free key (phone verification) |
| OpenDART | Korea | ~10 years | a free key |

`concepts.py` already maps `ifrs-full`, which ESEF uses.

## Alerts

`python main.py digest` already records what changed on the watchlist; scheduled weekly it does the
job of an alert (see [commands.md](../commands.md)). What's missing is delivery: it writes to the
terminal, a file and the dashboard, not to email or a phone. Insider trades are US only, since
EDGAR is the one free and complete source.

## A fuller test

`python main.py study` already scores every company as of each June since 2010 and sets the score
against what followed ([09 Does it work?](09-evidence.md)). What would make it stronger:

- the whole US market instead of the 397 large companies stored now (`python ingest.py --us`);
- prices for delisted companies, which no free source has, so the sample stays survivors only;
- the figures as first filed for the sources that only give restated ones.

The agents can't be tested on the past: the model has read what happened since.

Next: **[07 Research agents](07-research-agents.md)**.
