# Adding a politician

The platform is keyed on **`KNS_Person.Id`** from the ParliamentInfo OData V4
service. Onboarding any MK is two steps: (1) find their `Id`, (2) ingest it.
The pilot is Benjamin Netanyahu, `Id = 965`.

> Run every Python/CLI command with the venv interpreter:
> `C:/Users/noams/knesset-osint/.venv/Scripts/python.exe` (or the installed
> `knesset-osint` console script).

---

## Step 1 — Find the `KNS_Person.Id`

Filter `KNS_Person` by last name. `httpx` URL-encodes the Hebrew automatically;
when probing by hand with `curl`, the value must be URL-encoded.

`KNS_Person` fields (verified live 2026-06-20): `Id`, `LastName`, `FirstName`,
`GenderDesc`, `Email`, `IsCurrent`, `LastUpdatedDate`.

```bash
# Live probe (manual). Netanyahu: LastName = נתניהו -> Id 965, FirstName בנימין.
curl -s "https://knesset.gov.il/OdataV4/ParliamentInfo/KNS_Person?\$filter=LastName%20eq%20'%D7%A0%D7%AA%D7%A0%D7%99%D7%94%D7%95'&\$format=json"
```

The OData filter expression is simply:

```
LastName eq 'נתניהו'
```

Tips when several people share a surname:

- Add `FirstName`: `LastName eq 'X' and FirstName eq 'Y'`.
- Restrict to sitting MKs: `... and IsCurrent eq true`.
- Confirm by eye using `Email` / `GenderDesc` in the returned rows.

If you prefer not to hand-craft `curl`, the CLI can do the lookup for you:

```bash
knesset-osint find-person --last-name "נתניהו"
# prints matching Id / FirstName / LastName / IsCurrent rows
```

---

## Step 2 — Ingest

Run the ingest command with the `Id` you found:

```bash
knesset-osint ingest --person-id 965
# or, via the venv interpreter:
C:/Users/noams/knesset-osint/.venv/Scripts/python.exe -m knesset_osint.cli ingest --person-id 965
```

This drives the full pipeline for that person (see
[ARCHITECTURE.md](ARCHITECTURE.md) for the flow):

1. **Person** — fetch `KNS_Person(Id eq <id>)`, upsert a `Politician`
   (`knesset_person_id`, `first_name`, `last_name`, `gender`, `email`,
   `is_current`), provenance copied from the `RawRecord`.
2. **Roles / parties** — fetch `KNS_PersonToPosition?$filter=PersonID eq <id>`
   and upsert `Role` rows.
3. **Bills** — fetch `KNS_BillInitiator?$filter=PersonID eq <id>` (Netanyahu has
   31 rows), upsert `BillSponsorship`, and resolve each `Bill` via
   `KNS_Bill?$filter=Id eq <BillID>`.
4. **Votes** — reconcile the person to the Votes service MK id and ingest
   `VoteEvent` + `Vote` rows from the V3 `Votes.svc` tables.

Re-running is **idempotent** (upserts keyed on natural keys), so you can refresh
any time.

---

## How parties and roles populate

There is no separate "party" table — party/faction and office history live on
`Role`, sourced from **`KNS_PersonToPosition`**.

`KNS_PersonToPosition` fields (verified live): `Id`, `PersonID`, `PositionID`,
`KnessetNum`, `StartDate`, `FinishDate`, `GovMinistryID`, `GovMinistryName`,
`DutyDesc`, `FactionID`, `FactionName`, `GovernmentNum`, `CommitteeID`,
`CommitteeName`, `IsCurrent`.

Mapped onto `Role`:

| `KNS_PersonToPosition` | `Role` column |
|---|---|
| `PositionID` | `position_id` |
| `DutyDesc` | `position_desc` |
| `KnessetNum` | `knesset_num` |
| `GovernmentNum` | `government_num` |
| `GovMinistryName` | `ministry_name` |
| `FactionName` | `faction_name` |
| `CommitteeName` | `committee_name` |
| `StartDate` / `FinishDate` | `start_date` / `finish_date` (Date) |
| `IsCurrent` | `is_current` |

The politician's **current party** is derived from their current faction:
`Politician.current_party` is set from the `FactionName` of the role whose
`IsCurrent` is true (for the pilot this resolves to הליכוד / Likud,
`settings.pilot_party_he` / `settings.pilot_party_en`).

---

## How votes attach (Person ↔ MK id reconciliation)

`KNS_Person.Id` is **not** guaranteed to equal the Votes service's MK id. The
pipeline reconciles by matching `FirstName + LastName` via
`View_Vote_MK_Individual` (Votes V3) and stores the resolved id in
`Politician.external_ids['votes_mk_id']`. From then on, votes for that MK are
fetched and upserted as `VoteEvent` + `Vote` (`stance`).

> The exact column names of the V3 vote tables are not pre-verified — the mappers
> probe live and read defensively. If a member's votes don't attach, confirm the
> reconciliation matched a row in `View_Vote_MK_Individual` (name spelling /
> nikud differences are the usual culprit).

---

## Verify

```bash
knesset-osint show --person-id 965     # per-source counts for the politician
# or via the API: GET http://localhost:8000/politicians/965
```

For Netanyahu you should see 1 `Politician` (`knesset_person_id = 965`,
`last_name = נתניהו`), his roles, ~31 bill sponsorships, and his reconciled
votes. Zeros usually mean the live endpoint was unreachable or `.env` wasn't
loaded — re-check with the `curl` probe in Step 1.
